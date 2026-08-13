"""Study-planning node driven by canonical metadata from mcp_data."""

import json
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graph.state import MetaproteomicsAnalysisState
from mcp.mcp_data import inspect_csv_study


class StudyPlanOutput(BaseModel):
    study_plan: str = Field(description="A grounded metaproteomics analysis plan.")
    issues: list[str] = Field(default_factory=list, description="Missing information and uncertainties.")


MODEL_NAME = os.getenv("DENBI_MODEL", "vllm/Qwen/Qwen3.6-35B-A3B")
API_BASE_URL = os.getenv("DENBI_API_BASE", "https://llm.bi.denbi.de/v1")
SYSTEM_PROMPT = """
You are a metaproteomics study planner. Input is canonical semantic JSON from
the data MCP. Treat its mappings and uncertainties as the source of truth. Do
not invent experimental design or treat protein/taxonomy/function annotations
as sample metadata. Explain every file and valid joins, identify study factors
and missing information, then provide an ordered downstream analysis plan. Put
all blockers and uncertainty in issues. Do not perform statistical analysis.
""".strip()


def _planner_model():
    api_token = os.getenv("DENBI_API_TOKEN")
    if not api_token:
        raise RuntimeError("DENBI_API_TOKEN is not set")
    return ChatOpenAI(model=MODEL_NAME, base_url=API_BASE_URL, api_key=api_token, temperature=0).with_structured_output(StudyPlanOutput, method="json_schema")


def study_planner_node(state: MetaproteomicsAnalysisState) -> dict:
    """Inspect all files through mcp_data and generate one integrated plan."""
    try:
        canonical = inspect_csv_study(state["data_raw_paths"])
        message = "Create one integrated study plan from this canonical metadata JSON. Account for every file and preserve uncertainty:\n\n" + json.dumps(canonical, indent=2, default=str)
        output = _planner_model().invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)])
        return {"study_plan": output.study_plan, "issues": output.issues}
    except Exception as exc:
        return {"study_plan": None, "issues": [f"Study planner failed: {type(exc).__name__}: {exc}"]}


study_planer_node = study_planner_node
