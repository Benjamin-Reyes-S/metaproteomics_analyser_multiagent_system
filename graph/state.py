from operator import add
from typing import Annotated, NotRequired, Required, TypedDict

from schemas.schema_inspect_data import DatasetSummary
from schemas.schema_study_planer import StudyPlan


class MetaproteomicsAnalysisState(TypedDict, total=False):
    # Every CSV/TSV that belongs to the study (metadata, abundance, annotations).
    data_raw_paths: Required[list[str]]
    dataset_summary: NotRequired[DatasetSummary | None]

    # Produced by the planner
    study_plan: Required[StudyPlan]

    # Produced by the auditor
    code_text: NotRequired[str | None]
    code_path: NotRequired[str | None]

    # Produced by run_code (the sandbox execution boundary)
    execution_status: NotRequired[str | None]
    execution_stdout: NotRequired[str | None]
    execution_stderr: NotRequired[str | None]
    execution_exit_code: NotRequired[int | None]

    # Produced during analysis
    output_files:list[str] | None

    evaluation: str
    evaluator_feedback:Required[str | None]

    # Multiple nodes may contribute issues, so append instead of overwrite
    issues: Annotated[list[str], add]
    retry_count: int