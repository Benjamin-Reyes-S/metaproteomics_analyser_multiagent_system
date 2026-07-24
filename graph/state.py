from operator import add
from typing import Annotated, NotRequired, TypedDict


class MetaproteomicsAnalysisState(TypedDict, total=False):
    data_raw_path: Required[str]

    # Produced by the planner
    study_plan: NotRequired[str | None]

    # Produced by the auditor
    evaluation_study_plan: NotRequired[bool | None]

    # Produced by the analysis node
    downstream_analysis: NotRequired[bool | None]

    # Produced during analysis
    data_outcomes: NotRequired[list[str] | None]
    plot_paths: NotRequired[list[str] | None]

    # Multiple nodes may contribute issues, so append instead of overwrite
    issues: Annotated[list[str], add]
