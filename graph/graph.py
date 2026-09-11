"""LangGraph backbone wiring the metaproteomics pipeline together.

    inspect_data -> study_planer -> write_plan -> statistical_analyser -> run_code -> outcome_auditor
                                                        ^                                       |
                                                        |______________ FAIL (retry) ___________|
                                                                                                 |
                                                                                             PASS |
                                                                                                 v
                                                                                          store_results -> END

See PIPELINE.md for the full state contract and file layout. The nodes
imported from agents/ are deterministic placeholders for now (see their
docstrings); run_code_node and store_results_node below are the
deterministic, non-agent parts of the backbone and are implemented for
real.
"""

import shutil
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents.inspect_data import inspect_data_node
#from agents.outcome_auditor import outcome_auditor_node
from agents.statistical_analyser import statistical_analyser_node
from agents.study_planer import render_study_plan, study_planner_node
from graph.save_outputs import (
    make_save_analysis_script_node,
    make_save_dataset_summary_node,
    make_save_study_plan_node,
)
from graph.state import MetaproteomicsAnalysisState
from sandbox.run_code import run_code

MAX_RETRIES = 3


def make_write_plan_node(workspace_dir: Path):
    """Write study_plan to workspace/plan.txt right after study_planer runs.

    Must happen here, inside the graph, and not after graph.invoke()
    returns: store_results_node (below) copies workspace/plan.txt into
    results/ on PASS, which happens during this same invoke() call.
    """

    def write_plan_node(state: MetaproteomicsAnalysisState) -> dict:
        study_plan = state.get("study_plan")
        issues = state.get("issues") or []
        plan_text = render_study_plan(study_plan) if study_plan is not None else "No study plan produced."
        sections = ["METAPROTEOMICS STUDY PLAN", "", plan_text.strip()]
        if issues:
            sections.extend(
                ["", "ISSUES AND MISSING INFORMATION", ""] + [f"- {issue}" for issue in issues]
            )
        (workspace_dir / "plan.txt").write_text("\n".join(sections) + "\n", encoding="utf-8")
        return {}

    return write_plan_node


def make_run_code_node(workspace_dir: Path, input_dir: Path):
    """Write code_text to workspace/code.py, then execute it in the sandbox.

    This is the isolation boundary between LLM-generated text
    (state["code_text"]) and code that actually runs: nothing except the
    deterministic write below decides what ends up on disk and gets
    executed.
    """

    def run_code_node(state: MetaproteomicsAnalysisState) -> dict:
        code_path = workspace_dir / "code.py"
        code_path.write_text(state["code_text"], encoding="utf-8")

        result = run_code(workspace_dir, input_dir)
        return {
            "code_path": str(code_path),
            "execution_stdout": result["stdout"],
            "execution_stderr": result["stderr"],
            "execution_exit_code": result["exit_code"],
            "output_files": result["output_files"],
            "execution_status": "completed" if result["exit_code"] == 0 else "failed",
        }

    return run_code_node


def make_store_results_node(workspace_dir: Path, results_dir: Path):
    """Copy accepted artifacts from workspace/ into results/ on PASS."""

    def store_results_node(state: MetaproteomicsAnalysisState) -> dict:
        results_dir.mkdir(parents=True, exist_ok=True)
        for name in ("plan.txt", "code.py"):
            source = workspace_dir / name
            if source.is_file():
                shutil.copy2(source, results_dir / name)
        for output_file in state.get("output_files") or []:
            source = Path(output_file)
            if source.is_file():
                shutil.copy2(source, results_dir / source.name)
        return {}

    return store_results_node


def route_after_audit(state: MetaproteomicsAnalysisState) -> str:
    if state.get("evaluation") == "PASS":
        return "store_results"
    if state.get("retry_count", 0) < MAX_RETRIES:
        return "statistical_analyser"
    return END


def build_graph(workspace_dir: Path, input_dir: Path, results_dir: Path):
    """Build the full pipeline graph, bound to concrete directories."""
    builder = StateGraph(MetaproteomicsAnalysisState)
    builder.add_node("inspect_data", inspect_data_node)
    builder.add_node("save_dataset_summary", make_save_dataset_summary_node(workspace_dir))
    builder.add_node("study_planer", study_planner_node)
    builder.add_node("save_study_plan", make_save_study_plan_node(workspace_dir))
    builder.add_node("statistical_analyser", statistical_analyser_node)
    builder.add_node("save_analysis_script", make_save_analysis_script_node(workspace_dir))
    builder.add_node("run_code", make_run_code_node(workspace_dir, input_dir))
    # TEMP (4-agent test run): outcome_auditor is still a deterministic
    # placeholder (see its docstring) and store_results/the retry loop only
    # make sense once it's real, so they stay commented out, not deleted.
    # builder.add_node("write_plan", make_write_plan_node(workspace_dir))
    # builder.add_node("outcome_auditor", outcome_auditor_node)
    # builder.add_node("store_results", make_store_results_node(workspace_dir, results_dir))

    builder.add_edge(START, "inspect_data")
    builder.add_edge("inspect_data", "save_dataset_summary")
    builder.add_edge("save_dataset_summary", "study_planer")
    builder.add_edge("study_planer", "save_study_plan")
    builder.add_edge("save_study_plan", "statistical_analyser")
    builder.add_edge("statistical_analyser", "save_analysis_script")
    builder.add_edge("save_analysis_script", "run_code")
    # TEMP (4-agent test run): downstream edges commented out, not deleted.
    # builder.add_edge("study_planer", "write_plan")
    # builder.add_edge("write_plan", "statistical_analyser")
    # builder.add_edge("run_code", "outcome_auditor")
    # builder.add_conditional_edges(
    #     "outcome_auditor",
    #     route_after_audit,
    #     {"statistical_analyser": "statistical_analyser", "store_results": "store_results", END: END},
    # )
    # builder.add_edge("store_results", END)
    # TEMP (4-agent test run): new edge short-circuiting straight to END right
    # after run_code, since outcome_auditor/store_results stay commented out above.
    builder.add_edge("run_code", END)
    return builder.compile()
