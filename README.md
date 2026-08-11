# Metaproteomics analyser

The data MCP separates deterministic CSV reading from semantic metadata
interpretation. The study planner consumes the resulting canonical JSON rather
than interpreting raw tables repeatedly.

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

Or select files explicitly:

```bash
python main.py \
  --dataset data/SupplementaryFile1.csv \
  --dataset data/SupplementaryFile3_1.csv
```

The plan is written to `workspace/study_plan.txt`.

## Data MCP API

- `read_csv_data(file_path, delimiter)` reads and validates a rectangular table
  without semantic inference.
- `interpret_csv_metadata(csv_data)` converts that deterministic output to the
  stable semantic JSON schema.
- `inspect_csv_study(file_paths)` auto-detects delimiters, uses a bounded preview
  for semantic reasoning, counts every row, and returns one canonical object per
  file. This is the interface used by the study planner.

Large annotation tables are not loaded fully into the planner context. Preview
and relationship limits are reported under `quality_checks.warnings`.
