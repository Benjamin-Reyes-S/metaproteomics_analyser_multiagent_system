# Metaproteomics analyser

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker build -t metaproteomics-sandbox:latest ./sandbox
```

## Run the pipeline

Run against every CSV/TSV in `input/`:

```bash
python main.py
```

This runs the full LangGraph backbone (inspect data, plan, generate
code, execute it in an isolated Docker sandbox, audit the outcome, and
either store the results or retry). The agent nodes are currently
deterministic placeholders with no LLM call — see
[PIPELINE.md](PIPELINE.md) for the state contract, file layout, and
what to replace them with.