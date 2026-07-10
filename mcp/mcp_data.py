from fastmcp import FastMCP
from pydantic import BaseModel
from typing import Optional, Dict, Any


@mcp.tool
def available_batch_labels():
	return batch_labels

@mcp.tool
def number_of_studies():
	studies: [str]
	return studies, len[studies]

@mcp.tool
def number_of_samples():
		sample_labels: [str]
	return sample_labels, len[sample_labels]