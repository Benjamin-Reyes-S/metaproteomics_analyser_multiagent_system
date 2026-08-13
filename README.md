# Metaproteomics analyser

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DENBI_API_TOKEN="your-api-token"
```

The planner uses the OpenAI-compatible endpoint
`https://llm.bi.denbi.de/v1` and model `vllm/Qwen/Qwen3.6-35B-A3B`.
The token is read only from `DENBI_API_TOKEN`; do not commit it. Override the
defaults, if necessary, with `DENBI_API_BASE` and `DENBI_MODEL`.

## Run the planner

Run against every CSV/TSV in `data/`:

```bash
python main.py
```

```

The plan is written to `workspace/study_plan.txt`.