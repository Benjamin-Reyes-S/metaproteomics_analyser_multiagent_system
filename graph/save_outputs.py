"""Deterministic nodes that persist agent outputs into workspace/ for inspection.

Wired into the current 2-agent test graph (graph/graph.py): dataset_summary
(from inspect_data) is written as JSON, and study_plan (from study_planer) as
the already-rendered plan text (render_study_plan, from agents/study_planer.py).
Both write unconditionally, even when the corresponding agent fell back
(None/minimal output), so a failed run is just as inspectable as a successful
one.

make_save_analysis_script_node (below) follows the same pattern for
analysis_script_plan (from agents/statistical_analyser.py): the full
structured plan as JSON, for review, plus the flattened script
(render_analysis_script) as workspace/code.py. workspace_dir here is
exactly what sandbox.run_code.run_code() bind-mounts as /workspace, so
code.py lands where run_code's fixed sandbox command
(`python /workspace/code.py`) expects it, alongside the /input:ro-mounted
raw data the script itself is expected to read from.
"""

import shutil
from pathlib import Path

from agents.statistical_analyser import render_analysis_script
from agents.study_planer import render_study_plan
from graph.state import MetaproteomicsAnalysisState


def make_save_dataset_summary_node(workspace_dir: Path):
    """Write state["dataset_summary"] to workspace/dataset_summary.json."""

    def save_dataset_summary_node(state: MetaproteomicsAnalysisState) -> dict:
        dataset_summary = state.get("dataset_summary")
        text = dataset_summary.model_dump_json(indent=2) if dataset_summary is not None else "null"
        (workspace_dir / "dataset_summary.json").write_text(text + "\n", encoding="utf-8")
        return {}

    return save_dataset_summary_node


def make_save_study_plan_node(workspace_dir: Path):
    """Write state["study_plan"] to workspace/study_plan.txt."""

    def save_study_plan_node(state: MetaproteomicsAnalysisState) -> dict:
        study_plan = state.get("study_plan")
        text = render_study_plan(study_plan) if study_plan is not None else "No study plan produced."
        (workspace_dir / "study_plan.txt").write_text(text.strip() + "\n", encoding="utf-8")
        return {}

    return save_study_plan_node


def make_save_analysis_script_node(workspace_dir: Path):
    """Write state["analysis_script_plan"] to workspace/analysis_script_plan.json
    (full structured plan, for review) and workspace/code.py (the flattened,
    runnable script). Also returns code_text so it lands in state for
    run_code_node's existing state["code_text"] contract (graph/graph.py),
    without that node needing to re-derive it."""

    def save_analysis_script_node(state: MetaproteomicsAnalysisState) -> dict:
        plan = state.get("analysis_script_plan")
        json_text = plan.model_dump_json(indent=2) if plan is not None else "null"
        (workspace_dir / "analysis_script_plan.json").write_text(json_text + "\n", encoding="utf-8")

        code_text = render_analysis_script(plan) if plan is not None else "# No analysis script was produced.\n"
        (workspace_dir / "code.py").write_text(code_text.strip() + "\n", encoding="utf-8")
        return {"code_text": code_text}

    return save_analysis_script_node


# Files the pipeline itself writes into workspace/ (not produced by code.py),
# so save_code_output leaves them where they are.
PIPELINE_FILES = {
    "code.py",
    "plan.txt",
    "dataset_summary.json",
    "study_plan.txt",
    "analysis_script_plan.json",
}
PLOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".tif", ".tiff", ".eps"}
EXECUTION_LOG_NAME = "execution_log.txt"


def save_code_output(subworkspace_dir: Path):
    """Collect what code.py produced in the sandbox into workspace/output/.

    subworkspace_dir is workspace/output. On every run it is emptied and
    recreated, together with subworkspace_dir/plots/, so it only holds the
    current run's results. Then:
      - every file code.py left in workspace/ (state["output_files"], minus
        PIPELINE_FILES) is moved there; images (PLOT_SUFFIXES) go into plots/;
      - run_code's stdout, stderr and exit code are written to
        execution_log.txt, so a failed or timed-out run is visible on disk.
    Returns the new locations as output_files.
    """

    def save_code_output_node(state: MetaproteomicsAnalysisState) -> dict:
        plots_dir = subworkspace_dir / "plots"
        if subworkspace_dir.exists():
            shutil.rmtree(subworkspace_dir)
        plots_dir.mkdir(parents=True)

        moved_files = []
        for output_file in state.get("output_files") or []:
            source = Path(output_file)
            if not source.is_file() or source.name in PIPELINE_FILES:
                continue
            target_dir = plots_dir if source.suffix.casefold() in PLOT_SUFFIXES else subworkspace_dir
            target = target_dir / source.name
            shutil.move(str(source), str(target))
            moved_files.append(str(target))

        log_text = (
            f"execution_status: {state.get('execution_status')}\n"
            f"exit_code: {state.get('execution_exit_code')}\n"
            f"\n===== stdout =====\n{state.get('execution_stdout') or ''}\n"
            f"\n===== stderr =====\n{state.get('execution_stderr') or ''}\n"
        )
        (subworkspace_dir / EXECUTION_LOG_NAME).write_text(log_text, encoding="utf-8")

        return {"output_files": sorted(moved_files)}

    return save_code_output_node
