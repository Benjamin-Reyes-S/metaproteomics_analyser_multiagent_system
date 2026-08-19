




# Pipeline backbone

LangGraph pipeline wiring agents (LLM calls) and deterministic nodes
together. Run via [main.py](main.py); full node/state code lives in
[graph/graph.py](graph/graph.py) and [graph/state.py](graph/state.py).

## Graph

```
input/*.csv
     |
     v
inspect_data          (agents/inspect_data.py — agent, LLM call)
     |
     | dataset_summary: DatasetSummary
     v
study_planer          (agents/study_planer.py — agent, LLM call)
     |
     | study_plan: StudyPlan
     v
write_plan            (graph/graph.py — deterministic, writes workspace/plan.txt)
     |
     v
statistical_analyser  (agents/statistical_analyser.py — placeholder, no LLM call yet)
     |
     | code_text: str
     v
run_code              (graph/graph.py + sandbox/run_code.py — deterministic, Docker sandbox)
     |
     | stdout / stderr / exit_code / output_files
     v
outcome_auditor       (agents/outcome_auditor.py — placeholder, no LLM call yet)
     |
     +-- PASS --> store_results (deterministic) --> END
     |
     +-- FAIL --> statistical_analyser (retry, up to MAX_RETRIES=3, then END)
```

## Who talks to whom, and how

Nodes communicate through the in-memory LangGraph state
(`MetaproteomicsAnalysisState`), not files. Files are written only where a
human needs to read the result, or where a process outside Python (the
sandbox container) needs the data.

```
 agent / node            state it reads              state it writes
 ───────────────────     ─────────────────────       ─────────────────────
 inspect_data       -->  data_raw_paths          -->  dataset_summary, issues
 study_planer       -->  dataset_summary         -->  study_plan, issues
 write_plan         -->  study_plan, issues      -->  workspace/plan.txt   (file, audit only)
 statistical_analyser --> data_raw_paths         -->  code_text
 run_code           -->  code_text               -->  workspace/code.py    (file, sandbox needs it)
                                                  -->  execution_*, output_files
 outcome_auditor    -->  execution_*             -->  evaluation, evaluator_feedback
 store_results      -->  output_files            -->  results/*            (file, on PASS only)
```

`dataset_summary` (`schemas/schema_inspect_data.py: DatasetSummary`) and
`study_plan` (`schemas/schema_study_planer.py: StudyPlan`) are typed
Pydantic models, not free text — both agents call their LLM with
`with_structured_output()` against these schemas so the next node gets
validated fields (study-design case, batch/replicate/condition structure,
QC/filtering/normalization/batch/DA/visualization choices) instead of a
string to re-parse. Schemas live under `schemas/`, separate from the
agents and from `graph/state.py`, to avoid an import cycle between them.

`code_text` is the isolation boundary for LLM-generated code: it only
ever exists as a string in state until `run_code` writes it verbatim to
`workspace/code.py` and executes that file in a network-isolated
container — no agent output ever reaches a command line.

## Agents vs. placeholders

| Node | Real? |
|---|---|
| `inspect_data` | Yes — LLM call, falls back to a structural-only `DatasetSummary` if `DENBI_TOKEN` is unset or the call fails |
| `study_planer` | Yes — LLM call, falls back to a minimal `StudyPlan` on the same conditions |
| `statistical_analyser` | Placeholder — emits a fixed script, ignores `study_plan` |
| `outcome_auditor` | Placeholder — PASS/FAIL purely from the sandbox exit code |
| `write_plan`, `run_code`, `store_results` | Deterministic, not agents — implemented for real |

## Running it

```bash
docker build -t metaproteomics-sandbox:latest ./sandbox
python main.py                      # uses every CSV/TSV in input/
python main.py --dataset input/SupplementaryFile1.csv
```

`DENBI_TOKEN` (and optionally `DENBI_MODEL`, `DENBI_API_BASE`) must be set
for `inspect_data` and `study_planer` to make real LLM calls; otherwise
both fall back as described above. Requires `langgraph`/`pandas` on the
host (see `requirements.txt`) and a working `docker` CLI on `PATH`.

Artifacts: `workspace/` holds the current run (`plan.txt`, `code.py`,
whatever the generated code writes); `store_results_node` copies those
into `results/` only on a PASS audit.

## Docker Compose

[docker-compose.yml](docker-compose.yml) defines two services:

- **`analysis-sandbox`** — real, built from `./sandbox`
  (`sandbox/Dockerfile`), tagged `metaproteomics-sandbox:latest` (must
  match `IMAGE_NAME` in `sandbox/run_code.py`). Runs with `network_mode:
  none` and only `sandbox/requirements.txt` (pandas/numpy/scipy/
  matplotlib) — no LangGraph or agent dependencies. Mounts `./input` read-only
  at `/input` and `./workspace` at `/workspace`. This is the container
  `run_code_node` invokes to execute LLM-generated analysis scripts.
- **`multiagent-system`** — not yet implemented; a placeholder image tag
  gated behind the `not-yet-implemented` profile so `docker compose up`
  never tries to build/start it. The pipeline itself (`python main.py`)
  still runs on the host, since it needs outbound internet access to
  reach the deNBI LLM endpoint that `inspect_data` and `study_planer`
  call.
