"""MCP tools for loading CSV data and Markdown study-planning guidance."""

import csv
import re
from pathlib import Path

from fastmcp import FastMCP


mcp = FastMCP("metaproteomics-data")


@mcp.tool()
def read_csv_data(file_path: str, delimiter: str = ",") -> dict:
    """Read a CSV file deterministically without guessing or type conversion.

<<<<<<< HEAD
    The first row is treated as the header. Every value is returned as text in
    its original row order; an absent trailing value is returned as ``None``.
    UTF-8 with an optional byte-order mark is supported.
=======
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

>>>>>>> b2c482148b5172bc1f1b49e8b133e40a1cbb0ba2

    Args:
        file_path: Path to a file whose extension is ``.csv``.
        delimiter: One-character field delimiter. It defaults to a comma.

    Returns:
        The resolved path, column names, row count, and rows as dictionaries.
    """
    path = Path(file_path).expanduser().resolve()
    if path.suffix.lower() != ".csv":
        raise ValueError("file_path must point to a .csv file")
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    if len(delimiter) != 1:
        raise ValueError("delimiter must be exactly one character")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise ValueError("CSV file is empty") from exc

        if not columns or any(column == "" for column in columns):
            raise ValueError("CSV header names must not be empty")
        if len(columns) != len(set(columns)):
            raise ValueError("CSV header names must be unique")

<<<<<<< HEAD
        rows = []
        for row_number, values in enumerate(reader, start=2):
            if len(values) > len(columns):
                raise ValueError(
                    f"CSV row {row_number} has {len(values)} fields; "
                    f"expected at most {len(columns)}"
                )
            padded_values = values + [None] * (len(columns) - len(values))
            rows.append(dict(zip(columns, padded_values)))
=======
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
>>>>>>> b2c482148b5172bc1f1b49e8b133e40a1cbb0ba2

    return {
        "file_path": str(path),
        "columns": columns,
        "row_count": len(rows),
        "rows": rows,
    }


<<<<<<< HEAD
@mcp.tool()
def read_markdown_skill(file_path: str) -> dict:
    """Read an agent skill or study-planning context from a Markdown file.
=======
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
>>>>>>> b2c482148b5172bc1f1b49e8b133e40a1cbb0ba2

    Markdown headings are also exposed as ordered sections. This lets an agent
    use the full document as its prompt context while addressing individual
    sections by heading.

    Args:
        file_path: Path to a Markdown file with a ``.md`` extension.

    Returns:
        The resolved path, complete Markdown text, and ordered sections. Each
        section contains its heading level, title, and body.
    """
    path = Path(file_path).expanduser().resolve()
    if path.suffix.lower() != ".md":
        raise ValueError("file_path must point to a .md file")
    if not path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {path}")

    content = path.read_text(encoding="utf-8-sig")
    heading_pattern = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
    sections = []
    current = {"level": 0, "title": "Preamble", "lines": []}

    for line in content.splitlines():
        match = heading_pattern.match(line)
        if match:
            if current["lines"] or current["title"] != "Preamble":
                sections.append(
                    {
                        "level": current["level"],
                        "title": current["title"],
                        "content": "\n".join(current["lines"]).strip(),
                    }
                )
            current = {
                "level": len(match.group(1)),
                "title": match.group(2).strip(),
                "lines": [],
            }
        else:
            current["lines"].append(line)

    if current["lines"] or current["title"] != "Preamble":
        sections.append(
            {
                "level": current["level"],
                "title": current["title"],
                "content": "\n".join(current["lines"]).strip(),
            }
        )

    return {
        "file_path": str(path),
        "content": content,
        "sections": sections,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
