"""Outcome-auditing node.

Deterministic placeholder: no LLM call yet. It applies a simple
PASS/FAIL rule based on the sandbox exit code so the retry loop and the
result-storage path in graph/graph.py can be exercised end to end.
Replace the body with a real auditing agent later; keep the contract
(`execution_exit_code`/`execution_stdout`/`execution_stderr` in,
`evaluation`/`evaluator_feedback` out) the same.
"""

from graph.state import MetaproteomicsAnalysisState


def outcome_auditor_node(state: MetaproteomicsAnalysisState) -> dict:
    exit_code = state.get("execution_exit_code")

    if exit_code == 0:
        return {
            "evaluation": "PASS",
            "evaluator_feedback": "run_code exited with status 0.",
        }

    feedback = (
        f"run_code exited with status {exit_code}.\n"
        f"stderr:\n{state.get('execution_stderr') or '(empty)'}"
    )
    return {
        "evaluation": "FAIL",
        "evaluator_feedback": feedback,
        "retry_count": state.get("retry_count", 0) + 1,
    }
