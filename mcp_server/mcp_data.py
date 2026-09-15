"""MCP server for standardizing metaproteomics input data file formats.

Input files in this project routinely show up with inconsistent delimiters
(comma, tab, semicolon) and, for small metadata-style tables, a transposed
layout (variables as rows, samples as columns) instead of the tidy
one-row-per-sample layout the rest of the pipeline assumes. See
DataStructuralProblems.md for concrete examples. The two tools below fix
each problem independently so an agent can call whichever one a given file
needs.

Both tools write their result as a new, tagged file next to the original
(e.g. "SupplementaryFile1+Separator.csv", or "...+Separator+Transpose.csv"
if both are applied in sequence), and move the original, untagged file into
an "original_files" subdirectory under INPUT_DIR itself -- so a top-level,
non-recursive directory scan of INPUT_DIR only ever finds one, unambiguous
version of each file, while the raw original stays around on disk for
reference.
"""

import csv
import shutil
from pathlib import Path

import pandas as pd
from fastmcp import FastMCP

mcp = FastMCP("Data Standardization")

ORIGINAL_FILES_SUBDIR = "original_files"
TAGS = ("Separator", "Transpose")


def _sniff_separator(path: Path) -> str:
    with open(path, newline="") as f:
        sample = f.readline()
    return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter


def _is_tagged(path: Path) -> bool:
    return any(tag in path.stem for tag in TAGS)


def _tagged_path(path: Path, tag: str) -> Path:
    return path.with_name(f"{path.stem}+{tag}{path.suffix}")


def _archive_original(path: Path, input_dir: Path) -> str | None:
    """Move an untagged original out of INPUT_DIR once it's been replaced.

    Returns the archive path, or None if `path` is already a tagged
    (previously standardized) file and should be left where it is.
    """
    if _is_tagged(path):
        return None
    archive_dir = input_dir / ORIGINAL_FILES_SUBDIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / path.name
    shutil.move(str(path), str(archive_path))
    return str(archive_path)


@mcp.tool()
def standardize_separator(file_path: str, input_dir: str) -> dict:
    """Rewrite a CSV/TSV file to use "," as its delimiter.

    CSV and TSV files in this project's inputs use different delimiters
    (",", "\\t", ";"), which confuses agents that assume comma-separated
    data. Detects the file's actual delimiter, and if it isn't already
    ",", rewrites the file as "<name>+Separator.csv" in INPUT_DIR and
    archives the original into "<input_dir>/original_files/".

    If the file is already comma-delimited, nothing is changed.
    """
    src = Path(input_dir) / file_path
    separator = _sniff_separator(src)

    if separator == ",":
        return {"output_path": str(src), "changed": False, "archived_original": None}

    df = pd.read_csv(src, sep=separator)
    out_path = _tagged_path(src, "Separator")
    df.to_csv(out_path, index=False)
    archived = _archive_original(src, Path(input_dir))

    return {"output_path": str(out_path), "changed": True, "archived_original": archived}


@mcp.tool()
def transpose_data_file(file_path: str, input_dir: str) -> dict:
    """Transpose a variables-as-rows file into samples-as-rows.

    Some metaproteomics metadata files store one row per variable (e.g.
    SampleID, condition, study) and one column per sample -- the
    assumption here is that the file has far more samples than variables,
    so this call should only be made on that kind of small, wide table,
    not on a large abundance/feature matrix. Transposes it so each sample
    becomes a row and the first column is named "SampleID", writes the
    result as "<name>+Transpose.csv" in INPUT_DIR, and archives the
    original into "<input_dir>/original_files/".
    """
    src = Path(input_dir) / file_path
    separator = _sniff_separator(src)

    df = pd.read_csv(src, sep=separator, index_col=0)
    df = df.T.reset_index().rename(columns={"index": "SampleID"})
    out_path = _tagged_path(src, "Transpose")
    df.to_csv(out_path, index=False)
    archived = _archive_original(src, Path(input_dir))

    return {"output_path": str(out_path), "changed": True, "archived_original": archived}


if __name__ == "__main__":
    mcp.run()
