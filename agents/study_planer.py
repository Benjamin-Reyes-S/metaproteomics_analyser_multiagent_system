"""Study-planning node.

Deterministic placeholder: no LLM call yet. It only threads
`dataset_summary` into a `study_plan` string so the graph's input/output
contract (and the downstream plan.txt artifact) can be exercised end to
end. Replace the body with a real planning agent later; keep the
contract (`dataset_summary` in, `study_plan` + `issues` out) the same.
"""

from graph.state import MetaproteomicsAnalysisState


def study_planner_node(state: MetaproteomicsAnalysisState) -> dict:
    dataset_summary = state.get("dataset_summary") or {}

    if not dataset_summary:
        return {
            "study_plan": "No study plan produced: dataset_summary is empty.",
            "issues": ["study_planer: no dataset_summary available from inspect_data"],
        }

    lines = ["STUDY PLAN PLACEHOLDER (no LLM call yet)", ""]
    for path, description in dataset_summary.items():
        lines.append(f"- {path}: {description}")
    return {"study_plan": "\n".join(lines), "issues": []}


study_planer_node = study_planner_node
