"""Dataset-inspection node.

Reads basic structure (columns, dtypes, a small sample of rows) out of
every input file, then makes a single LLM call over all files together
to produce the semantic summary — file roles, valid joins, study factors,
missing information — that the next agent (study_planer) needs. The
input/output contract (`data_raw_paths` in, `dataset_summary`/`issues`
out) is unchanged; downstream nodes only ever see `state["dataset_summary"]`,
never this file's internals.

If no DENBI_TOKEN is configured, or the LLM call fails, this node falls
back to the plain structural description (columns/dtypes/row count) so
the pipeline can still run without semantic annotation.
"""

import json
import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
import pandas as pd

from graph.state import MetaproteomicsAnalysisState

DEFAULT_MODEL_NAME = "vllm/Qwen/Qwen3.6-35B-A3B"
DEFAULT_API_BASE_URL = "https://llm.bi.denbi.de/v1"

SYSTEM_PROMPT = """
You are a metaproteomics data analyzer. Do not invent experimental design
or treat protein/taxonomy/function annotations as sample metadata.
Explain every file and valid joins, identify study factors
and missing information, then provide an ordered summary of the data founded
for the next agent to develop a bioinfromatics downstream analysis with it. Put
all blockers and uncertainty in issues. Do not perform statistical analysis.
check the skill in data_comprehension.md for more details.
""".strip()


class FileSummary(BaseModel):
    path: str = Field(description="Exact input file path as given in the request.")
    summary: str = Field(
        description="What this file contains: entities, granularity, key columns, "
        "and its likely role (metadata/abundance/taxonomy/function)."
    )


class DatasetInspectionOutput(BaseModel):
    file_summaries: list[FileSummary] = Field(
        description="One entry per input file, covering every file provided."
    )
    integrated_summary: str = Field(
        description="Cross-file summary: valid joins, study factors identified, "
        "and how the files relate for the downstream analysis."
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Blockers, missing information, or uncertainty the next agent must know about.",
    )


def _summarizer_model():
    api_token = os.getenv("DENBI_TOKEN")
    if not api_token:
        raise RuntimeError("DENBI_TOKEN is not set")
    model_name = os.getenv("DENBI_MODEL", DEFAULT_MODEL_NAME)
    api_base_url = os.getenv("DENBI_API_BASE", DEFAULT_API_BASE_URL)
    return ChatOpenAI(
        model=model_name, base_url=api_base_url, api_key=api_token, temperature=0
    ).with_structured_output(DatasetInspectionOutput, method="json_schema")


def _structural_profile(path: str) -> dict:
    sample = pd.read_csv(path, nrows=1000)
    return {
        "columns": list(sample.columns),
        "dtypes": {col: str(dtype) for col, dtype in sample.dtypes.items()},
        "sampled_rows": len(sample),
        "example_rows": sample.head(5).to_dict(orient="records"),
    }


def inspect_data_node(state: MetaproteomicsAnalysisState) -> dict:
    issues: list[str] = []
    canonical: dict[str, dict] = {}

    for path in state["data_raw_paths"]:
        try:
            canonical[path] = _structural_profile(path)
        except Exception as exc:
            issues.append(f"inspect_data failed to read {path}: {type(exc).__name__}: {exc}")

    if not canonical:
        return {"dataset_summary": {}, "issues": issues}

    fallback_summary = {
        path: f"columns=[{', '.join(profile['columns'])}] sampled_rows={profile['sampled_rows']}"
        for path, profile in canonical.items()
    }

    message = (
        "Create one integrated summary from the datasets provided. Account for "
        "every file and preserve uncertainty:\n\n" + json.dumps(canonical, indent=2, default=str)
    )

    try:
        output = _summarizer_model().invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]
        )
    except Exception as exc:
        issues.append(f"inspect_data LLM call failed, using structural fallback: {type(exc).__name__}: {exc}")
        return {"dataset_summary": fallback_summary, "issues": issues}

    dataset_summary = {item.path: item.summary for item in output.file_summaries}
    for path in canonical:
        dataset_summary.setdefault(path, fallback_summary[path])
    dataset_summary["__integrated_summary__"] = output.integrated_summary

    return {"dataset_summary": dataset_summary, "issues": issues + list(output.issues)}
