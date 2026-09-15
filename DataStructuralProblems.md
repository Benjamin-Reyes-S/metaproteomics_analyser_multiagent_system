# Data Structural Problems

Notes on formatting/structural issues found in the `input/` files while debugging
`workspace/code.py`. Kept for reference so future runs (or new input files from the
same sources) don't hit the same surprises.

## 1. `SupplementaryFile3_1.csv` — wrong delimiter assumption

Despite the `.csv` extension, this file is **tab-delimited** (`\t`) with
Windows-style CRLF line endings (`\r\n`).

Reading it with `pd.read_csv(path)` (default comma separator) does not fail
immediately — instead, pandas tries to split each line on commas. Since the file
has almost no real comma delimiters, most lines parse as a single field, but the
free-text annotation columns (functional descriptions, protein names, etc.)
contain literal commas, so the *number* of comma-separated tokens varies wildly
from row to row. This makes pandas' C parser raise:

```
ParserError: Error tokenizing data. C error: Expected X fields in line Y, saw Z
```

**Fix:** read with the correct separator: `pd.read_csv(ANNOTATION_PATH, sep='\t')`.

## 2. `SupplementaryFile1.csv` — wrong delimiter *and* transposed orientation

Two separate issues stacked on top of each other:

- **Delimiter:** the file is `;`-delimited, not comma-delimited, and contains
  zero commas anywhere. Reading it with the default comma separator makes
  pandas treat each entire line as one column, so there is no real `SampleID`
  column — leading to `KeyError: 'SampleID'` the moment the code does
  `df_meta['SampleID']`.

- **Orientation:** even after fixing the separator, the table is laid out
  transposed relative to what the analysis code expects. Rows are *variables*
  (`SampleID`, `condition`, `disease`, `study`, `UseCase`) and columns are
  individual *samples* — the opposite of the usual tidy layout (one row per
  sample/observation, one column per variable):

  ```
  SampleID;20190107_06_S08F_env;20190107_08_T05F_env;...
  condition;diseased;control;...
  disease;CD;normal;...
  study;Henry;Henry;...
  UseCase;BiomarkerDiscovery;BiomarkerDiscovery;...
  ```

**Fix applied in `workspace/code.py`:**

```python
df_meta = (
    pd.read_csv(METADATA_PATH, sep=';', index_col=0)
    .T
    .reset_index()
    .rename(columns={'index': 'SampleID'})
)
```

This loads the variable names as the index, transposes so each sample becomes
a row, and restores `SampleID` as a real column (it would otherwise be
absorbed into the DataFrame index and lost as a usable column name).

## 3. `all_groups_abundance.csv` — extreme sparsity breaks median normalization

Separate from parsing, this matrix has a real data-shape problem: **96.8% of
all abundance values are exactly `0`** (protein group not detected in that
sample), and even the best-covered sample only has ~7.5% nonzero entries.

`workspace/code.py`'s normalization step filters groups down to ~7000 rows
(peptide-count + prevalence filters) and then computes each sample's median
abundance across those rows for median normalization. Because of the
sparsity above, **every single sample's median — including zeros — is still
exactly 0**, even after filtering. Dividing by a zero median turned the
entire matrix into `NaN`, which silently made every downstream row fail the
`mask.sum() < 10` non-missing check in the differential-abundance loop,
leaving the results table empty.

**Fix applied in `workspace/code.py`:** compute the per-sample median over
*detected* (nonzero) values only —
`data_matrix.replace(0, np.nan).median(axis=0)` — so the normalization
factor reflects an actual quantitative signal instead of being dominated by
non-detections. Zeros themselves are left as `0` (a real "not detected"
value), not turned into missing data.

## 5. `pd.get_dummies` dtype change (code/environment bug, not a data issue)

Not a problem with the input files, but it combined with #4 to produce the
same symptom (empty differential-abundance results → `KeyError: 'coef'`), so
it's worth recording here too. Recent pandas versions (this environment: 2.2.2)
return **bool**-dtype columns from `pd.get_dummies`. `workspace/code.py` mixes
those with an `int` `intercept` column into one DataFrame; calling `.values`
on that mix produces a numpy `object` array instead of a numeric one, which
`np.linalg.lstsq` rejects with `_UFuncInputCastingError`. The loop's bare
`except: continue` swallowed that error silently on every single row, so the
`results` list ended up empty with no visible error — the only symptom was
the downstream `KeyError: 'coef'` when the empty `results` list became a
column-less `df_da`.

**Fix applied:** cast the encoded design matrix to `float` explicitly
(`pd.get_dummies(...).astype(float)`, `intercept = 1.0`) so `.values` is a
proper numeric array pandas/numpy version-independently.

## Takeaway

Files with a `.csv` extension in this dataset are not reliably comma-delimited
or in a "tidy" row-per-observation layout — each new supplementary file should
be spot-checked for its actual delimiter (`cat -A` / `head -c` to look for
`^I` tabs, `^M` CRLF markers, or `;`) and orientation before being fed into
`pd.read_csv()` with default arguments.
