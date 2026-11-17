# Metaproteomics analyser

A LangGraph multi-agent pipeline that inspects metaproteomics study files,
drafts a study plan, generates analysis code, and runs that code in an
isolated Docker sandbox. See [PIPELINE.md](PIPELINE.md) for details.

```
inspect_data -> save_dataset_summary -> study_planer -> save_study_plan
  -> statistical_analyser -> save_analysis_script -> run_code
  -> save_code_output -> END
```

## 1. Create a `.env` file

Create a file named `.env` in the repo root with your LLM credentials.
It is gitignored, so it is never committed.

```dotenv
DENBI_TOKEN=your-token
DENBI_MODEL=your-model
DENBI_API_BASE=your-api-endpoint
```

Docker Compose reads `.env` automatically.

## 2. Build the images

```bash
sudo docker build -t metaproteomics-sandbox:latest ./sandbox
sudo docker compose build multiagent-system
```

## 3. Run the pipeline

Put the study CSV/TSV files in `input/`, then:

```bash
sudo docker compose run --rm multiagent-system
```

`multiagent-system` starts the sandbox container itself through the
mounted Docker socket (`/var/run/docker.sock`). The sandbox runs with no
network access, reads `input/` read-only and writes into `workspace/`.

## 4. Where the output is

```
workspace/
  dataset_summary.json        inspect_data output
  study_plan.txt              study_planer output
  analysis_script_plan.json   statistical_analyser output
  code.py                     the generated script that runs in the sandbox
  output/                     files code.py produced (reset on every run)
    execution_log.txt         exit code, stdout and stderr of the sandbox run
    plots/                    images code.py produced
```

The sandbox run times out after 1 hour; the container is then stopped.

## Run `code.py` in the sandbox by hand

Useful for re-running the generated script without the agents:

```bash
sudo docker run --rm \
  --network none \
  -v "$PWD/input:/input:ro" \
  -v "$PWD/workspace:/workspace" \
  -w /workspace \
  metaproteomics-sandbox:latest \
  python /workspace/code.py
```

Run it from the repo root. Results are written to `workspace/` (not
`workspace/output/`, which only the pipeline fills).
