# Pipeline backbone

This describes the current LangGraph backbone: how data moves through
`MetaproteomicsAnalysisState`, which files land in `workspace/` and
`results/`, and which nodes are real vs. placeholder.

Every agent node in `agents/` (`study_planer`,
`statistical_analyser`, `outcome_auditor`) is currently a **deterministic
placeholder with no LLM call**. Only the wiring, state contract, file
artifacts, and sandbox execution are implemented for real. Each stub's
docstring says exactly what to replace and what contract to preserve.
`agents/inspect_data` already calls LLM.

## Graph

```
input/*.csv
     |
     v
inspect_data            (agents/inspect_data.py — agent)
     |
     | dataset_summary
     v
study_planer             (agents/study_planer.py — placeholder)
     |
     | study_plan
     v
write_plan               (graph/graph.py — real, writes workspace/plan.txt)
     |
     v
statistical_analyser      (agents/statistical_analyser.py — placeholder)
     |
     | code_text
     v
run_code                 (graph/graph.py + sandbox/run_code.py — real)
     |                    writes workspace/code.py, runs it in Docker
     | stdout / stderr / exit_code / output_files
     v
outcome_auditor           (agents/outcome_auditor.py — placeholder)
     |
     +-- PASS --> store_results (graph/graph.py — real) --> END
     |
     +-- FAIL --> statistical_analyser (up to MAX_RETRIES=3, then END)
```

Defined in [graph/graph.py](graph/graph.py); run via [main.py](main.py).

## State contract (`graph/state.py`)

| Field | Set by | Read by | Notes |
|---|---|---|---|
| `data_raw_paths` | caller (`main.py`) | `inspect_data`, `statistical_analyser` | host paths to input CSV/TSV files |
| `dataset_summary` | `inspect_data` | `study_planer` | `{path: description}` |
| `study_plan` | `study_planer` | `statistical_analyser` (contract only, unused by placeholder) | written to `workspace/plan.txt` by the `write_plan` node, immediately after `study_planer` and before `store_results` can run |
| `code_text` | `statistical_analyser` | `run_code` node | in-memory only; never touches disk until `run_code` writes it |
| `code_path` | `run_code` node | `store_results` | set to `workspace/code.py` |
| `execution_status` | `run_code` node | — | `"completed"` or `"failed"`, derived from `execution_exit_code` |
| `execution_stdout` / `execution_stderr` / `execution_exit_code` | `run_code` node | `outcome_auditor` | raw sandbox process output |
| `output_files` | `run_code` node | `outcome_auditor`, `store_results` | every file left in `workspace/` other than `code.py` |
| `evaluation` | `outcome_auditor` | routing (`route_after_audit`) | `"PASS"` / `"FAIL"` |
| `evaluator_feedback` | `outcome_auditor` | `statistical_analyser` (contract only, unused by placeholder) | free text, meant to drive regeneration on retry |
| `issues` | `inspect_data`, `study_planer` | `write_plan` (written into plan.txt), `main.py` (printed) | accumulates (`Annotated[..., add]`) |
| `retry_count` | `outcome_auditor` | routing | incremented on each `FAIL`, capped at `MAX_RETRIES` in `graph/graph.py` |

`code_text`/`code_path` are produced by `statistical_analyser`/`run_code`

## Isolation of LLM-generated code

`statistical_analyser` only ever returns `code_text` (a string in
memory). The **only** place that string is written to disk and executed
is `run_code_node` in `graph/graph.py`, which writes it verbatim to
`workspace/code.py` and then calls `sandbox.run_code.run_code()`. That
function assembles the Docker command itself — no agent or LLM output
ever contributes to the command line, only to the contents of the file
that command runs.

## Sandbox execution (`sandbox/run_code.py`)

`run_code(workspace_dir, input_dir)` runs, deterministically:

```
docker run --rm --network none \
    -v <input_dir>:/input:ro \
    -v <workspace_dir>:/workspace \
    -w /workspace \
    metaproteomics-sandbox:latest \
    python /workspace/code.py
```

and returns `{"stdout", "stderr", "exit_code", "output_files"}`.

Build the image once before running the pipeline:

```bash
docker build -t metaproteomics-sandbox:latest ./sandbox
# or: docker compose build analysis-sandbox
```

The sandbox image (`sandbox/Dockerfile`) only installs
`sandbox/requirements.txt` (pandas, numpy, scipy, matplotlib) — no
LangGraph or agent dependencies. It exists to run generated analysis
code, not the multi-agent system.

## Files

```
workspace/                 current run's artifacts (overwritten every run)
├── plan.txt                written by write_plan_node from state["study_plan"]
├── code.py                 written by run_code_node from state["code_text"]
├── results.csv              \
└── plot_1.png, ...          / whatever the generated code writes

results/                   accepted artifacts, populated only on PASS
├── plan.txt
├── code.py
├── results.csv
└── plot_1.png, ...
```

`store_results_node` copies `plan.txt`, `code.py`, and every entry in
`output_files` from `workspace/` into `results/`. On FAIL after
`MAX_RETRIES` retries, the graph ends without touching `results/`;
inspect `workspace/` (`execution_stderr`, `evaluator_feedback` in the
returned state) to see why.

## Running it

```bash
docker build -t metaproteomics-sandbox:latest ./sandbox
python main.py                      # uses every CSV/TSV in input/
python main.py --dataset input/SupplementaryFile1.csv
```

Requires `langgraph` and `pandas` on the host (see `requirements.txt`)
and a working `docker` CLI on `PATH`.


### notes
Two corrections to your mental model:

1. statistical_analyser doesn't read plan.txt — and even in the real version, it shouldn't read the file. Right now (line 26 above) it doesn't touch study_plan at all — as a placeholder it only reads state["data_raw_paths"] and ignores the plan entirely. When it is implemented for real, it should read state["study_plan"] — the string still sitting in the in-memory state dict — not re-open workspace/plan.txt from disk.LangGraph already carries it forward in memory as part of the state object flowing node-to-node. The file on disk is a side effect for a human to read (and later for store_results to archive into results/) — it's not the inter-node data channel.

2. So the general rule in this backbone: state (in-memory dict) is how nodes talk to each other; files are written by the deterministic nodes only where an artifact needs to persist because a human wants to read it, or because something outside this Python process needs it (the sandbox container can only see /workspace, it can't see the orchestrator's Python variables, so code.py genuinely must be a file). plan.txt doesn't have that second requirement — nothing outside the process reads it during the run — so writing it is purely for persistence/audit, not data transfer.

Corrected version of your summary:

inspect_data returns dataset_summary: dict[str, str] — into state, in-memory.
study_planner_node reasons over state["dataset_summary"] (in-memory, not a file) → returns 






: str — into state.
write_plan_node (deterministic) persists state["study_plan"] to workspace/plan.txt — for humans/results/, not for the next node.
statistical_analyser_node should read state["study_plan"] (in-memory) to generate code_text: str — into state. (Currently it doesn't — placeholder gap.)
make_run_code_node's node (deterministic) is the one place a file is genuinely required as the handoff: it writes state["code_text"] to workspace/code.py because the sandbox container can only see the filesystem, then executes it and reads back stdout/stderr/exit_code/output_files into state.