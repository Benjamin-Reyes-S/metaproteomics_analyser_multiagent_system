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


class StudySummary(BaseModel):
    """Quick-glance study-planning facts, separate from the detailed
    replicate/batch/condition/longitudinal breakdowns below so a human or
    the planner doesn't have to reassemble them from those nested fields."""

    narrative: str | None = None
    n_samples_total: int | None = None
    n_samples_with_full_metadata: int | None = None
    cohorts_or_studies: list[str] = Field(default_factory=list)
    n_batches: int | None = None


class DataPointer(BaseModel):
    """Points at where one specific kind of information lives inside one file."""

    file_path: str
    columns: list[str] = Field(default_factory=list)
    information_type: Literal[
        "sample_id",
        "abundance_intensity",
        "protein_group_id",
        "protein_accession",
        "peptide_sequence",
        "taxonomic",
        "functional",
        "sample_metadata_covariate",
        "other",
    ]
    row_filter: str | None = Field(
        default=None,
        description="Condition selecting which rows this pointer applies to, if the "
        "file mixes row types under one schema, e.g. \"level == 'group'\" vs "
        "\"level == 'member'\".",
    )
    notes: str | None = None


class DataLink(BaseModel):
    """One join a downstream agent (study_planer, statistical_analyser) must
    perform to go from `source` to `target`, e.g. abundance intensity ->
    taxonomic/functional annotation, or abundance sample columns -> sample
    metadata. Protein-group-style IDs are frequently reassigned per export
    and are NOT safe to join on directly across files even when two files
    both look numerically indexed — prefer joining on the underlying
    accession/identifier columns and say so in join_procedure."""

    source: DataPointer
    target: DataPointer
    join_method: Literal[
        "exact_string_match",
        "explode_delimited_list_then_match",
        "column_header_matches_row_value",
        "unknown",
    ] = "unknown"
    cardinality: Literal["one_to_one", "many_to_one", "many_to_many", "unknown"] = "unknown"
    join_procedure: list[str] = Field(
        default_factory=list,
        description="Ordered, concrete steps to perform the join when it is not a "
        "single direct key match, e.g. ['explode source.columns on \";\"', "
        "'match each exploded value against target.columns where "
        "row_filter applies', 'read the annotation off the matched row'].",
    )
    rationale: str | None = None


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
    study_summary: StudySummary = Field(default_factory=StudySummary)
    annotation_philosophy: AnnotationPhilosophy = Field(default_factory=AnnotationPhilosophy)
    replicate_structure: ReplicateStructure = Field(default_factory=ReplicateStructure)
    batch_info: BatchInfo = Field(default_factory=BatchInfo)
    condition_info: ConditionInfo | None = None  # None if case 1
    longitudinal_info: LongitudinalInfo | None = None  # None if case 1/2
    known_confounders: list[str] = Field(default_factory=list)
    missingness_policy: MissingnessPolicy | None = None
    # The consensus join map for study_planer/statistical_analyser: where each
    # kind of information (abundance, taxonomic, functional, sample metadata)
    # physically lives and how to join across files to assemble it.
    data_linkage: list[DataLink] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)  # things planner must resolve
