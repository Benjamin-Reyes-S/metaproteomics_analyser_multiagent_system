"""Dataset-inspection node.

Reads basic structure (columns, dtypes, a small sample of rows) out of
every input file, then makes a single LLM call over all files together
to produce the structured `DatasetSummary` (study.schemas.DatasetSummary)
that the next agent (study_planer) needs: study-design case, per-file
matrix roles, annotation philosophy, replicate/batch/condition/
longitudinal structure, and open questions. The input/output contract
(`data_raw_paths` in, `dataset_summary`/`issues` out) is unchanged;
downstream nodes only ever see `state["dataset_summary"]`, never this
file's internals.

If no DENBI_TOKEN is configured, or the LLM call fails, this node falls
back to a structural-only DatasetSummary (columns/dtypes/row count per
file, everything semantic left "unknown") so the pipeline can still run
without semantic annotation.
"""

import json
import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import pandas as pd

from schemas.schema_inspect_data import DatasetSummary, MatrixInfo
from graph.state import MetaproteomicsAnalysisState

DEFAULT_MODEL_NAME = "vllm/Qwen/Qwen3.6-35B-A3B"
DEFAULT_API_BASE_URL = "https://llm.bi.denbi.de/v1"

SYSTEM_PROMPT = """
You are a metaproteomics data analyzer preparing a structured DatasetSummary
for a downstream study-planning agent. Do not invent experimental design or
treat protein/taxonomy/function annotations as sample metadata.

Classify the study into exactly one study_design_case:
- unique_sample_no_control: single microbiome/condition, descriptive only.
- condition_comparison: two or more discrete groups being compared.
- longitudinal: the same subject(s)/microbiome(s) sampled at multiple time points.
- complex_multifactorial: multiple factors varying together (e.g. time x
  condition, time x site).
Use "unknown" only if the files genuinely do not contain enough metadata
to decide, and explain why in open_questions.

Add one MatrixInfo entry per input file: its level
(peptide_intensity/protein_intensity/taxonomic/functional/unknown), its
domain (host/microbial/mixed/unknown), and in `notes` its role, key
columns, and how it joins to the other files.

Set annotation_philosophy based on whether peptides were collapsed into
protein (sub)groups before annotation (protein_centric) or kept with all
in-silico digest matches (peptide_centric).

Fill replicate_structure, batch_info, condition_info (only when the case
involves 2+ groups), longitudinal_info (only when longitudinal or
complex_multifactorial), known_confounders, and missingness_policy from
whatever metadata columns are actually present. Leave a field at its
default (None/empty/false) rather than guessing when the files don't say.

Put every blocker, ambiguity, or missing piece of information the planner
must resolve into open_questions. Do not perform statistical analysis.
""".strip()


def _summarizer_model():
    api_token = os.getenv("DENBI_TOKEN")
    if not api_token:
        raise RuntimeError("DENBI_TOKEN is not set")
    model_name = os.getenv("DENBI_MODEL", DEFAULT_MODEL_NAME)
    api_base_url = os.getenv("DENBI_API_BASE", DEFAULT_API_BASE_URL)
    return ChatOpenAI(
        model=model_name, base_url=api_base_url, api_key=api_token, temperature=0
    ).with_structured_output(DatasetSummary, method="function_calling")


def _structural_profile(path: str) -> dict:
    # sep=None + engine="python" sniffs the delimiter per file (comma, semicolon,
    # tab, ...) instead of assuming comma; a hardcoded comma silently collapses
    # semicolon-delimited files into one giant column and throws on ragged
    # tab-delimited ones.
    sample = pd.read_csv(path, sep=None, engine="python", nrows=1000)
    # dtypes/example_rows are positional (aligned with "columns" by index), not
    # keyed by column name: a record-per-row dict repeats every column name once
    # per example row, which blows up the LLM prompt for wide tables (hundreds of
    # columns x several rows x long column-name strings).
    return {
        "columns": list(sample.columns),
        "dtypes": [str(dtype) for dtype in sample.dtypes],
        "sampled_rows": len(sample),
        "example_rows": sample.head(5).values.tolist(),
    }


def _fallback_summary(canonical: dict[str, dict], reason: str) -> DatasetSummary:
    matrices = [
        MatrixInfo(
            path=path,
            level="unknown",
            domain="unknown",
            n_features=len(profile["columns"]),
            n_samples=profile["sampled_rows"],
            notes=f"columns=[{', '.join(profile['columns'])}]",
        )
        for path, profile in canonical.items()
    ]
    return DatasetSummary(
        matrices=matrices,
        open_questions=[reason, "No semantic analysis was performed; only file structure is known."],
    )


def inspect_data_node(state: MetaproteomicsAnalysisState) -> dict:
    issues: list[str] = []
    canonical: dict[str, dict] = {}

    for path in state["data_raw_paths"]:
        try:
            canonical[path] = _structural_profile(path)
        except Exception as exc:
            issues.append(f"inspect_data failed to read {path}: {type(exc).__name__}: {exc}")

    if not canonical:
        return {"dataset_summary": None, "issues": issues}

    message = (
        "Build a DatasetSummary for the study described by these files. Account "
        "for every file and preserve uncertainty. In each file's profile, "
        "\"dtypes\" and \"example_rows\" are positional: dtypes[i] and every "
        "example_rows[row][i] correspond to columns[i].\n\n"
        + json.dumps(canonical, separators=(",", ":"), default=str)
    )

    try:
        dataset_summary = _summarizer_model().invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]
        )
    except Exception as exc:
        reason = f"inspect_data LLM call failed, using structural fallback: {type(exc).__name__}: {exc}"
        issues.append(reason)
        return {"dataset_summary": _fallback_summary(canonical, reason), "issues": issues}

    return {"dataset_summary": dataset_summary, "issues": issues + list(dataset_summary.open_questions)}
