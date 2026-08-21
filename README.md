# Metaproteomics analyser

A LangGraph multi-agent pipeline for planning (and, eventually, running)
metaproteomics data analyses: it inspects raw study files, drafts a
structured study plan, generates analysis code, and executes that code
in an isolated Docker sandbox. See [PIPELINE.md](PIPELINE.md) for the
full graph, state contract, and file layout.

## Repo layout

```
agents/     inspect_data, study_planer (real LLM calls); statistical_analyser,
            outcome_auditor (placeholders, no LLM call yet)
graph/      graph.py (LangGraph wiring), state.py (shared state), save_outputs.py
            (writes agent outputs to workspace/ for inspection)
schemas/    Pydantic schemas (DatasetSummary, StudyPlan) the two real agents
            call their LLM with via with_structured_output()
sandbox/    Dockerfile + requirements.txt + run_code.py for the isolated,
            network-disabled container that executes generated analysis code
docker/     Dockerfile for the multiagent-system container (runs main.py)
input/      study CSV/TSV files (gitignored; large files stay local-only)
workspace/  current run's artifacts (dataset_summary.json, study_plan.txt, ...)
results/    accepted artifacts, copied over once the full pipeline PASSes audit
```

## Setup

Two ways to run it: directly on the host, or via Docker Compose
(recommended, since it also gives `run_code_node` the sandbox image and a
Docker socket without you needing `docker`/`langgraph` installed locally
beyond Docker itself).

### Option A: Docker Compose

```bash
docker build -t metaproteomics-sandbox:latest ./sandbox
docker compose build multiagent-system
```

### Option B: host Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker build -t metaproteomics-sandbox:latest ./sandbox
```

Either way, a working `docker` CLI is required on `PATH`/the container
(for `run_code_node` to launch the `analysis-sandbox` image).

## LLM credentials

`inspect_data` and `study_planer` call an OpenAI-compatible endpoint
(defaults to the deNBI-hosted vLLM gateway) and need `DENBI_TOKEN` set;
`DENBI_MODEL` and `DENBI_API_BASE` are optional overrides. Without a
token, or if the call fails, both agents fall back to a minimal
structural-only result instead of erroring out.

Pass credentials inline on the command itself rather than `export`-ing
them into your shell session, so the token doesn't linger in your
environment or end up in any file:

```bash
DENBI_TOKEN=your-token DENBI_MODEL=your-model DENBI_API_BASE=your-api-base \
  docker compose run --rm multiagent-system
```

(`docker-compose.yml` only declares the bare variable names under
`environment:`, so it forwards whatever is in the invoking shell's
environment — it never stores a value itself.)

## Run the pipeline

Every CSV/TSV under `input/`:

```bash
docker compose run --rm multiagent-system
# or, on the host:
python main.py
```

A specific subset (must all live in the same directory):

```bash
docker compose run --rm multiagent-system --dataset input/SupplementaryFile1.csv
```

`multiagent-system` is capped at 25GB RAM (`mem_limit` in
`docker-compose.yml`).

### Current graph wiring

`graph/graph.py` is currently wired for a 2-agent test run:

```
inspect_data -> save_dataset_summary -> study_planer -> save_study_plan -> END
```

`save_dataset_summary`/`save_study_plan` (`graph/save_outputs.py`) write
the two agents' structured outputs to `workspace/dataset_summary.json`
and `workspace/study_plan.txt` so they can be inspected directly. The
rest of the full pipeline — `write_plan`, `statistical_analyser`,
`run_code`, `outcome_auditor`, `store_results`, and the PASS/FAIL retry
loop — is implemented but commented out in `graph/graph.py`/`main.py`
pending `statistical_analyser`/`outcome_auditor` becoming real agents.
See [PIPELINE.md](PIPELINE.md) for that full design.

## Docker Compose services

- **`multiagent-system`** — builds from `docker/Dockerfile`, runs
  `python main.py`. Bind-mounts the repo at the same absolute path
  inside and outside the container (so paths `run_code_node` resolves
  stay valid on the host) and mounts the host's Docker socket, since
  this container has no daemon of its own and needs to launch
  `analysis-sandbox` as a sibling container (Docker-outside-of-Docker).
  Needs outbound internet access to reach the LLM endpoint.
- **`analysis-sandbox`** — builds from `./sandbox`
  (`sandbox/Dockerfile`), tagged `metaproteomics-sandbox:latest` (must
  match `IMAGE_NAME` in `sandbox/run_code.py`). Runs with
  `network_mode: none` and only `sandbox/requirements.txt`
  (pandas/numpy/scipy/matplotlib) — no LangGraph or agent dependencies.
  Mounts `./input` read-only and `./workspace` read-write.
