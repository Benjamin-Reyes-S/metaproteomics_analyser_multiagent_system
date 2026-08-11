"""Namespace-safe loader for the repository's data MCP implementation.

The implementation remains in ``mcp/mcp_data.py`` for use as an MCP server,
but the directory is intentionally not a Python package because FastMCP itself
depends on the third-party package named ``mcp``.
"""

import importlib.util
import sys
from pathlib import Path


_IMPLEMENTATION = Path(__file__).resolve().parent / "mcp" / "mcp_data.py"
_SPEC = importlib.util.spec_from_file_location("_metaproteomics_mcp_data", _IMPLEMENTATION)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load data MCP implementation: {_IMPLEMENTATION}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

inspect_csv_study = _MODULE.inspect_csv_study
interpret_csv_metadata = _MODULE.interpret_csv_metadata

__all__ = ["inspect_csv_study", "interpret_csv_metadata", "read_csv_data"]
