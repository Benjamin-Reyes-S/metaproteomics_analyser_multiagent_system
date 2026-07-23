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


@mcp.tool
	def read_csv_proteomics_dataset(path_to_dataset:str)-> df:DataFrame:
		import pandas as pd

	df = pd.read_csv(
		path_to_dataset,
		sep="\t"
	)

	print(df.columns.tolist())
	print(df.head())
	print(df.isna().sum().sort_values(ascending=False).head(10))
	return df as proteomics_dataset
	