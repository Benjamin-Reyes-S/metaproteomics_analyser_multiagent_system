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


@mcp.tool
def read_csv_proteomics_dataset(path_to_dataset: str) -> dict[str, Any]:
    """Inspect a CSV/TSV proteomics table without returning the full dataset."""
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
