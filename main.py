"""Run the full metaproteomics multi-agent pipeline end to end.

input/*.csv -> inspect_data -> study_planer -> statistical_analyser -> run_code
(Docker sandbox) -> outcome_auditor -> PASS: results/ | FAIL: retry statistical_analyser

See PIPELINE.md for the state contract and file layout this produces.
"""

import argparse
import os
from pathlib import Path

from graph.graph import build_graph

REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_DIRECTORY = REPOSITORY_ROOT / "input"
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"
DEFAULT_RESULTS = REPOSITORY_ROOT / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--input-directory",
        type=Path,
        default=DEFAULT_INPUT_DIRECTORY,
        help="Directory containing study CSV/TSV files, mounted read-only into the sandbox as /input (default: input/)",
    )
    input_group.add_argument(
        "--dataset",
        type=Path,
        action="append",
        help="Specific input file within one directory; repeat to provide multiple files",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="Directory for the current run's artifacts (plan.txt, code.py, outputs)",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help="Directory accepted artifacts are copied to after a PASS audit",
    )
    parser.add_argument(
        "--denbi-api-base",
        type=str,
        default=None,
        help="Override the DENBI_API_BASE env var (LLM endpoint used by inspect_data)",
    )
    parser.add_argument(
        "--denbi-token",
        type=str,
        default=None,
        help="Override the DENBI_TOKEN env var (LLM API credential). "
        "Prefer setting the env var directly so the token doesn't end up in shell history.",
    )
    parser.add_argument(
        "--denbi-model",
        type=str,
        default=None,
        help="Override the DENBI_MODEL env var used by inspect_data",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.expanduser().resolve()
    results = args.results.expanduser().resolve()

    if args.denbi_api_base:
        os.environ["DENBI_API_BASE"] = args.denbi_api_base
    if args.denbi_token:
        os.environ["DENBI_TOKEN"] = args.denbi_token
    if args.denbi_model:
        os.environ["DENBI_MODEL"] = args.denbi_model

    if args.dataset:
        datasets = [path.expanduser().resolve() for path in args.dataset]
        input_directories = {path.parent for path in datasets}
        if len(input_directories) > 1:
            raise ValueError(
                "All --dataset files must live in the same directory; that directory is mounted as /input in the sandbox."
            )
        input_directory = next(iter(input_directories))
    else:
        input_directory = args.input_directory.expanduser().resolve()
        if not input_directory.is_dir():
            raise FileNotFoundError(f"Input directory not found: {input_directory}")
        datasets = sorted(
            path.resolve()
            for path in input_directory.iterdir()
            if path.is_file() and path.suffix.casefold() in {".csv", ".tsv"}
        )
    if not datasets:
        raise FileNotFoundError("No CSV/TSV input files were found")

    workspace.mkdir(parents=True, exist_ok=True)

    graph = build_graph(workspace_dir=workspace, input_dir=input_directory, results_dir=results)
    final_state = graph.invoke(
        {"data_raw_paths": [str(path) for path in datasets], "issues": [], "retry_count": 0}
    )

    print(f"Datasets inspected: {len(datasets)}")
    for dataset in datasets:
        print(f"  - {dataset}")
    # TEMP (2-agent test run): the graph currently stops right after
    # study_planer (see graph/graph.py), so evaluation/execution state below
    # is never produced. Commented out, not deleted, for when the full
    # pipeline is wired back in.
    # print(f"Evaluation: {final_state.get('evaluation')}")
    # print(f"Execution exit code: {final_state.get('execution_exit_code')}")
    # if final_state.get("evaluation") == "PASS":
    #     print(f"Results stored in: {results}")
    # else:
    #     print(
    #         f"Pipeline did not pass audit after {final_state.get('retry_count', 0)} retry(ies). "
    #         f"See {workspace} for details."
    #     )
    # TEMP (2-agent test run): report the two agents' actual outputs instead.
    print(f"Dataset summary: {final_state.get('dataset_summary')}")
    print(f"Study plan: {final_state.get('study_plan')}")
    print(f"Issues: {final_state.get('issues')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
