"""Run the first-stage metaproteomics study-planning graph."""

import argparse
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents.study_planer import MODEL_NAME, study_planner_node
from graph.state import MetaproteomicsAnalysisState


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIRECTORY = REPOSITORY_ROOT / "data"
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"


def build_graph():
    """Build the currently enabled study-planning portion of the workflow."""
    builder = StateGraph(MetaproteomicsAnalysisState)
    builder.add_node("study_design", study_planner_node)
    builder.add_edge(START, "study_design")
    builder.add_edge("study_design", END)
    return builder.compile()


def write_study_plan(result: dict, output_path: Path) -> None:
    """Write a human-readable planner result to the workspace."""
    study_plan = result.get("study_plan")
    if not study_plan:
        issues = "\n".join(f"- {issue}" for issue in result.get("issues", []))
        raise RuntimeError(f"The planner did not return a study plan.\n{issues}")

    sections = ["METAPROTEOMICS STUDY PLAN", "", study_plan.strip()]
    if result.get("issues"):
        sections.extend(
            ["", "ISSUES AND MISSING INFORMATION", ""]
            + [f"- {issue}" for issue in result["issues"]]
        )
    output_path.write_text("\n".join(sections) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--data-directory",
        type=Path,
        default=DEFAULT_DATA_DIRECTORY,
        help="Directory containing study CSV/TSV files (default: data/)",
    )
    input_group.add_argument(
        "--dataset",
        type=Path,
        action="append",
        help="Specific input file; repeat this option to provide multiple files",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="Directory where study_plan.txt is written",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.expanduser().resolve()
    if args.dataset:
        datasets = [path.expanduser().resolve() for path in args.dataset]
    else:
        data_directory = args.data_directory.expanduser().resolve()
        if not data_directory.is_dir():
            raise FileNotFoundError(f"Data directory not found: {data_directory}")
        datasets = sorted(
            path.resolve()
            for path in data_directory.iterdir()
            if path.is_file() and path.suffix.casefold() in {".csv", ".tsv"}
        )
    if not datasets:
        raise FileNotFoundError("No CSV/TSV input files were found")
    missing = [path for path in datasets if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Dataset not found: {missing[0]}")

    workspace.mkdir(parents=True, exist_ok=True)
    output_path = workspace / "study_plan.txt"
    result = build_graph().invoke(
        {"data_raw_paths": [str(path) for path in datasets], "issues": []}
    )
    write_study_plan(result, output_path)
    print(f"Model: {MODEL_NAME}")
    print(f"Datasets inspected: {len(datasets)}")
    for dataset in datasets:
        print(f"  - {dataset}")
    print(f"Study plan written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
