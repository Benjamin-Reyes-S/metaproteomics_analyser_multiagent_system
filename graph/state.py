from operator import add
from typing import Annotated, NotRequired, Required, TypedDict


class MetaproteomicsAnalysisState(TypedDict, total=False):
    # Every CSV/TSV that belongs to the study (metadata, abundance, annotations).
    data_raw_paths: Required[list[str]]
    dataset_summary: NotRequired[dict[str, str] | None]

    # Produced by the planner
    study_plan: Required[str]

    # Produced by the auditor
    code_text: NotRequired[str | None]
    code_path: NotRequired[str | None]

    # Produced by the analysis node
    execution_status: NotRequired[str | None]

    # Produced during analysis
    output_files:list[str] | None

    evaluation: str
    evaluator_feedback:Required[str | None]

    # Multiple nodes may contribute issues, so append instead of overwrite
    issues: Annotated[list[str], add]
    retry_count: int