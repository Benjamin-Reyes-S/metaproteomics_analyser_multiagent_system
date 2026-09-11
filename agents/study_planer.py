"""Study-planning node.

Makes a single LLM call over `state["dataset_summary"]` (a
`schemas.schema_inspect_data.DatasetSummary`) to produce a structured
`schemas.schema_study_planer.StudyPlan`: which of the four canonical
study-design cases applies, and concrete QC / filtering / normalization /
batch / differential-abundance / visualization choices for it. The
`StudyPlan` object itself is returned as `study_plan` (state's
`study_plan` field is typed `StudyPlan`, not a string); `render_study_plan`
below is exported for `write_plan_node` (`graph/graph.py`) to turn it into
the human-readable `plan.txt`.

If no DENBI_TOKEN is configured, or the LLM call fails, this node falls
back to a minimal `StudyPlan` built directly from `dataset_summary`'s
already-known fields, with the failure recorded in `issues` and in the
plan's own `open_questions` so it's visible in plan.txt.
"""

import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from graph.state import MetaproteomicsAnalysisState
from schemas.schema_inspect_data import DatasetSummary
from schemas.schema_study_planer import (
    BatchPlan,
    DifferentialAbundancePlan,
    FilteringPlan,
    NormalizationPlan,
    QCPlan,
    StudyPlan,
    VisualizationPlan,
)

DEFAULT_MODEL_NAME = "vllm/Qwen/Qwen3.6-35B-A3B"
DEFAULT_API_BASE_URL = "https://llm.bi.denbi.de/v1"

SYSTEM_PROMPT = """
You are a metaproteomics study-planning agent. You receive a DatasetSummary
(already produced by an upstream inspection agent) and must produce a
StudyPlan: concrete, justified method choices for the downstream analysis.
Do not perform the analysis yourself, and do not invent facts about the
study beyond what DatasetSummary states — if something is unknown, say so
in open_questions rather than guessing.

Base study_design_case on DatasetSummary.study_design_case and reason about
its implications:
- unique_sample_no_control: no differential abundance is possible; the plan
  should focus on descriptive taxonomic/functional composition, diversity,
  and coverage completeness. QC and database choice matter more since there
  is no comparator.
- condition_comparison: requires a differential-abundance model; the number
  of groups determines t-test/ANOVA vs. more general linear models; whether
  the same subject was sampled under both conditions determines paired vs.
  unpaired; group sizes must be balanced or the imbalance justified.
- longitudinal: needs repeated-measures / mixed-effects models with subject
  as a random effect; consider temporal autocorrelation; prefer trajectory
  visualizations over static group comparisons.
- complex_multifactorial: needs factorial or nested mixed models with
  interaction terms (time x condition, time x site); highest confounding
  risk, so batch/covariate handling must be explicit; often needs
  taxon-stratified functional analysis to interpret interactions.
If study_design_case is "unknown", keep differential_abundance_plan.applicable
false and explain what's missing in open_questions.

Apply these cross-cutting rules regardless of case:
- Replicate structure: biological replicates drive power; flag technical
  replicates if their CV exceeds 0.2 within a condition/batch. Pooled
  samples are acceptable when only small effect sizes are expected.
- Batch effects: evaluate association with PCA axes, missingness, total
  intensity, and ID depth before deciding to correct. Never propose
  correcting a batch that is fully confounded with the biological
  condition. Prefer modeling batch as a covariate over irreversibly
  transforming the matrix.
- Normalization must match measurement scale: continuous protein/peptide
  intensities (log2, median, quantile, VSN, internal-reference, etc.) are
  not interchangeable with compositional taxonomic/functional tables (CLR,
  Aitchison distance, compositional DA methods). Never apply microbiome
  count methods to continuous LFQ intensities.
- Missing data can be abundance-dependent (not-at-random); state an explicit
  missing-value policy rather than defaulting to blind minimum-value
  imputation.
- Prevalence filtering should be evaluated within experimental groups, not
  across the whole dataset, and host/microbial matrices should be filtered
  separately at least initially.
- Track whether annotation is peptide-centric or protein-centric
  (DatasetSummary.annotation_philosophy) and note its impact on
  taxonomic/functional read-outs in annotation_philosophy_impact.

Ground every field in DatasetSummary: use its matrices to decide which
levels (protein/peptide intensity, taxonomic, functional) need QC/
filtering/normalization plans, its study_summary for cohort/sample/
batch scale, its batch_info/condition_info/longitudinal_info/
replicate_structure/missingness_policy to decide batch_plan/
differential_abundance_plan, and its known_confounders and
open_questions to seed your own open_questions.

Treat dataset_summary.data_linkage as the authoritative join map — it
is what statistical_analyser will use to know exactly which file/column
holds abundance vs. taxonomic vs. functional information and how to
join them. Do not re-derive or contradict those joins yourself. If a
level of information your plan depends on (e.g. a taxonomic or
functional readout in visualization_plan) has no corresponding
data_linkage entry, say so explicitly in open_questions rather than
assuming a join exists.

Put every remaining blocker or ambiguity the study_planer could not
resolve into open_questions.

filtering_plan.min_unique_peptides, filtering_plan.prevalence_cutoff_pct,
and batch_plan.confounded_with_biology are plain number/true-false fields,
not one of the enumerated "unknown"-option string fields elsewhere in this
schema: if you don't know the value, set it to null, never the string
"unknown".
""".strip()


def _planner_model():
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
    ).with_structured_output(StudyPlan, method="json_schema")


def render_study_plan(plan: StudyPlan) -> str:
    lines = [
        f"Study design case: {plan.study_design_case}",
        "",
        plan.summary,
        "",
        "QC PLAN",
        f"- host/microbial matrices separated: {plan.qc_plan.host_microbial_separated}",
    ]
    lines += [f"- check: {check}" for check in plan.qc_plan.checks]
    lines += [f"- flag: {flag}" for flag in plan.qc_plan.flags_to_investigate]

    fp = plan.filtering_plan
    lines += [
        "",
        "FILTERING PLAN",
        f"- remove contaminants/decoys: {fp.remove_contaminants_and_decoys}",
        f"- minimum unique peptides: {fp.min_unique_peptides}",
        f"- prevalence cutoff: {fp.prevalence_cutoff_pct}% ({fp.prevalence_grouping})",
        f"- filter host/microbial separately: {fp.filter_host_and_microbial_separately}",
        f"- rationale: {fp.rationale}",
    ]

    np_ = plan.normalization_plan
    lines += [
        "",
        "NORMALIZATION PLAN",
        f"- intensity method: {np_.intensity_method}",
        f"- compositional method: {np_.compositional_method}",
        f"- rationale: {np_.rationale}",
    ]

    bp = plan.batch_plan
    lines += [
        "",
        "BATCH ASSESSMENT AND CORRECTION",
        f"- confounded with biology: {bp.confounded_with_biology}",
        f"- correction method: {bp.correction_method}",
        f"- rationale: {bp.rationale}",
    ]
    lines += [f"- validation: {check}" for check in bp.validation_checks]

    dap = plan.differential_abundance_plan
    lines += [
        "",
        "DIFFERENTIAL ABUNDANCE PLAN",
        f"- applicable: {dap.applicable}",
        f"- model type: {dap.model_type}",
        f"- model formula: {dap.model_formula}",
        f"- paired: {dap.paired}",
        f"- missing-value policy: {dap.missing_value_policy}",
        f"- rationale: {dap.rationale}",
    ]
    lines += [f"- must report: {item}" for item in dap.reporting_requirements]

    vp = plan.visualization_plan
    lines += ["", "VISUALIZATION PLAN"]
    lines += [f"- protein level: {item}" for item in vp.protein_level]
    lines += [f"- taxonomic level: {item}" for item in vp.taxonomic_level]
    lines += [f"- functional level: {item}" for item in vp.functional_level]

    if plan.annotation_philosophy_impact:
        lines += ["", "ANNOTATION PHILOSOPHY IMPACT", plan.annotation_philosophy_impact]

    return "\n".join(lines)

#if the dataset_summary not available
def _fallback_plan(dataset_summary, reason: str) -> StudyPlan:
    return StudyPlan(
        study_design_case=dataset_summary.study_design_case,
        summary=f"Fallback plan: {reason}",
        qc_plan=QCPlan(host_microbial_separated=True),
        filtering_plan=FilteringPlan(rationale="Not determined: LLM call unavailable."),
        normalization_plan=NormalizationPlan(rationale="Not determined: LLM call unavailable."),
        batch_plan=BatchPlan(rationale="Not determined: LLM call unavailable."),
        differential_abundance_plan=DifferentialAbundancePlan(
            applicable=False,
            missing_value_policy="Not determined: LLM call unavailable.",
            rationale="Not determined: LLM call unavailable.",
        ),
        visualization_plan=VisualizationPlan(),
        open_questions=[reason],
    )


def study_planner_node(state: MetaproteomicsAnalysisState) -> dict:
    dataset_summary = state.get("dataset_summary")

    if dataset_summary is None:
        reason = "study_planer: no dataset_summary available from inspect_data"
        return {
            "study_plan": _fallback_plan(
                DatasetSummary(study_design_case="unknown", open_questions=[reason]), reason
            ),
            "issues": [reason],
        }

    message = (
        "Produce a StudyPlan for this DatasetSummary:\n\n"
        + dataset_summary.model_dump_json(indent=2)
    )

    try:
        plan = _planner_model().invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]
        )
    except Exception as exc:
        reason = f"study_planer LLM call failed, using minimal fallback: {type(exc).__name__}: {exc}"
        return {
            "study_plan": _fallback_plan(dataset_summary, reason),
            "issues": [reason],
        }

    if plan is None:
        # with_structured_output can return None instead of raising when the
        # model's response has no usable tool/function call.
        reason = (
            "study_planer LLM call returned no structured StudyPlan (the model "
            "likely did not invoke the expected function call), using minimal fallback."
        )
        return {
            "study_plan": _fallback_plan(dataset_summary, reason),
            "issues": [reason],
        }

    return {"study_plan": plan, "issues": list(plan.open_questions)}


study_planer_node = study_planner_node
