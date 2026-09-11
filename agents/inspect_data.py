"""Dataset-inspection node.

Reads basic structure (columns, dtypes, a small sample of rows) out of
every input file, then makes a single LLM call over all files together
to produce the structured `DatasetSummary` (study.schemas.DatasetSummary)
that the next agent (study_planer) needs: study-design case, per-file
matrix roles, a quick-glance study_summary (sample/cohort/batch counts),
annotation philosophy, replicate/batch/condition/longitudinal structure,
the cross-file data_linkage join map (which file/column holds abundance
vs. taxonomic vs. functional information and how to join them —
consumed by study_planer and, later, statistical_analyser), and open
questions. The input/output contract (`data_raw_paths` in,
`dataset_summary`/`issues` out) is unchanged; downstream nodes only ever
see `state["dataset_summary"]`, never this file's internals.

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

from schemas.schema_inspect_data import DatasetSummary, MatrixInfo, StudySummary
from graph.state import MetaproteomicsAnalysisState

DEFAULT_MODEL_NAME = "vllm/Qwen/Qwen3.6-35B-A3B"
DEFAULT_API_BASE_URL = "https://llm.bi.denbi.de/v1"

# Metaproteomics exports routinely carry hundreds of individual per-sample
# columns (an abundance matrix's sample columns, a transposed metadata
# file's sample columns) that all share one dtype. Runs of same-dtype
# columns at or under this size are listed by name in full; longer runs are
# collapsed into one group (count + dtype + a few example names from each
# end) instead, since listing every sample name burns tokens on this LLM
# call and, if forwarded via MatrixInfo.notes, on study_planer's call too,
# without adding anything the LLM needs to reason about study design.
COLUMN_RUN_LISTING_THRESHOLD = 30
COLUMN_RUN_PREVIEW_SIZE = 3

# A protein-group row's Proteins/Peptides cell can itself be a ";"-delimited
# list of hundreds to 1000+ accessions — the LLM only needs to recognize
# that shape (and the delimiter, for join_procedure), not read every entry.
CELL_VALUE_CHAR_LIMIT = 200

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

Fill study_summary with a short narrative plus the concrete counts a
planner needs at a glance (total samples, samples actually covered by
metadata, the distinct cohorts/studies present, number of batches) —
leave a count None rather than guessing if the files don't support it.

Fill data_linkage with one DataLink entry for every join a downstream
statistical_analyser agent will need to perform to assemble abundance,
taxonomic, and functional information for one biological entity (e.g.
"abundance intensity for sample X" -> "that sample's condition/batch",
or "abundance for protein group Y" -> "protein group Y's taxonomic/
functional annotation"). Each DataPointer's file_path and columns must
be exact, copyable values (never paraphrased) so the next agent can
write pandas code straight from them; use row_filter when a file mixes
multiple row types under shared column names (e.g. a "level"/"type"
column distinguishing cluster-level rows from member-level rows).
Two join patterns are common and must be reasoned about explicitly:
- Sample identity: often the abundance matrix has one column per sample
  (join_method="column_header_matches_row_value") and a separate
  metadata file has one row per sample.
- Group/cluster identity: numeric IDs assigned to the same biological
  cluster in two different files are NOT guaranteed to match even when
  both look like simple sequential indices — each file may assign its
  own numbering independently. Never assume ID_in_file_A == ID_in_file_B
  without evidence (e.g. matching example_rows). The safe join is
  through the underlying accession/identifier list: explode a
  delimited multi-value column (join_method=
  "explode_delimited_list_then_match") and match individual accessions
  against the other file's identifier column, spelling out every step
  in join_procedure. Set join_method/cardinality to "unknown" and
  explain in rationale/open_questions if the files don't give enough
  evidence to be sure.

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
    # json_schema constrains decoding directly via response_format instead of
    # relying on the model choosing to invoke a tool call (function_calling);
    # self-hosted/gateway-served models often support the former far more
    # reliably than OpenAI-style forced tool-choice.
    return ChatOpenAI(
        model=model_name, base_url=api_base_url, api_key=api_token, temperature=0
    ).with_structured_output(DatasetSummary, method="json_schema")


def _summarize_columns(columns: list[str], dtypes: list[str]) -> list[dict]:
    """Group consecutive same-dtype columns; collapse long runs (see
    COLUMN_RUN_LISTING_THRESHOLD) into a count + a few example names."""
    groups: list[dict] = []
    start = 0
    while start < len(columns):
        end = start + 1
        while end < len(columns) and dtypes[end] == dtypes[start]:
            end += 1
        run = columns[start:end]
        if len(run) <= COLUMN_RUN_LISTING_THRESHOLD:
            groups.append({"columns": run, "dtype": dtypes[start]})
        else:
            groups.append(
                {
                    "n_columns": len(run),
                    "dtype": dtypes[start],
                    "example_columns": run[:COLUMN_RUN_PREVIEW_SIZE] + run[-COLUMN_RUN_PREVIEW_SIZE:],
                }
            )
        start = end
    return groups


def _truncate_cell(value):
    if not isinstance(value, str) or len(value) <= CELL_VALUE_CHAR_LIMIT:
        return value
    n_items = value.count(";") + 1
    return f"{value[:CELL_VALUE_CHAR_LIMIT]}... [truncated: {len(value)} chars, ~{n_items} ';'-separated items]"


def _render_column_groups(column_groups: list[dict]) -> str:
    parts = []
    for group in column_groups:
        if "columns" in group:
            parts.append(f"{group['dtype']}: {', '.join(group['columns'])}")
        else:
            examples = ", ".join(group["example_columns"])
            parts.append(f"{group['dtype']} x{group['n_columns']} (e.g. {examples})")
    return "; ".join(parts)


def _structural_profile(path: str) -> dict:
    # sep=None + engine="python" sniffs the delimiter per file (comma, semicolon,
    # tab, ...) instead of assuming comma; a hardcoded comma silently collapses
    # semicolon-delimited files into one giant column and throws on ragged
    # tab-delimited ones.
    sample = pd.read_csv(path, sep=None, engine="python", nrows=1000)
    columns = list(sample.columns)
    dtypes = [str(dtype) for dtype in sample.dtypes]
    column_groups = _summarize_columns(columns, dtypes)

    # example_rows only covers the columns actually named in column_groups
    # (small runs in full, long runs' head/tail preview) — pulling every
    # value for a 900+ column row would undo the point of collapsing the
    # column list above. .iloc uses these as positional indices, so this
    # is safe even if pandas parsed duplicate column names.
    example_row_columns: list[str] = []
    example_indices: list[int] = []
    start = 0
    for group in column_groups:
        run_len = len(group["columns"]) if "columns" in group else group["n_columns"]
        end = start + run_len
        if "columns" in group:
            example_row_columns.extend(group["columns"])
            example_indices.extend(range(start, end))
        else:
            preview = group["example_columns"]
            half = COLUMN_RUN_PREVIEW_SIZE
            example_row_columns.extend(preview)
            example_indices.extend(range(start, start + half))
            example_indices.extend(range(end - half, end))
        start = end

    example_rows = [
        [_truncate_cell(value) for value in row]
        for row in sample.iloc[:5, example_indices].values.tolist()
    ]
    return {
        "n_columns_total": len(columns),
        "column_groups": column_groups,
        "sampled_rows": len(sample),
        "example_row_columns": example_row_columns,
        "example_rows": example_rows,
    }


def _fallback_summary(canonical: dict[str, dict], reason: str) -> DatasetSummary:
    matrices = [
        MatrixInfo(
            path=path,
            level="unknown",
            domain="unknown",
            n_features=profile["n_columns_total"],
            n_samples=profile["sampled_rows"],
            notes=_render_column_groups(profile["column_groups"]),
        )
        for path, profile in canonical.items()
    ]
    return DatasetSummary(
        matrices=matrices,
        study_summary=StudySummary(narrative=reason),
        open_questions=[
            reason,
            "No semantic analysis was performed; only file structure is known.",
            "data_linkage is empty: no cross-file joins were determined without an LLM call.",
        ],
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
        "for every file and preserve uncertainty. Each file's profile groups "
        "columns as column_groups: a short run of distinct-dtype columns is "
        "listed by name under \"columns\"; a long run of same-dtype columns "
        "(e.g. hundreds of per-sample columns) is collapsed into one entry "
        "with n_columns and a few example_columns from each end, so most of "
        "those columns are NOT individually named — n_columns_total is the "
        "file's true column count. example_rows/example_row_columns are "
        "positional and cover only the columns named in column_groups: "
        "example_rows[row][i] corresponds to example_row_columns[i].\n\n"
        + json.dumps(canonical, separators=(",", ":"), default=str)
    )

    try:
        dataset_summary = _summarizer_model().invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]
        )
    except Exception as exc:
        issues.append(f"inspect_data LLM call failed, using structural fallback: {type(exc).__name__}: {exc}")
        reason = (
            f"Semantic analysis unavailable: the inspect_data LLM call failed "
            f"({type(exc).__name__}); see issues for the full error. Only file "
            "structure is known below."
        )
        return {"dataset_summary": _fallback_summary(canonical, reason), "issues": issues}

    if dataset_summary is None:
        # with_structured_output can return None instead of raising when the
        # model's response has no usable tool/function call (seen with some
        # OpenAI-compatible endpoints, e.g. vLLM-hosted models that answer in
        # plain text instead of invoking the DatasetSummary function).
        reason = (
            "Semantic analysis unavailable: the inspect_data LLM call returned no "
            "structured DatasetSummary (the model likely did not invoke the "
            "expected function call). Only file structure is known below."
        )
        issues.append(reason)
        return {"dataset_summary": _fallback_summary(canonical, reason), "issues": issues}

    return {"dataset_summary": dataset_summary, "issues": issues + list(dataset_summary.open_questions)}
