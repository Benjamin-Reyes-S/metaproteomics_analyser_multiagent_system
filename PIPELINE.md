
# Pipeline backbone

LangGraph pipeline wiring agents (LLM calls) and deterministic nodes
together. Run via [main.py](main.py); full node/state code lives in
[graph/graph.py](graph/graph.py) and [graph/state.py](graph/state.py).

## Graph

Today's wiring is a strict prefix of the full pipeline design: nothing has
been removed, `outcome_auditor`/`store_results`/`write_plan`/the retry loop
are implemented but still commented out in `graph/graph.py` (see "Agents
vs. placeholders" below), pending `outcome_auditor` becoming a real agent.

### Currently wired

```
input/*.csv
     |
     v
inspect_data          (agents/inspect_data.py — agent, LLM call)
     |
     | dataset_summary: DatasetSummary
     v
save_dataset_summary  (graph/save_outputs.py — deterministic, writes workspace/dataset_summary.json)
     |
     v
study_planer          (agents/study_planer.py — agent, LLM call)
     |
     | study_plan: StudyPlan
     v
save_study_plan       (graph/save_outputs.py — deterministic, writes workspace/study_plan.txt)
     |
     v
statistical_analyser  (agents/statistical_analyser.py — agent, LLM call)
     |
     | analysis_script_plan: AnalysisScriptPlan
     v
save_analysis_script  (graph/save_outputs.py — deterministic, writes
     |                  workspace/analysis_script_plan.json + workspace/code.py, sets code_text)
     v
run_code              (graph/graph.py + sandbox/run_code.py — deterministic, Docker sandbox)
     |
     | stdout / stderr / exit_code / output_files
     v
    END
```

### Full design (implemented, not yet wired)

```
                                                        ...
run_code
     |
     v
outcome_auditor       (agents/outcome_auditor.py — placeholder, no LLM call yet)
     |
     +-- PASS --> store_results (deterministic) --> END
     |
     +-- FAIL --> statistical_analyser (retry, up to MAX_RETRIES=3, then END)
```

`write_plan` (renders `study_plan` + `issues` into `workspace/plan.txt`,
the file `store_results` later copies into `results/`) is also implemented
(`make_write_plan_node` in `graph/graph.py`) but not wired in, since
nothing downstream of it is wired either yet.

## Who talks to whom, and how

Nodes communicate through the in-memory LangGraph state
(`MetaproteomicsAnalysisState`), not files. Files are written only where a
human needs to read the result, or where a process outside Python (the
sandbox container) needs the data.

```
 agent / node             state it reads                       state it writes
 ────────────────────     ─────────────────────────────────    ─────────────────────
 inspect_data          --> data_raw_paths                   --> dataset_summary, issues
 save_dataset_summary  --> dataset_summary                  --> workspace/dataset_summary.json (file, audit only)
 study_planer          --> dataset_summary                  --> study_plan, issues
 save_study_plan       --> study_plan                       --> workspace/study_plan.txt        (file, audit only)
 statistical_analyser  --> dataset_summary, study_plan,
                            data_raw_paths                  --> analysis_script_plan, issues
 save_analysis_script  --> analysis_script_plan             --> workspace/analysis_script_plan.json (file, audit only)
                                                             --> workspace/code.py    (file, sandbox needs it)
                                                             --> code_text
 run_code              --> code_text                        --> workspace/code.py    (re-written, same content)
                                                             --> execution_*, output_files
 outcome_auditor       --> execution_*                      --> evaluation, evaluator_feedback   (not wired yet)
 store_results         --> output_files                     --> results/*  (file, on PASS only)  (not wired yet)
```

`inspect_data` also has a file side effect not shown in the table above: it
standardizes each raw input file's delimiter/orientation on disk before
profiling it and reads the result rather than `data_raw_paths` untouched.
See "Input standardization" below.

`dataset_summary` (`schemas/schema_inspect_data.py: DatasetSummary`),
`study_plan` (`schemas/schema_study_planer.py: StudyPlan`), and
`analysis_script_plan` (`schemas/analysis_script_plan.py:
AnalysisScriptPlan`) are typed Pydantic models, not free text — all three
real agents call their LLM with `with_structured_output(Schema,
method="json_schema")` against these schemas so the next node gets
validated fields instead of a string to re-parse. `AnalysisScriptPlan`
mirrors both upstream schemas so a reviewer can check every cross-file join
(`data_linkage_implementation`) and every plan decision (the
`*_implementation` fields) against `DatasetSummary`/`StudyPlan` without
reading the whole generated script; the script itself is either a single
string or an ordered list of named, independently re-runnable
`ScriptSection`s. Schemas live under `schemas/`, separate from the agents
and from `graph/state.py`, to avoid an import cycle between them.

`code_text` is the isolation boundary for LLM-generated code:
`save_analysis_script_node` (deterministic, not an LLM call) is the only
place that turns `analysis_script_plan.script` into an actual file
(`workspace/code.py`) and populates `code_text`; `run_code_node`
re-writes the same content and executes that file in a network-isolated
container — no agent output ever reaches a command line directly.

## Input standardization (mcp_server/mcp_data.py)

Input files in this project show up with inconsistent delimiters (comma,
tab, semicolon) and, for small metadata-style tables, a transposed layout
(variables as rows, samples as columns) instead of the tidy
one-row-per-sample layout the rest of the pipeline assumes — see
[DataStructuralProblems.md](DataStructuralProblems.md) for the concrete
cases that motivated this. `mcp_data.py` defines two `@mcp.tool()`-decorated
functions, `standardize_separator` and `transpose_data_file`, that fix each
problem independently: each writes a new, tagged file (e.g.
`SupplementaryFile1+Separator+Transpose.csv`) next to the original and
moves the original, untagged file into `<input_dir>/original_files/`.

**These are called as plain Python functions, not through the MCP
protocol.** `@mcp.tool()` registers them on a `FastMCP` server object, but
nothing runs that server or connects to it via an MCP client — no agent can
currently discover or invoke these tools itself. `inspect_data_node`
(`agents/inspect_data.py`) imports `mcp_server.mcp_data` directly and calls
`standardize_separator`/`transpose_data_file` deterministically, before
profiling each file, for the same reason `sandbox/run_code.py` builds its
`docker run` command deterministically: which delimiter a file uses is not
a judgment call, so there's nothing for an LLM to decide there. Making an
agent actually call these tools through MCP (via `langchain-mcp-adapters`,
already in `requirements.txt` but currently unused) would need a separate
tool-calling LLM turn before the existing `with_structured_output(...,
method="json_schema")` call, since mixing forced-schema decoding with
tool-calling in one turn is unreliable on the self-hosted model this
project targets (see "Structured-output reliability" below).

Whether a file needs transposing is decided by `_looks_transposed()`
(`agents/inspect_data.py`): a pure row-count-vs-column-count comparison,
with no semantic understanding of what the file actually is. It correctly
handles this project's known files (a small metadata table has far fewer
rows than columns; a real abundance/annotation matrix is the opposite), but
it will misfire on any file that is legitimately wide yet already correctly
oriented (e.g. a small study with 8 samples and 15 metadata columns) —
silently transposing good data. `standardize_separator` carries no such
risk; it's always safe to call (a no-op if the file is already
comma-delimited).

Standardized files and the `original_files/` archive both live inside
`input_dir` itself. Since `main.py` lists `input_dir` non-recursively when
building `data_raw_paths`, archived originals are automatically excluded
from every subsequent run without any extra filtering logic — but this also
means `data_raw_paths`, once set at graph-start, does not reflect files
this same run standardizes: on the run that performs standardization, some
paths in `state["data_raw_paths"]` stop existing on disk partway through
(moved into `original_files/`) without the state being updated to match.
The only consumer of `data_raw_paths` besides `inspect_data_node` is
`statistical_analyser`'s fallback plan, which only uses it for an
informational basename list, so this is harmless today — but
`data_raw_paths` should not be relied on for real file access by anything
added later; use `dataset_summary`'s `MatrixInfo.path` values instead,
which always reflect the standardized files.

**Known packaging gap:** `docker/Dockerfile` (the `multiagent-system`
image) does not yet `COPY mcp_server/`, so `python main.py` inside that
container currently fails with `ModuleNotFoundError: No module named
'mcp_server'` until that line is added.

## Agents vs. placeholders

| Node | Real? |
|---|---|
| `inspect_data` | Yes — LLM call, falls back to a structural-only `DatasetSummary` if `DENBI_TOKEN` is unset, the call fails, or the model returns no structured output |
| `study_planer` | Yes — LLM call, falls back to a minimal `StudyPlan` on the same conditions |
| `statistical_analyser` | Yes — LLM call, falls back to a two-section sandbox-connectivity-check script (lists `/input`, writes a marker file to `/workspace`) on the same conditions |
| `outcome_auditor` | Placeholder — PASS/FAIL purely from the sandbox exit code; not wired into the graph yet |
| `save_dataset_summary`, `save_study_plan`, `save_analysis_script`, `run_code` | Deterministic, not agents — implemented for real and wired in |
| `write_plan`, `store_results` | Deterministic, implemented for real, but not wired into the graph yet (nothing downstream needs them until `outcome_auditor` is real) |

## Structured-output reliability

All three real agents call a self-hosted, OpenAI-compatible endpoint (the
deNBI vLLM gateway), not a first-party OpenAI model, which surfaced two
failure modes now handled in code rather than left to crash the pipeline:

- **A silent `None` instead of an exception.** `with_structured_output()`
  can return `None` (not raise) when the model's response contains no
  usable tool/function call. Every node now checks for `None` after
  `invoke()` and falls back exactly as it does on a caught exception.
  Using `method="json_schema"` (constrains decoding via `response_format`
  instead of relying on the model choosing to invoke a tool) targets the
  underlying cause rather than only the symptom.
- **Schema-invalid placeholder values.** Several schemas prompt heavily
  toward answering `"unknown"` via `Literal[..., "unknown"]` fields; the
  model over-generalized that onto a few plain `int | None` / `float |
  None` / `bool | None` fields with no such option, which raised a
  `ValidationError` mid-call. Those fields
  (`schema_study_planer.py`: `FilteringPlan.min_unique_peptides`,
  `FilteringPlan.prevalence_cutoff_pct`, `BatchPlan.confounded_with_biology`)
  now have a `field_validator(mode="before")` coercing that placeholder
  string to `None`. The same class of field exists, unfixed so far, in
  `schema_inspect_data.py` and `analysis_script_plan.py`.

## Running it

```bash
docker build -t metaproteomics-sandbox:latest ./sandbox
DENBI_TOKEN=your-token python main.py     # uses every CSV/TSV in input/
DENBI_TOKEN=your-token python main.py --dataset input/SupplementaryFile1.csv
```

`DENBI_TOKEN` (and optionally `DENBI_MODEL`, `DENBI_API_BASE`) must be set
for `inspect_data`, `study_planer`, and `statistical_analyser` to make real
LLM calls; otherwise all three fall back as described above. Requires
`langgraph`/`pandas`/`langchain-openai` on the host (see
`requirements.txt`) and a working `docker` CLI with access to a Docker
daemon (for `run_code_node` to launch `analysis-sandbox`).

Artifacts: `workspace/` holds the current run's `dataset_summary.json`,
`study_plan.txt`, `analysis_script_plan.json`, `code.py`, and whatever
`code.py` itself writes when executed in the sandbox. `store_results_node`
(not wired yet) would copy accepted artifacts into `results/` only on a
PASS audit.

## Docker Compose

[docker-compose.yml](docker-compose.yml) defines two services:

- **`analysis-sandbox`** — real, built from `./sandbox`
  (`sandbox/Dockerfile`), tagged `metaproteomics-sandbox:latest` (must
  match `IMAGE_NAME` in `sandbox/run_code.py`). Runs with `network_mode:
  none` and only `sandbox/requirements.txt` (pandas/numpy/scipy/
  matplotlib) — no LangGraph or agent dependencies. `run_code_node`
  launches it directly via a `docker run` subprocess (not `docker compose
  run`), passing `-v <input_dir>:/input:ro -v <workspace_dir>:/workspace`
  with paths resolved at runtime — this is the container that executes
  LLM-generated analysis scripts.
- **`multiagent-system`** — builds from `docker/Dockerfile`, runs `python
  main.py`. Bind-mounts the repo at the identical absolute path
  (`${PWD}:${PWD}`) inside and outside the container, and mounts the
  host's Docker socket, since this container has no daemon of its own and
  needs `run_code_node` to launch `analysis-sandbox` as a sibling
  container (Docker-outside-of-Docker). The identical-path mount is what
  lets the host daemon resolve `run_code_node`'s absolute paths correctly,
  and what lets `multiagent-system` see `analysis-sandbox`'s output files
  afterward — both containers end up bind-mounting the same physical host
  directory. Needs outbound internet access to reach the LLM endpoint.
  **Currently missing a `COPY mcp_server/` line** — see the packaging gap
  noted under "Input standardization" above.
