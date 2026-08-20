"""Deterministic nodes that persist agent outputs into workspace/ for inspection.

Wired into the current 2-agent test graph (graph/graph.py): dataset_summary
(from inspect_data) is written as JSON, and study_plan (from study_planer) as
the already-rendered plan text (render_study_plan, from agents/study_planer.py).
Both write unconditionally, even when the corresponding agent fell back
(None/minimal output), so a failed run is just as inspectable as a successful
one.
"""

from pathlib import Path

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
