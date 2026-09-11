"""Structured output schema for the study_planer agent.

`StudyPlan` is what the LLM call in `agents/study_planer.py` is forced to
produce. It mirrors the six sequential downstream stages a metaproteomics
analysis plan must schedule (QC -> filtering -> normalization -> batch
assessment/correction -> differential abundance -> visualization) and is
built from `schemas.schema_inspect_data.DatasetSummary`, the same way
DatasetSummary itself was built from raw file structure. Kept in its own
module (not in `agents/study_planer.py`) for the same reason
DatasetSummary lives outside `agents/inspect_data.py`: it's a shared,
validated contract, not an implementation detail of the node that fills
it in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _blank_placeholder_to_none(value):
    """Coerce a placeholder string (the LLM's catch-all "I don't know" answer
    for the many Literal[..., "unknown"] fields elsewhere in this schema) to
    None on fields that are plain int/float/bool and have no such literal
    option -- otherwise a stray "unknown" here fails validation outright and
    discards an otherwise-usable plan."""
    if isinstance(value, str) and value.strip().lower() in {"unknown", "n/a", "na", "none", ""}:
        return None
    return value


class QCPlan(BaseModel):
    host_microbial_separated: bool = True
    checks: list[str] = Field(
        default_factory=list,
        description="Concrete QC checks to run, e.g. IDs/sample, total intensity/sample, "
        "missingness %, PCA by condition/batch/subject, RLE plots, technical-replicate CV, "
        "per-taxon/function coverage.",
    )
    flags_to_investigate: list[str] = Field(
        default_factory=list,
        description="Thresholds/anomalies to check before normalization, e.g. "
        "'technical-replicate CV > 0.2 within a condition/batch', 'high keratin/contaminant fraction'.",
    )


class FilteringPlan(BaseModel):
    remove_contaminants_and_decoys: bool = True
    min_unique_peptides: int | None = None
    prevalence_cutoff_pct: float | None = None
    prevalence_grouping: Literal["within_group", "across_dataset", "unknown"] = "within_group"
    filter_host_and_microbial_separately: bool = True
    rationale: str

    @field_validator("min_unique_peptides", "prevalence_cutoff_pct", mode="before")
    @classmethod
    def _coerce_unknown(cls, value):
        return _blank_placeholder_to_none(value)


class NormalizationPlan(BaseModel):
    intensity_method: Literal[
        "log2",
        "median",
        "global_scaling",
        "quantile",
        "vsn",
        "internal_reference_or_pooled_qc",
        "software_provided",
        "none",
        "unknown",
    ] = "unknown"
    compositional_method: Literal[
        "relative_abundance", "clr", "aitchison_distance", "none", "unknown"
    ] = "unknown"
    rationale: str


class BatchPlan(BaseModel):
    evaluate_before_correcting: bool = True
    confounded_with_biology: bool | None = None
    correction_method: Literal[
        "none",
        "covariate_in_model",
        "remove_batch_effect_for_viz_only",
        "combat",
        "internal_reference_scaling",
        "qc_loess_run_order",
        "mixed_effects",
        "unknown",
    ] = "unknown"
    validation_checks: list[str] = Field(
        default_factory=list,
        description="How the chosen correction (if any) will be validated, e.g. "
        "'PCA before/after', 'variance explained by batch vs biology', 'technical-replicate CVs'.",
    )
    rationale: str

    @field_validator("confounded_with_biology", mode="before")
    @classmethod
    def _coerce_unknown(cls, value):
        return _blank_placeholder_to_none(value)


class DifferentialAbundancePlan(BaseModel):
    applicable: bool
    model_type: Literal[
        "none",
        "t_test",
        "anova",
        "limma_moderated",
        "linear_model",
        "mixed_effects_model",
        "msstats",
        "compositional_da",
        "unknown",
    ] = "unknown"
    model_formula: str | None = Field(
        default=None, description="e.g. 'abundance ~ condition + batch + covariate'"
    )
    paired: bool = False
    missing_value_policy: str = Field(
        description="Explicit stance on imputation, since metaproteomics missingness can be "
        "abundance-dependent; must state whether/how missing values are handled, not just "
        "'impute with minimum'."
    )
    reporting_requirements: list[str] = Field(
        default_factory=list,
        description="e.g. 'log2 fold change', 'CIs', 'raw and FDR-adjusted p-values', "
        "'number of observations supporting each protein/function'.",
    )
    rationale: str


class VisualizationPlan(BaseModel):
    protein_level: list[str] = Field(default_factory=list)
    taxonomic_level: list[str] = Field(default_factory=list)
    functional_level: list[str] = Field(default_factory=list)


class StudyPlan(BaseModel):
    study_design_case: Literal[
        "unique_sample_no_control",
        "condition_comparison",
        "longitudinal",
        "complex_multifactorial",
        "unknown",
    ]
    summary: str = Field(description="Short narrative overview of the analysis strategy for a human reader.")
    qc_plan: QCPlan
    filtering_plan: FilteringPlan
    normalization_plan: NormalizationPlan
    batch_plan: BatchPlan
    differential_abundance_plan: DifferentialAbundancePlan
    visualization_plan: VisualizationPlan
    annotation_philosophy_impact: str | None = Field(
        default=None,
        description="How peptide-centric vs. protein-centric annotation shapes taxonomic/"
        "functional read-outs for this study, if relevant.",
    )
    open_questions: list[str] = Field(
        default_factory=list, description="Things the planner could not resolve from dataset_summary alone."
    )
