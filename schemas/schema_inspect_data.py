"""Structured output schema for the inspect_data agent.

`DatasetSummary` replaces the old `dict[str, str]` shape of
`state["dataset_summary"]` with a typed, nested model so branching
decisions downstream (study-design case, batch confounding, paired vs.
unpaired, host/microbial separation) are validated fields instead of
strings the planner has to re-parse.

Lives in its own module, separate from `agents/inspect_data.py` and
`graph/state.py`: `graph/state.py` needs these types for its TypedDict
field, and `agents/inspect_data.py` needs them for `with_structured_output`,
while `agents/inspect_data.py` itself imports `graph.state` — putting the
schema in either of those two modules would create an import cycle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MatrixInfo(BaseModel):
    path: str
    # "unknown" covers the structural-only fallback, where level can't be
    # inferred without semantic (LLM) judgment over column contents.
    level: Literal["peptide_intensity", "protein_intensity", "taxonomic", "functional", "unknown"]
    domain: Literal["host", "microbial", "mixed", "unknown"]
    n_features: int | None = None
    n_samples: int | None = None
    missingness_pct: float | None = None
    notes: str | None = None


class AnnotationPhilosophy(BaseModel):
    type: Literal["peptide_centric", "protein_centric", "mixed", "unknown"] = "unknown"
    rationale: str | None = None


class ReplicateStructure(BaseModel):
    biological_replicates_per_group: dict[str, int] = Field(default_factory=dict)
    technical_replicates: bool = False
    technical_replicate_cv: float | None = None  # flag if > 0.2
    pooled_samples: bool = False


class BatchInfo(BaseModel):
    has_known_batches: bool = False
    batch_column: str | None = None
    associated_with_pca_axes: bool | None = None
    confounded_with_biology: bool | None = None
    correction_recommended: bool | None = None
    rationale: str | None = None


class ConditionInfo(BaseModel):
    condition_column: str | None = None
    groups: list[str] = Field(default_factory=list)
    group_sizes: dict[str, int] = Field(default_factory=dict)
    paired: bool = False
    subject_column: str | None = None  # needed if paired


class LongitudinalInfo(BaseModel):
    is_longitudinal: bool = False
    timepoint_column: str | None = None
    n_timepoints: int | None = None
    subject_column: str | None = None
    site_or_cage_column: str | None = None  # for multi-factorial nesting


class MissingnessPolicy(BaseModel):
    likely_not_at_random: bool | None = None
    proposed_imputation_strategy: str | None = None
    justification: str | None = None


#class passed to the state 
class DatasetSummary(BaseModel):
    # "unknown" covers both the structural-only fallback and a genuine
    # LLM "the files don't say" verdict — either way open_questions must
    # explain why.
    study_design_case: Literal[
        "unique_sample_no_control",
        "condition_comparison",
        "longitudinal",
        "complex_multifactorial",
        "unknown",
    ] = "unknown"
    matrices: list[MatrixInfo] = Field(default_factory=list)
    annotation_philosophy: AnnotationPhilosophy = Field(default_factory=AnnotationPhilosophy)
    replicate_structure: ReplicateStructure = Field(default_factory=ReplicateStructure)
    batch_info: BatchInfo = Field(default_factory=BatchInfo)
    condition_info: ConditionInfo | None = None  # None if case 1
    longitudinal_info: LongitudinalInfo | None = None  # None if case 1/2
    known_confounders: list[str] = Field(default_factory=list)
    missingness_policy: MissingnessPolicy | None = None
    open_questions: list[str] = Field(default_factory=list)  # things planner must resolve
