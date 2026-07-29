import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
from fastmcp import FastMCP


mcp = FastMCP("metaproteomics-data")

SCHEMA_COLUMNS = {
    "N": {"short_name": "rank", "aliases": []},
    "Unused": {
        "short_name": "score",
        "aliases": ["Unused (ProtScore)", "Unused ProtScore"],
    },
    "Total": {
        "short_name": "total_score",
        "aliases": ["Total (ProtScore)", "Total ProtScore"],
    },
    "%Cov": {"short_name": "coverage", "aliases": []},
    "%Cov(50)": {"short_name": "coverage_50", "aliases": []},
    "%Cov(95)": {"short_name": "coverage_95", "aliases": []},
    "Accession": {
        "short_name": "protein_id",
        "aliases": ["Accessions", "Protein Accession"],
    },
    "Name": {
        "short_name": "protein_name",
        "aliases": ["Names", "Protein Name"],
    },
    "Species": {
        "short_name": "organism",
        "aliases": ["Organism", "Taxon"],
    },
}

LABEL_COLUMN_CANDIDATES = {
    "batch": ("batch", "batch_id", "batch_label"),
    "study": ("study", "study_id", "study_label", "project", "project_id"),
    "sample": ("sample", "sample_id", "sample_label", "sample_name"),
}

IDENTIFIER_COLUMN_NAMES = {
    "groupid",
    "protein",
    "proteins",
    "peptide",
    "peptides",
    "accession",
    "name",
    "species",
}


def _resolve_dataset(path_to_dataset: str) -> Path:
    path = Path(path_to_dataset).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Dataset does not exist or is not a file: {path}")
    return path


def _detect_separator(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(64 * 1024)

    if not sample.strip():
        raise ValueError(f"Dataset is empty: {path}")

    try:
        return csv.Sniffer().sniff(sample, delimiters="\t,;").delimiter
    except csv.Error:
        first_line = sample.splitlines()[0]
        counts = {separator: first_line.count(separator) for separator in ("\t", ",", ";")}
        separator = max(counts, key=counts.get)
        if counts[separator] == 0:
            raise ValueError("Could not detect a tab, comma, or semicolon delimiter")
        return separator


def _read_dataset(path_to_dataset: str) -> tuple[Path, str, pd.DataFrame]:
    path = _resolve_dataset(path_to_dataset)
    separator = _detect_separator(path)
    dataframe = pd.read_csv(path, sep=separator, encoding="utf-8-sig", low_memory=False)
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    return path, separator, dataframe


def _schema_matches(columns: list[str]) -> tuple[dict[str, str], list[str]]:
    available = {column.casefold(): column for column in columns}
    matches: dict[str, str] = {}
    missing: list[str] = []

    for source, definition in SCHEMA_COLUMNS.items():
        accepted_names = [source, *definition["aliases"]]
        matched = next(
            (available[name.casefold()] for name in accepted_names if name.casefold() in available),
            None,
        )
        if matched is None:
            missing.append(source)
        else:
            matches[matched] = definition["short_name"]
    return matches, missing


def _find_column(
    dataframe: pd.DataFrame,
    kind: str,
    column_name: str | None,
) -> str | None:
    available = {column.casefold(): column for column in dataframe.columns}
    if column_name is not None:
        matched = available.get(column_name.strip().casefold())
        if matched is None:
            raise ValueError(
                f"Column {column_name!r} was not found. Available columns: "
                f"{list(dataframe.columns)}"
            )
        return matched
    return next(
        (available[name] for name in LABEL_COLUMN_CANDIDATES[kind] if name in available),
        None,
    )


def _label_summary(
    path_to_dataset: str,
    kind: str,
    column_name: str | None,
) -> dict[str, Any]:
    _, _, dataframe = _read_dataset(path_to_dataset)
    column = _find_column(dataframe, kind, column_name)
    if column is None:
        return {
            "column": None,
            "count": None,
            "labels": [],
            "available": False,
            "reason": f"No {kind} label column was found in the dataset.",
        }

    labels = dataframe[column].dropna().astype(str).drop_duplicates().tolist()
    return {
        "column": column,
        "count": len(labels),
        "labels": labels,
        "available": True,
        "missing_values": int(dataframe[column].isna().sum()),
    }


def inspect_csv_proteomics_dataset(path_to_dataset: str) -> dict[str, Any]:
    """Inspect a CSV/TSV proteomics table without returning the full dataset.

    This undecorated function can be called directly by graph nodes.  The MCP
    tool below delegates to it when the data server is used independently.
    """
    path, separator, dataframe = _read_dataset(path_to_dataset)
    columns = list(dataframe.columns)
    schema_matches, missing_schema_columns = _schema_matches(columns)
    recognized = set(schema_matches)

    return {
        "path": str(path),
        "format": "tsv" if separator == "\t" else "csv",
        "separator": "\\t" if separator == "\t" else separator,
        "row_count": int(len(dataframe)),
        "column_count": int(len(columns)),
        "columns": columns,
        "column_types": {column: str(dtype) for column, dtype in dataframe.dtypes.items()},
        "schema_column_mapping": schema_matches,
        "missing_schema_columns": missing_schema_columns,
        "additional_columns": [column for column in columns if column not in recognized],
        "missing_values": {
            column: int(count)
            for column, count in dataframe.isna().sum().items()
            if int(count) > 0
        },
        "preview": json.loads(dataframe.head(5).to_json(orient="records")),
    }


def _count_rows(path: Path) -> int:
    """Count physical data rows without loading a potentially huge table."""
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _compact_file_inspection(path_to_dataset: str) -> tuple[dict[str, Any], set[str]]:
    """Create a bounded summary suitable for an LLM context window."""
    path = _resolve_dataset(path_to_dataset)
    separator = _detect_separator(path)
    preview = pd.read_csv(
        path,
        sep=separator,
        encoding="utf-8-sig",
        low_memory=False,
        nrows=200,
    )
    preview.columns = [str(column).strip() for column in preview.columns]
    columns = list(preview.columns)
    folded = {column.casefold() for column in columns}
    schema_matches, _ = _schema_matches(columns)
    label_names = {
        candidate
        for candidates in LABEL_COLUMN_CANDIDATES.values()
        for candidate in candidates
    }
    label_columns = [column for column in columns if column.casefold() in label_names]
    numeric_columns = preview.select_dtypes(include="number").columns.tolist()

    table_type = "unclassified_table"
    sample_columns: list[str] = []
    metadata_fields: list[str] = []
    if len(schema_matches) >= 4:
        table_type = "protein_identification_summary"
    elif columns and columns[0].casefold() in {"sampleid", "sample_id"} and len(columns) > len(preview):
        table_type = "transposed_sample_metadata"
        sample_columns = columns[1:]
        metadata_fields = preview.iloc[:, 0].dropna().astype(str).tolist()
    elif label_columns:
        table_type = "sample_metadata"
        sample_column = next(
            (
                column
                for column in label_columns
                if column.casefold() in LABEL_COLUMN_CANDIDATES["sample"]
            ),
            None,
        )
        if sample_column:
            sample_columns = (
                preview[sample_column].dropna().astype(str).drop_duplicates().tolist()
            )
        metadata_fields = columns
    elif "groupid" in folded and len(columns) > 20:
        table_type = "protein_group_abundance_matrix"
        sample_columns = [
            column
            for column in columns
            if column.casefold() not in IDENTIFIER_COLUMN_NAMES
        ]
    elif "level" in folded and ("#pg" in folded or "members_identifier" in folded):
        table_type = "protein_group_functional_annotation"
    elif len(numeric_columns) > 2:
        if folded & IDENTIFIER_COLUMN_NAMES:
            table_type = "feature_abundance_matrix"
    missing = preview.isna().sum()
    summary = {
        "file_name": path.name,
        "path": str(path),
        "inferred_table_type": table_type,
        "format": "tsv" if separator == "\t" else "csv",
        "row_count": _count_rows(path),
        "column_count": len(columns),
        "columns_head": columns[:30],
        "columns_tail": columns[-10:] if len(columns) > 30 else [],
        "numeric_column_count_in_preview": len(numeric_columns),
        "preview_rows_inspected": len(preview),
        "columns_with_missing_values_in_preview": {
            column: int(count)
            for column, count in missing.items()
            if int(count) > 0
        },
        "sample_count_inferred_from_columns": len(sample_columns) or None,
        "sample_ids_head": sample_columns[:20],
        "metadata_fields": metadata_fields[:30],
        "schema_column_mapping": schema_matches,
    }
    return summary, set(sample_columns)


def inspect_csv_study(path_to_datasets: list[str]) -> dict[str, Any]:
    """Inspect all study CSV/TSV files and describe their likely relationships."""
    if not path_to_datasets:
        raise ValueError("No CSV/TSV datasets were supplied")

    files: list[dict[str, Any]] = []
    samples_by_file: dict[str, set[str]] = {}
    for dataset_path in path_to_datasets:
        summary, sample_ids = _compact_file_inspection(dataset_path)
        files.append(summary)
        if sample_ids:
            samples_by_file[summary["file_name"]] = sample_ids

    overlaps = []
    names = list(samples_by_file)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            left_ids = samples_by_file[left]
            right_ids = samples_by_file[right]
            overlap = left_ids & right_ids
            overlaps.append(
                {
                    "left_file": left,
                    "right_file": right,
                    "matching_sample_ids": len(overlap),
                    "left_only": len(left_ids - right_ids),
                    "right_only": len(right_ids - left_ids),
                    "matching_ids_head": sorted(overlap)[:20],
                }
            )

    return {
        "file_count": len(files),
        "files": files,
        "sample_identifier_overlaps": overlaps,
        "inspection_note": (
            "All files and headers were inspected. Missing-value and dtype summaries "
            "use at most the first 200 rows to keep the planner prompt bounded."
        ),
    }


@mcp.tool
def read_csv_proteomics_dataset(path_to_dataset: str) -> dict[str, Any]:
    """Inspect a CSV/TSV proteomics table without returning the full dataset."""
    return inspect_csv_proteomics_dataset(path_to_dataset)


@mcp.tool
def available_batch_labels(
    path_to_dataset: str,
    column_name: str | None = None,
) -> dict[str, Any]:
    """List batch labels, optionally using an explicitly named batch column."""
    return _label_summary(path_to_dataset, "batch", column_name)


@mcp.tool
def number_of_studies(
    path_to_dataset: str,
    column_name: str | None = None,
) -> dict[str, Any]:
    """Count study labels, optionally using an explicitly named study column."""
    return _label_summary(path_to_dataset, "study", column_name)


@mcp.tool
def number_of_samples(
    path_to_dataset: str,
    column_name: str | None = None,
) -> dict[str, Any]:
    """Count sample labels, optionally using an explicitly named sample column."""
    return _label_summary(path_to_dataset, "sample", column_name)


@mcp.resource(
    "metaproteomics://schemas/pxd001655/protein-summary",
    mime_type="application/json",
)
def metaproteomics_schema() -> str:
    """Return the supported PXD001655 protein-summary column mapping."""
    return json.dumps(
        {
            "dataset": "PXD001655 protein-summary",
            "table_level": "protein",
            "columns": SCHEMA_COLUMNS,
            "rules": [
                "Match headers case-insensitively using source names and aliases.",
                "Do not assume sample, study, or batch metadata is present.",
                "Report missing schema columns instead of inventing values.",
            ],
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
