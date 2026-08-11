"""Bounded MCP tools for deterministic CSV study inspection."""

import csv
import json
import re
from collections import Counter
from pathlib import Path

from fastmcp import FastMCP


mcp = FastMCP("metaproteomics-data")

MISSING_VALUES = {"", "-", "na", "n/a", "nan", "none", "null", "unknown", "unclassified"}
FIELD_ALIASES = {
    "sample_id": {"sampleid", "sample id", "sample_id", "sample"},
    "subject_id": {"subject", "subjectid", "subject_id", "patient", "donor"},
    "condition": {"condition", "group", "experimental arm", "disease state"},
    "treatment": {"treatment", "intervention", "drug"},
    "disease": {"disease", "diagnosis"},
    "phenotype": {"phenotype"}, "cohort": {"cohort"},
    "study_id": {"study", "studyid", "study_id"},
    "use_case": {"usecase", "use case", "use_case"},
    "timepoint": {"timepoint", "time point", "visit"},
    "replicate": {"replicate"}, "batch": {"batch"},
    "organism": {"organism", "species"}, "tissue": {"tissue"},
    "protein_id": {"protein", "protein id", "protein_id", "accession", "members_identifier"},
    "protein_group_id": {"protein group", "protein_group_id", "groupid", "#pg"},
    "peptide_id": {"peptide", "peptide id", "peptide_id", "sequence"},
    "taxonomy_id": {"taxonomy id", "taxonomy_id", "taxid"},
}
STUDY_CONCEPTS = {"sample_id", "subject_id", "condition", "treatment", "disease", "phenotype", "cohort", "study_id", "use_case", "timepoint", "replicate", "batch", "organism", "tissue"}

MAX_FILES = 50
MAX_PREVIEW_ROWS = 100
MAX_EXAMPLES = 5
MAX_IDENTIFIERS = 20
MAX_RELATIONSHIPS = 100
MAX_FIELD_MAPPINGS = 250
MAX_CELL_CHARS = 500
MAX_RESPONSE_CHARS = 400_000


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", str(value).casefold()).strip()


def _canonical_field(label: str) -> tuple[str | None, float, str]:
    normalized = _normalized(label)
    for canonical, aliases in FIELD_ALIASES.items():
        if normalized in aliases:
            return canonical, 0.98, "The label matches a known semantic concept."
    if any(term in normalized for term in ("function", "description", "role", "subrole", "ortholog", "cazy")):
        return "functional_annotation", 0.92, "The field describes biological function."
    if any(term in normalized for term in ("superkingdom", "phylum", "class", "order", "family", "genus", "species")):
        return "organism_annotation", 0.96, "The field is a taxonomic rank annotation."
    if normalized in {"level", "members count", "members_count"}:
        return "group_membership", 0.92, "The field describes protein-group membership."
    return None, 0.0, "Semantic meaning could not be determined confidently."


def _detect_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(65536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        counts = {item: first.count(item) for item in ",;\t|"}
        delimiter = max(counts, key=counts.get)
        if not counts[delimiter]:
            raise ValueError(f"Could not detect delimiter for {path}")
        return delimiter


def _bounded_text(value) -> str:
    text = "" if value is None else str(value)
    return text[:MAX_CELL_CHARS]


def _unique_examples(values, limit: int = MAX_EXAMPLES) -> list[str]:
    result = []
    for value in values:
        value = _bounded_text(value)
        if value.casefold() in MISSING_VALUES or value in result:
            continue
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _read_preview(path: Path, delimiter: str, limit: int = MAX_PREVIEW_ROWS) -> tuple[list[str], list[dict], int]:
    rows, row_count = [], 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise ValueError(f"CSV file is empty: {path}") from exc
        if len(columns) != len(set(columns)):
            raise ValueError(f"CSV header names must be unique: {path}")
        for number, values in enumerate(reader, 2):
            if len(values) != len(columns):
                raise ValueError(f"CSV row {number} has {len(values)} fields; expected {len(columns)}")
            row_count += 1
            if len(rows) < limit:
                rows.append(dict(zip(columns, map(_bounded_text, values))))
    return columns, rows, row_count


def interpret_csv_metadata(csv_data: dict) -> dict:
    """Convert deterministic CSV output or a bounded preview to canonical JSON."""
    columns = list(csv_data["columns"])
    rows = list(csv_data["rows"])
    first_values = [str(row.get(columns[0], "")) for row in rows]
    first_concepts = [_canonical_field(value)[0] for value in first_values]
    transposed = len(columns) > 2 and bool(rows) and sum(c in STUDY_CONCEPTS for c in first_concepts) / len(rows) >= 0.4
    if transposed:
        fields = [(str(row.get(columns[0], "")), [str(row.get(column, "")) for column in columns[1:]]) for row in rows]
        all_entities = columns[1:]
        entities = all_entities[:MAX_IDENTIFIERS]
        orientation, entity_axis, attribute_axis = "entities_as_columns", "columns", "rows"
    else:
        fields = [(column, [str(row.get(column, "")) for row in rows]) for column in columns]
        all_entities = []
        entities, orientation, entity_axis, attribute_axis = [], "records_as_rows", "rows", "columns"

    mappings, unmapped, concept_values = [], [], {}
    mappings_truncated = len(fields) > MAX_FIELD_MAPPINGS
    for source, values in fields[:MAX_FIELD_MAPPINGS]:
        canonical, confidence, reason = _canonical_field(source)
        item = {"source_field": source, "canonical_field": canonical, "semantic_type": "categorical", "values_example": _unique_examples(values), "confidence": confidence, "status": "mapped" if canonical else "unknown", "reason": reason}
        mappings.append(item)
        if canonical:
            concept_values.setdefault(canonical, []).extend(values)
        else:
            unmapped.append({"source_field": source, "values_example": item["values_example"], "reason": reason})

    mapped = set(concept_values)
    has_study = bool(mapped & STUDY_CONCEPTS)
    has_groups = "protein_group_id" in mapped or "group_membership" in mapped
    has_bio = bool(mapped & {"protein_id", "peptide_id", "taxonomy_id", "organism_annotation", "functional_annotation"})
    if has_study and (has_groups or has_bio): role = "mixed_metadata"
    elif has_study: role = "sample_metadata" if transposed or "sample_id" in mapped else "study_metadata"
    elif has_groups: role = "protein_group_annotation"
    elif "peptide_id" in mapped: role = "peptide_annotation"
    elif "organism_annotation" in mapped and "functional_annotation" not in mapped: role = "taxonomy_annotation"
    elif "functional_annotation" in mapped and "organism_annotation" not in mapped: role = "functional_annotation"
    elif has_bio: role = "mixed_metadata"
    else: role = "unknown"
    entity_type = "sample" if role == "sample_metadata" else "protein_or_protein_group" if role == "protein_group_annotation" else "mixed" if role == "mixed_metadata" else "unknown"
    identifier = next((m for m in mappings if m["canonical_field"] in {"sample_id", "protein_group_id", "protein_id", "peptide_id"}), None)
    if not entities and identifier:
        entities = _unique_examples((row.get(identifier["source_field"]) for row in rows), MAX_IDENTIFIERS)

    design = {key: [] for key in ("sample_ids", "subject_ids", "conditions", "controls", "treatments", "diseases", "phenotypes", "cohorts", "timepoints", "batches", "replicates", "studies", "use_cases", "factors", "potential_confounders")}
    bucket = {"subject_id": "subject_ids", "condition": "conditions", "treatment": "treatments", "disease": "diseases", "phenotype": "phenotypes", "cohort": "cohorts", "timepoint": "timepoints", "batch": "batches", "replicate": "replicates", "study_id": "studies", "use_case": "use_cases"}
    if transposed: design["sample_ids"] = entities
    for concept, target in bucket.items():
        design[target] = _unique_examples(concept_values.get(concept, []), MAX_EXAMPLES)
    design["factors"] = [m["source_field"] for m in mappings if m["canonical_field"] in {"condition", "treatment", "disease", "phenotype", "cohort", "timepoint"}]
    design["potential_confounders"] = [m["source_field"] for m in mappings if m["canonical_field"] in {"batch", "study_id"}]
    biological = {"protein_ids": _unique_examples(concept_values.get("protein_id", [])), "protein_group_ids": _unique_examples(concept_values.get("protein_group_id", [])), "peptide_ids": _unique_examples(concept_values.get("peptide_id", [])), "taxonomy_ids": _unique_examples(concept_values.get("taxonomy_id", [])), "organisms": _unique_examples(concept_values.get("organism", []) + concept_values.get("organism_annotation", [])), "functional_annotations": _unique_examples(concept_values.get("functional_annotation", []))}
    relationships = []
    if transposed:
        for source, values in fields[:MAX_RELATIONSHIPS]:
            relationships.append({
                "attribute": source,
                "entity_count": len(all_entities),
                "value_examples": _unique_examples(values),
                "missing_count_in_preview": sum(
                    _bounded_text(value).casefold() in MISSING_VALUES
                    for value in values
                ),
            })
    warnings = []
    row_count = int(csv_data.get("row_count", len(rows)))
    if len(rows) < row_count: warnings.append(f"Semantic interpretation used a {len(rows)}-row preview of {row_count} rows.")
    if len(fields) > MAX_RELATIONSHIPS and transposed: warnings.append(f"Relationship summaries were limited to {MAX_RELATIONSHIPS} attributes.")
    if mappings_truncated: warnings.append(f"Field mappings were limited to {MAX_FIELD_MAPPINGS} fields.")
    confidence = min(0.99, 0.55 + 0.08 * len(mapped)) if role != "unknown" else 0.2
    usable = role in {"sample_metadata", "study_metadata", "mixed_metadata"} and has_study
    return {"schema_version": "1.0", "source": {"file_path": csv_data.get("file_path", ""), "row_count": row_count, "column_count": len(columns)}, "table_interpretation": {"table_role": role, "orientation": orientation, "entity_type": entity_type, "entity_axis": entity_axis, "attribute_axis": attribute_axis, "confidence": round(confidence, 2), "reasoning_summary": "The first column contains metadata attributes and remaining headers identify samples." if transposed else "Columns describe attributes and each row is an entity record."}, "entities": {"primary_entity": entity_type, "identifier_count": len(all_entities) if transposed else None, "identifier_examples": entities, "identifiers_truncated": transposed and len(all_entities) > len(entities), "identifier_source": "column_headers" if transposed else (identifier["source_field"] if identifier else "unknown")}, "field_mappings": mappings, "study_design": design, "biological_annotations": biological, "unmapped_fields": unmapped, "relationships": relationships, "quality_checks": {"duplicate_entity_ids": [value for value, count in Counter(entities).items() if value and count > 1], "missing_entity_ids": [], "inconsistent_fields": [], "possible_missing_values": [], "warnings": warnings}, "uncertainties": [] if not unmapped else [{"issue": f"{len(unmapped)} field(s) could not be mapped confidently.", "possible_interpretations": [], "confidence": 0.0, "additional_information_needed": "A data dictionary for the unmapped fields."}], "summary": {"usable_for_study_design": usable, "study_design_confidence": round(confidence, 2) if usable else 0.0, "description": f"Classified as {role} with {orientation} orientation."}}


@mcp.tool()
def inspect_csv_study(file_paths: list[str]) -> dict:
    """Return a bounded semantic study manifest for one or more CSV files.

    The result contains schemas, inferred roles, study factors, identifier
    examples, relationship summaries, warnings, and uncertainties. Raw rows
    and complete measurement tables are never returned.
    """
    if not file_paths:
        raise ValueError("At least one CSV file is required")
    if len(file_paths) > MAX_FILES:
        raise ValueError(f"At most {MAX_FILES} files may be inspected per call")

    files = []
    for file_path in file_paths:
        path = Path(file_path).expanduser().resolve()
        delimiter = _detect_delimiter(path)
        columns, rows, row_count = _read_preview(path, delimiter)
        result = interpret_csv_metadata({"file_path": str(path), "columns": columns, "row_count": row_count, "rows": rows})
        result["source"]["delimiter"] = {"\t": "tab", ";": "semicolon", ",": "comma", "|": "pipe"}[delimiter]
        files.append(result)
    manifest = {"schema_version": "1.0", "files": files}
    serialized = json.dumps(manifest, ensure_ascii=False)
    if len(serialized) > MAX_RESPONSE_CHARS:
        raise ValueError(
            f"Study manifest is too large: {len(serialized):,} characters; "
            f"maximum is {MAX_RESPONSE_CHARS:,}. Inspect fewer files per call."
        )
    return manifest


if __name__ == "__main__":
    mcp.run(transport="stdio")