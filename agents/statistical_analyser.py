"""Analysis-script-writing node.

Makes a single LLM call over `state["dataset_summary"]` (a
`schemas.schema_inspect_data.DatasetSummary`) and `state["study_plan"]` (a
`schemas.schema_study_planer.StudyPlan`) to produce a structured
`schemas.analysis_script_plan.AnalysisScriptPlan`: a runnable Python script
plus, alongside it, an explicit account of every cross-file join and every
plan decision the script implements, so a reviewer can catch a wrong join
or a skipped normalization step without reading the whole script.

Sandbox mount contract (see `sandbox/run_code.py`): the generated script
always runs as `python /workspace/code.py` inside a container with the raw
input files bind-mounted read-only at `/input/<basename>` and a writable
workspace at `/workspace`. The LLM is told this explicitly and given the
exact basenames of `state["data_raw_paths"]`, since DatasetSummary/StudyPlan
only carry host paths, which do not exist inside the sandbox.

The agent is explicitly allowed to skip any StudyPlan stage it cannot
confidently turn into code, rather than emit code it is not sure is
correct: a skipped stage still needs a `PlanImplementationStep` entry
(`matches_plan=False`, with `deviation_reason`) so the gap is visible, but
must not block the stages it *could* implement.

If no DENBI_TOKEN is configured, the LLM call fails, or dataset_summary/
study_plan are unavailable, this node falls back to a minimal
`AnalysisScriptPlan` whose script only proves the sandbox wiring works:
list `/input`, write a marker file to `/workspace`. The failure is recorded
in `issues` and in the plan's own `open_questions`.
"""

import os
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from graph.state import MetaproteomicsAnalysisState
from schemas.analysis_script_plan import AnalysisScriptPlan, OutputArtifact, ScriptSection
from schemas.schema_inspect_data import DatasetSummary

DEFAULT_MODEL_NAME = "vllm/Qwen/Qwen3.6-35B-A3B"
DEFAULT_API_BASE_URL = "https://llm.bi.denbi.de/v1"

SYSTEM_PROMPT = """
You are a metaproteomics analysis-script-writing agent. You receive a
DatasetSummary (from an upstream inspection agent) and a StudyPlan (from an
upstream planning agent) and must produce an AnalysisScriptPlan: a runnable
Python script plus a structured account of every join and plan decision it
implements, so a reviewer can check your work without reading the whole
script.

Sandbox execution contract (fixed, non-negotiable, do not deviate from it):
- Your script always runs as `python /workspace/code.py` inside a Docker
  container with no network access.
- Every input file is mounted read-only at /input/<basename>, where
  <basename> is exactly one of the names given to you as input_files below.
  Never use the host paths shown inside DatasetSummary/StudyPlan (e.g.
  MatrixInfo.path, DataPointer.file_path) directly -- rewrite them to
  /input/<basename> using only the file's basename.
- /workspace is writable and is where every artifact in outputs_manifest
  must be written, using paths relative to /workspace (e.g.
  "differential_abundance_results.csv", not "/workspace/..." or a host
  path).
- Only pandas, numpy, scipy, and matplotlib are guaranteed to be installed.

You do not have to implement every StudyPlan stage. If you cannot write
code for a stage that you are confident is correct (e.g. a batch-correction
or differential-abundance method you are unsure how to implement safely),
skip that stage rather than emit code that might silently do the wrong
thing. Every stage you implement must still produce a runnable script:
prefer a smaller, fully working script over a larger, broken one. Every
skipped stage still needs a PlanImplementationStep entry with
matches_plan=false and a deviation_reason stating that it was skipped and
why, with implemented_as describing what a human would need to do instead.

Data linkage is the highest-priority section: for every entry in
DatasetSummary.data_linkage, produce one DataLinkImplementation (same
order, referenced by data_link_index). Protein-group-style IDs are
frequently reassigned per export and are NOT safe to join on directly, even
when two files both look numerically indexed -- whenever the referenced
DataLink's cardinality is many_to_many or its notes warn about reassigned
IDs, join_key_is_accession_not_group_index must be true and
join_key_column must name the underlying accession/identifier column, not
a raw protein-group index. State explicitly, never implicitly, what
happens to rows that fail to match: dropped, kept as NA, or logged.

Prefer `script` as an ordered list[ScriptSection] (from among setup,
load_data, data_linkage, qc, filtering, normalization, batch_correction,
differential_abundance, visualization, export_outputs, other) over one
opaque script string, so each stage is independently inspectable and
re-runnable. depends_on must only name sections that appear earlier in
your list. Fall back to a single str only for a script too trivial for
staged sections to make sense.

Map every StudyPlan decision you act on into the matching
*_implementation list (qc_implementation, filtering_implementation,
normalization_implementation, batch_implementation,
differential_abundance_implementation, visualization_implementation),
describing how it was actually implemented (or why it was skipped), not
just repeating the plan.

Carry forward into assumptions_and_gaps any DatasetSummary.open_questions
or StudyPlan.open_questions you had to resolve to write the script, plus
any new assumption introduced only at code-writing time (e.g. a numeric
imputation floor). Put anything still unresolved into open_questions.
""".strip()


def _analyser_model():
    api_token = os.getenv("DENBI_TOKEN")
    if not api_token:
        raise RuntimeError("DENBI_TOKEN is not set")
    model_name = os.getenv("DENBI_MODEL", DEFAULT_MODEL_NAME)
    api_base_url = os.getenv("DENBI_API_BASE", DEFAULT_API_BASE_URL)
    # json_schema constrains decoding directly via response_format instead of
    # relying on the model choosing to invoke a tool call (function_calling);
    # self-hosted/gateway-served models often support the former far more
    # reliably than OpenAI-style forced tool-choice.
    return ChatOpenAI(
        model=model_name, base_url=api_base_url, api_key=api_token, temperature=0
    ).with_structured_output(AnalysisScriptPlan, method="json_schema")


def _topological_sections(sections: list[ScriptSection]) -> list[ScriptSection]:
    """Order sections depends_on-first so a partial re-run of the flattened
    script still respects declared dependencies; ties keep the author's
    original order. A dependency cycle is broken silently (best effort:
    this is a review/execution convenience, not a correctness guarantee
    the schema itself enforces)."""
    by_name = {section.name: section for section in sections}
    ordered: list[ScriptSection] = []
    done: set[str] = set()
    in_progress: set[str] = set()

    def visit(section: ScriptSection) -> None:
        if section.name in done or section.name in in_progress:
            return
        in_progress.add(section.name)
        for dep_name in section.depends_on:
            dep_section = by_name.get(dep_name)
            if dep_section is not None:
                visit(dep_section)
        in_progress.discard(section.name)
        done.add(section.name)
        ordered.append(section)

    for section in sections:
        visit(section)
    return ordered


def render_analysis_script(plan: AnalysisScriptPlan) -> str:
    """Flatten AnalysisScriptPlan.script into a single workspace/code.py body.

    A plain str script is returned unchanged; a list[ScriptSection] is
    reordered depends_on-first and concatenated with a header comment per
    section, so the file stays legible as staged, independently reviewable
    blocks even once it is one script on disk."""
    if isinstance(plan.script, str):
        return plan.script

    blocks = [
        f"# === {section.name}: {section.purpose} ===\n{section.code.strip()}\n"
        for section in _topological_sections(plan.script)
    ]
    return "\n".join(blocks)


def _fallback_plan(
    dataset_summary: DatasetSummary | None,
    input_basenames: list[str],
    reason: str,
) -> AnalysisScriptPlan:
    study_design_case = dataset_summary.study_design_case if dataset_summary is not None else "unknown"
    setup_code = "from pathlib import Path\n\ninput_dir = Path('/input')\nworkspace_dir = Path('/workspace')\n"
    export_code = (
        "input_files = sorted(p.name for p in input_dir.iterdir()) if input_dir.exists() else []\n"
        "(workspace_dir / 'sandbox_connectivity_check.txt').write_text(\n"
        "    'sandbox connectivity check\\n'\n"
        "    f'input files visible under /input: {input_files}\\n'\n"
        "    'workspace is writable: True\\n'\n"
        ")\n"
        "print('sandbox connectivity check complete')\n"
    )
    return AnalysisScriptPlan(
        study_design_case=study_design_case,
        summary=f"Fallback sandbox connectivity check: {reason}",
        data_linkage_implementation=[],
        script=[
            ScriptSection(
                name="setup",
                purpose="Resolve the fixed /input and /workspace sandbox mount points.",
                code=setup_code,
                depends_on=[],
            ),
            ScriptSection(
                name="export_outputs",
                purpose="Prove the sandbox ran end-to-end: list /input and write a marker file to /workspace.",
                code=export_code,
                depends_on=["setup"],
            ),
        ],
        outputs_manifest=[
            OutputArtifact(
                path="sandbox_connectivity_check.txt",
                kind="log",
                description="Marker file proving the generated script ran inside the sandbox and could read /input and write /workspace.",
                produced_by_section="export_outputs",
            )
        ],
        open_questions=[reason, f"input files known at fallback time: {input_basenames}" if input_basenames else "no input files were known at fallback time"],
    )


def statistical_analyser_node(state: MetaproteomicsAnalysisState) -> dict:
    dataset_summary = state.get("dataset_summary")
    study_plan = state.get("study_plan")
    input_basenames = sorted({Path(path).name for path in state.get("data_raw_paths", [])})

    if dataset_summary is None or study_plan is None:
        reason = (
            "statistical_analyser: missing dataset_summary or study_plan, "
            "producing a sandbox connectivity check script only"
        )
        return {
            "analysis_script_plan": _fallback_plan(dataset_summary, input_basenames, reason),
            "issues": [reason],
        }

    message = (
        "Write an AnalysisScriptPlan implementing this StudyPlan against this "
        "DatasetSummary. Input files available inside the sandbox at "
        f"/input/<name>, where <name> is one of: {input_basenames}\n\n"
        "DatasetSummary:\n" + dataset_summary.model_dump_json(indent=2) + "\n\n"
        "StudyPlan:\n" + study_plan.model_dump_json(indent=2)
    )

    try:
        plan = _analyser_model().invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]
        )
    except Exception as exc:
        reason = (
            f"statistical_analyser LLM call failed, using sandbox connectivity "
            f"check script: {type(exc).__name__}: {exc}"
        )
        return {
            "analysis_script_plan": _fallback_plan(dataset_summary, input_basenames, reason),
            "issues": [reason],
        }

    if plan is None:
        # with_structured_output can return None instead of raising when the
        # model's response has no usable tool/function call.
        reason = (
            "statistical_analyser LLM call returned no structured AnalysisScriptPlan "
            "(the model likely did not invoke the expected function call), using "
            "sandbox connectivity check script."
        )
        return {
            "analysis_script_plan": _fallback_plan(dataset_summary, input_basenames, reason),
            "issues": [reason],
        }

    return {"analysis_script_plan": plan, "issues": list(plan.open_questions)}


statistical_analyser_node = statistical_analyser_node
