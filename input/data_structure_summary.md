# Metaproteomics Dataset — Structure & Join Summary
*For handoff from `inspect_data` agent → `study_planner` agent*

## 0. Dataset overview

Three files together describe an MPA-style (metaproteomics pipeline) output: a **protein-group abundance matrix**, **sample clinical/study metadata**, and **protein-group functional/taxonomic annotation**. They must be joined through two different keys — one for samples, one for proteins — described below.

| File | Delimiter | Shape | Role |
|---|---|---|---|
| `all_groups_abundance.csv` | comma (quoted) | 45,432 rows × 963 cols | Quantitative core: abundance per protein-group per sample |
| `SupplementaryFile1.csv` | semicolon, **transposed** | 5 rows × 607 cols | Sample-level clinical/study metadata (subset of samples) |
| `SupplementaryFile3_1.csv` | tab | 1,456,393 rows × 22 cols | Protein-group functional + taxonomic + CAZy annotation |

---

## 1. `all_groups_abundance.csv` — abundance matrix

- 45,432 data rows = 45,432 protein groups (homology/peptide-sharing clusters, see §4)
- 963 columns total: 3 metadata columns + 960 sample columns

| Column | Type | Description |
|---|---|---|
| `GroupID` | int (as string, 1-indexed, `"1"`...`"45432"`) | Unique ID for one protein group. **Not** directly derivable from any other file's ID — must be joined via protein accession (§4). |
| `Proteins` | str, `;`-delimited list | All protein accessions belonging to this group (mixed ID formats: UniProt-style e.g. `A0A023PXH9`, and catalog-style e.g. `HG5380117`). Group size ranges from 1 to 1000+ accessions. |
| `Peptides` | str, `;`-delimited list | Observed tryptic peptide sequences supporting this group (identification evidence). |
| `<sample_name>` (× 960 cols) | float, 0–~0.02 | Relative abundance of this protein group in that sample. Very sparse (many zeros). Compositional data — not raw counts. |

**Sample columns come from many different cohorts/studies** with inconsistent naming conventions (e.g. `01_C`, `160513-SM-A1C8J-5`, `P18a_CD`, `NASH`, `HCC`, `PD_xx`, `NO_xx`, `CO_xx`). Only 606 of the 960 are covered by `SupplementaryFile1.csv` metadata (see §2).

---

## 2. `SupplementaryFile1.csv` — sample metadata

- **Transposed layout**: row 1 = header-like sample list, subsequent rows = one attribute each, one value per sample column.
- 606 samples total, all confirmed to be a **subset** of the 960 sample columns in the abundance file. 354 abundance-file samples (NASH, HCC, PD_xx, CO_xx, NO_xx, and a handful of others) have **no metadata here**.

| Row (attribute) | Values seen | Description |
|---|---|---|
| `SampleID` | e.g. `20190107_06_S08F_env`, `P18a_CD` | Sample identifier — **must exactly match a column name** in `all_groups_abundance.csv` |
| `condition` | `control`, `diseased` | Binary case/control label |
| `disease` | `normal`, `CD`, `UC`, `IBD-ND`, `IBD-ND-OS`, `CD-OS`, `UC-OS`, `IBD` | Finer-grained diagnosis |
| `study` | `Henry`, `Lehmann`, `Lloyd-Price`, `Thuy-Boun`, `Wolf_2021`, `Wolf_2024_BL/W14-A/W14-R` | Source cohort/study — important confound/batch variable |
| `UseCase` | `BiomarkerDiscovery`, `BiomarkerValidation` | Pre-assigned train/validation split intended for biomarker workflows |

**To use programmatically:** transpose to long/tidy form → one row per `SampleID` with columns `condition, disease, study, UseCase`.

---

## 3. `SupplementaryFile3_1.csv` — functional / taxonomic / CAZy annotation

- Tab-delimited, 1,456,393 rows, two row *types* distinguished by the `level` column:
  - `level == "group"` → 45,432 rows, one per annotated protein-group cluster
  - `level == "member"` → 1,410,961 rows, one per individual protein accession, carrying a **copy** of its parent group's annotation

| Column | On `group` rows | On `member` rows |
|---|---|---|
| (unnamed col 0) | sequential row index (0-based) | sequential row index (0-based) |
| `level` | `"group"` | `"member"` |
| `#pg` | 0-indexed sequential counter over group rows only (**not** the abundance file's `GroupID** — see §4) | same `#pg` as its parent group |
| `members_count` | integer, size of this cluster | `-` |
| `min_seqlen` / `max_seqlen` | sequence length range within cluster | `-` |
| `min_rel_pairw_ident` / `max_rel_pairw_ident` | pairwise sequence identity range (%) within cluster — can be very wide (e.g. 8.84–98.91) | `-` |
| `members_identifier` | `;`-joined list of **all** accessions in the cluster | **single accession** for this member row — the real join key to `Proteins` in the abundance file |
| `task_0::Functional_Annotation_Task_1::*` (main role, subrole, og, desc, seed ortholog) | eggNOG-style functional annotation | copied from parent group |
| `task_1::Taxonomic_Annotation_Task_1::*` (superkingdom → species) | consensus/LCA-style taxonomic lineage for the cluster | copied from parent group |
| `task_2::Functional_Annotation_Task_2::*` (description, CAZyDB family ID) | CAZy carbohydrate-active enzyme annotation | copied from parent group |

---

## 4. Cross-file join keys — IMPORTANT, verified empirically

### 4a. Samples: abundance columns ↔ `SupplementaryFile1.csv`
- **Key:** exact string match between a sample column name in `all_groups_abundance.csv` and the `SampleID` row value in `SupplementaryFile1.csv`.
- **Coverage:** only 606 / 960 sample columns have metadata. The planner must decide how to handle the 354 unmatched samples (different cohorts entirely — NASH, HCC, Parkinson's, colorectal, etc. — likely out of scope for an IBD-focused study).

### 4b. Protein groups: abundance `GroupID` ↔ file3 group annotation
- **`GroupID` and `#pg` are NOT the same numbering** — confirmed by direct test. E.g. abundance `GroupID=1`'s full 371-protein list matches file3 `#pg=971` exactly (and only that group); `GroupID=2`'s 133 proteins match `#pg=941` exactly.
- The **correct and only reliable join path** is through individual protein accessions:
  1. Explode `Proteins` (from abundance row) into individual accessions.
  2. Look up each accession among file3's `member`-level rows (`members_identifier`) to get its parent `#pg`.
  3. All accessions from one `GroupID` resolve to the same single `#pg` (1:1 correspondence at the group level, just non-sequentially numbered).
  4. Pull the group-level annotation (taxonomy, function, CAZy) from that `#pg`'s `group` row.
- **Practical recommendation:** build this `GroupID → #pg → annotation` mapping **once** as a lookup table (45,432 entries) and cache/persist it, rather than re-joining 1.4M rows repeatedly — the member-level table is the expensive side of the join.

---

## 5. Known data-quality considerations for the study planner

- **Compositional/sparse data**: abundance values are relative (not counts), heavily zero-inflated → standard differential-abundance methods for compositional data are appropriate (e.g. CLR transform, ANCOM-BC, ALDEx2), not naive t-tests on raw values.
- **Batch/study confounding**: `study` spans multiple independent cohorts with different sample-prep/naming; must be modeled or corrected for in any diseased-vs-control comparison.
- **Partial metadata coverage**: 354 of 960 samples in the abundance matrix have no clinical annotation — scope any analysis to the 606 annotated samples unless the other cohorts are separately relevant.
- **Annotation granularity varies**: some protein groups are single-species/singleton (fine-grained taxonomy), others span wide pairwise-identity ranges and get a coarse LCA-style taxonomic label (e.g. phylum/kingdom level) — taxonomic resolution is not uniform across `GroupID`s.
- **Pre-built train/validation split**: `UseCase` (`BiomarkerDiscovery` / `BiomarkerValidation`) appears designed for direct use as a train/test split for biomarker modeling — worth respecting rather than re-splitting.

---

## 6. Suggested key/field names for state object design

For building the classes to pass between agents, these are the natural entities and their primary/foreign keys:

- **Sample**: `sample_id` (PK, matches abundance column name), `condition`, `disease`, `study`, `use_case`
- **ProteinGroup**: `group_id` (PK, from abundance file), `proteins` (list[str]), `peptides` (list[str]), `pg_annotation_id` (FK → AnnotationCluster, resolved via §4b join, not directly present in source data)
- **AnnotationCluster**: `pg` (PK), `members_count`, `seqlen_range`, `pairwise_identity_range`, `members` (list[str]), `functional_annotation` (main_role, subrole, og, desc, seed_ortholog), `taxonomic_lineage` (superkingdom…species), `cazy_annotation` (description, family_id)
- **AbundanceRecord**: `group_id` (FK), `sample_id` (FK), `abundance` (float) — the long-form melt of the abundance matrix
