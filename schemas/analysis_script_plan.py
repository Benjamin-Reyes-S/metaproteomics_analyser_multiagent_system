"""Structured output schema for the analysis-script-writing agent.

`AnalysisScriptPlan` is what the LLM call that turns a
`schemas.schema_inspect_data.DatasetSummary` + `schemas.schema_study_planer.StudyPlan`
pair into a runnable Python analysis script is forced to produce. It sits at
the third stage of the pipeline — profiler (`inspect_data` -> DatasetSummary)
-> planner (`study_planer` -> StudyPlan) -> script-writer (this agent ->
AnalysisScriptPlan) -> `run_code` (sandbox execution) — and is deliberately
not just `{code: str}`: every join and every plan decision has to be shown
alongside the code it produced, so a reviewer (human or `outcome_auditor`)
can catch a wrong join or a skipped normalization step without reading the
whole script.

Reiterates the join-safety warning from `schema_inspect_data.DataLink`:
protein-group-style IDs are frequently reassigned per export and are NOT
safe to join on directly across files, even when two files both look
numerically indexed. Every `data_linkage_implementation` entry must confirm
the join key actually used in the script is the underlying accession/
identifier column, never a raw protein-group-style numeric index, whenever
the referenced DataLink's cardinality is many_to_many or its notes warn
about reassigned IDs.

Kept in its own module, separate from the agent that fills it in, for the
same reason DatasetSummary and StudyPlan live outside their agents: it's a
shared, validated contract, not an implementation detail of one node.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DataLinkImplementation(BaseModel):
    """Concrete realization of exactly one `schema_inspect_data.DataLink` entry.

    One of these must exist per item in `DatasetSummary.data_linkage`, in the
    same order, so a reviewer can check each join the script performs against
    the join the profiler actually authorized — without reading the whole
    script."""

    data_link_index: int = Field(
        description="Index into the input DatasetSummary.data_linkage this entry implements."
    )
    cardinality: Literal["one_to_one", "many_to_one", "many_to_many", "unknown"] = Field(
        description="Copied from the referenced DataLink, for traceability without re-opening DatasetSummary."
    )
    join_key_column: str = Field(
        description="The column actually used as the join key in the script, e.g. 'Accession' or 'protein_id'."
    )
    join_key_is_accession_not_group_index: bool = Field(
        description="True confirms join_key_column is the underlying accession/identifier column, "
        "never a raw protein-group-style numeric index. Must be true whenever cardinality is "
        "many_to_many or the source DataLink's notes warn about reassigned protein-group IDs."
    )
    operations: list[str] = Field(
        default_factory=list,
        description="Ordered, concrete pandas/python operations realizing join_procedure, as "
        "pseudocode or real snippets, e.g. [\"source_df['Accessions'].str.split(';').explode()\", "
        "\"merge(exploded, target_df, left_on='Accessions', right_on='accession', how='left')\"].",
    )
    unmatched_row_policy: Literal[
        "dropped", "kept_as_na", "logged_and_dropped", "logged_and_kept_as_na", "other"
    ] = Field(description="What happens to rows that fail to match on this join. Must be stated explicitly, not left implicit.")
    unmatched_row_handling_notes: str | None = Field(
        default=None,
        description="Required detail when unmatched_row_policy is 'other'; optional elaboration otherwise.",
    )
    deviation_from_join_procedure: str | None = Field(
        default=None,
        description="Why operations differ from the source DataLink.join_procedure, if they do.",
    )

    @model_validator(mode="after")
    def _require_notes_for_other_policy(self) -> "DataLinkImplementation":
        if self.unmatched_row_policy == "other" and not self.unmatched_row_handling_notes:
            raise ValueError("unmatched_row_handling_notes is required when unmatched_row_policy is 'other'")
        return self


class PlanImplementationStep(BaseModel):
    """Maps one decision from a StudyPlan section to the script section that
    implements it. Captures how the decision was actually implemented rather
    than repeating the plan verbatim, so deviations are visible without a
    line-by-line diff against StudyPlan."""

    plan_step: str = Field(
        description="The specific StudyPlan decision being implemented, e.g. 'normalization_method=quantile'."
    )
    implemented_as: str = Field(description="What the script actually does to realize plan_step.")
    script_section: str = Field(
        description="Name of the ScriptSection (or region, if using a single script string) that implements this."
    )
    matches_plan: bool = Field(default=True, description="False if implemented_as deviates from plan_step.")
    deviation_reason: str | None = Field(
        default=None,
        description="Required when matches_plan is False; explains why the script departs from the plan.",
    )

    @model_validator(mode="after")
    def _require_deviation_reason(self) -> "PlanImplementationStep":
        if not self.matches_plan and not self.deviation_reason:
            raise ValueError("deviation_reason is required when matches_plan is False")
        return self


class ScriptSection(BaseModel):
    """One independently inspectable, independently re-runnable stage of the
    generated script. Preferred over one opaque script string so QC,
    filtering, normalization, batch correction, differential abundance, and
    visualization stages can each be reviewed and re-executed on their own."""

    name: Literal[
        "setup",
        "load_data",
        "data_linkage",
        "qc",
        "filtering",
        "normalization",
        "batch_correction",
        "differential_abundance",
        "visualization",
        "export_outputs",
        "other",
    ]
    purpose: str = Field(description="One-line statement of what this section accomplishes.")
    code: str
    depends_on: list[str] = Field(
        default_factory=list, description="Names of other sections that must run before this one."
    )


class ResolvedAssumption(BaseModel):
    """One open question the script-writer had to resolve on its own, or a
    new assumption introduced only at code-writing time (e.g. a numeric
    imputation floor with no basis in DatasetSummary or StudyPlan)."""

    origin: Literal[
        "dataset_summary_open_question", "study_plan_open_question", "introduced_at_code_time"
    ]
    question_or_gap: str = Field(
        description="The open question being resolved, or a description of the new gap if origin is introduced_at_code_time."
    )
    assumption_made: str
    impact_if_wrong: str | None = Field(
        default=None, description="What would break or silently mislead downstream if this assumption is wrong."
    )


class OutputArtifact(BaseModel):
    """One file the script is expected to produce, so a caller can validate
    the script actually produced what was promised."""

    path: str = Field(description="Expected file path/name the script writes, relative to the run's workspace directory.")
    kind: Literal["table", "figure", "stats_result", "model_object", "log", "other"]
    description: str = Field(description="One-line description of what this artifact contains.")
    produced_by_section: str | None = Field(
        default=None, description="Name of the ScriptSection that writes this artifact, if using sectioned code."
    )


class AnalysisScriptPlan(BaseModel):
    """Structured output of the script-writing agent: profiler (`inspect_data`
    -> DatasetSummary) -> planner (`study_planer` -> StudyPlan) -> script-
    writer (this agent -> AnalysisScriptPlan) -> `run_code` (sandbox
    execution). Forces the agent to show its work — every join and every
    plan decision — in a form checkable against the two upstream schemas
    without reading the whole generated script.

    Protein-group-style IDs are frequently reassigned per export and are NOT
    safe to join on directly across files, even when two files both look
    numerically indexed: every `data_linkage_implementation` entry must
    confirm the join key actually used is the underlying accession/
    identifier column, not a raw protein-group index, whenever the
    referenced DataLink's cardinality is many_to_many or its notes warn
    about reassigned IDs."""

    study_design_case: Literal[
        "unique_sample_no_control",
        "condition_comparison",
        "longitudinal",
        "complex_multifactorial",
        "unknown",
    ] = Field(description="Copied from the input StudyPlan/DatasetSummary, for traceability.")
    summary: str = Field(description="Short narrative overview of what the script does, for a human reviewer.")

    # Highest priority: one entry per DatasetSummary.data_linkage item, in order.
    data_linkage_implementation: list[DataLinkImplementation] = Field(
        default_factory=list,
        description="One entry per DatasetSummary.data_linkage[i], in the same order. "
        "Empty only if data_linkage was empty.",
    )

    # Plan-to-code traceability, mirroring StudyPlan's six sections.
    qc_implementation: list[PlanImplementationStep] = Field(default_factory=list)
    filtering_implementation: list[PlanImplementationStep] = Field(default_factory=list)
    normalization_implementation: list[PlanImplementationStep] = Field(default_factory=list)
    batch_implementation: list[PlanImplementationStep] = Field(default_factory=list)
    differential_abundance_implementation: list[PlanImplementationStep] = Field(default_factory=list)
    visualization_implementation: list[PlanImplementationStep] = Field(default_factory=list)

    script: str | list[ScriptSection] = Field(
        description="The generated analysis code. Prefer list[ScriptSection] (named, ordered, "
        "independently re-runnable stages) so QC/filtering/normalization/batch/DA/viz can each be "
        "inspected on their own; fall back to a single str only when the analysis is trivial enough "
        "that staged sections would be artificial."
    )

    assumptions_and_gaps: list[ResolvedAssumption] = Field(
        default_factory=list,
        description="Carries forward DatasetSummary.open_questions / StudyPlan.open_questions that "
        "had to be resolved to write the script, plus any new assumptions introduced only at "
        "code-writing time.",
    )

    outputs_manifest: list[OutputArtifact] = Field(default_factory=list)

    open_questions: list[str] = Field(
        default_factory=list,
        description="Things the script-writer still could not resolve, carried forward for "
        "outcome_auditor or a human.",
    )
