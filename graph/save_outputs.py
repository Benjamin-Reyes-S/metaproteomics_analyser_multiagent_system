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
