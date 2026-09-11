# === setup: Define input paths and imports ===
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats

# Setup paths
ABUNDANCE_PATH = '/input/all_groups_abundance.csv'
METADATA_PATH = '/input/SupplementaryFile1.csv'
ANNOTATION_PATH = '/input/SupplementaryFile3_1.csv'

# === load_data: Load raw CSV files ===
df_abund = pd.read_csv(ABUNDANCE_PATH)
df_meta = pd.read_csv(METADATA_PATH)
df_anno = pd.read_csv(ANNOTATION_PATH)

# === data_linkage: Join abundance with metadata and group-level annotations ===
# Link Abundance to Metadata
sample_cols = [c for c in df_abund.columns if c not in ['GroupID', 'Proteins', 'Peptides']]
meta_samples = df_meta['SampleID'].tolist()
valid_samples = [s for s in sample_cols if s in meta_samples]

# Filter abundance to only include samples in metadata
df_abund_filtered = df_abund[['GroupID', 'Proteins', 'Peptides'] + valid_samples].copy()
# Reorder metadata to match abundance columns
df_meta_filtered = df_meta[df_meta['SampleID'].isin(valid_samples)].set_index('SampleID').loc[valid_samples]

# Link Abundance to Group Annotations
df_anno_group = df_anno[df_anno['level'] == 'group'].copy()
df_final = pd.merge(df_abund_filtered, df_anno_group, left_on='GroupID', right_on='#pg', how='left')

# === qc: Perform PCA to check for batch/condition clustering ===
X = df_final[valid_samples].values.astype(float)
# Simple PCA using SVD
X_centered = X - np.nanmean(X, axis=0)
U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)
coords = U @ np.diag(S)

plt.figure(figsize=(10, 7))
for cond in df_meta_filtered['condition'].unique():
    idx = df_meta_filtered[df_meta_filtered['condition'] == cond].index
    # Map index to position in valid_samples
    pos = [valid_samples.index(s) for s in idx]
    plt.scatter(coords[pos, 0], coords[pos, 1], label=cond)
plt.title('PCA of Protein Abundances')
plt.legend()
plt.savefig('/workspace/pca_plot.png')
plt.close()

# === filtering: Filter by peptide count and group-wise prevalence ===
# 1. Min unique peptides >= 2
df_final['peptide_count'] = df_final['Peptides'].str.count(';') + 1
df_filtered = df_final[df_final['peptide_count'] >= 2].copy()

# 2. Prevalence filtering (50% within at least one group)
# We check prevalence across samples for each condition
cond_groups = df_meta_filtered.groupby('condition').groups
prevalence_mask = []

for idx, row in df_filtered.iterrows():
    keep = False
    for cond, samples in cond_groups.items():
        # Count non-NaNs for this protein in this condition
        present = row[samples].notna().sum()
        if (present / len(samples)) >= 0.5:
            keep = True
            break
    prevalence_mask.append(keep)

df_filtered = df_filtered.iloc[np.array(prevalence_mask)]

# === normalization: Apply median normalization to samples ===
# Median Normalization
# Extract only numeric sample data
data_matrix = df_filtered[valid_samples].astype(float)
# Calculate sample medians
sample_medians = data_matrix.median(axis=0)
global_median = sample_medians.median()

# Normalize: (val / sample_median) * global_median
normalized_data = (data_matrix.div(sample_medians)) * global_median
df_norm = df_filtered.copy()
for col in valid_samples:
    df_norm[col] = normalized_data[col]

# === differential_abundance: Linear model for DA controlling for study ===
results = []
# Prepare design matrix
# condition: 0=control, 1=diseased
# study: dummy encoded
meta_encoded = pd.get_dummies(df_meta_filtered[['condition', 'study']], drop_first=True)
meta_encoded['intercept'] = 1

for idx, row in df_norm.iterrows():
    y = row[valid_samples].values.astype(float)
    # Handle NaNs for linear regression by dropping them from both X and y
    mask = ~np.isnan(y)
    if mask.sum() < 10: continue
    
    y_clean = y[mask]
    X_clean = meta_encoded.iloc[mask].values
    
    # Solve OLS: beta = (X^T X)^-1 X^T y
    try:
        beta, residuals, rank, s = np.linalg.lstsq(X_clean, y_clean, rcond=None)
        # The coefficient for 'condition' is the first dummy (usually)
        # Find the column name for condition_diseased
        cond_col_idx = 0 # based on drop_first=True and order
        coef = beta[cond_col_idx]
        
        # Simple p-value calculation
        std_err = np.sqrt(residuals[0] / (len(y_clean) - X_clean.shape[1])) if len(residuals)>0 else 1.0
        t_stat = coef / std_err if std_err != 0 else 0
        p_val = stats.t.sf(np.abs(t_stat), len(y_clean) - X_clean.shape[1]) * 2
        
        results.append({'GroupID': row['GroupID'], 'coef': coef, 'p_value': p_val})
    except:
        continue

df_da = pd.DataFrame(results)
df_da.to_csv('/workspace/differential_abundance_results.csv', index=False)

# === visualization: Generate volcano plot of results ===
plt.figure(figsize=(8, 6))
plt.scatter(df_da['coef'], -np.log10(df_da['p_value'] + 1e-10), alpha=0.5)
plt.axhline(-np.log10(0.05), color='red', linestyle='--')
plt.xlabel('Coefficient (Log Fold Change approx)')
plt.ylabel('-log10(p-value)')
plt.title('Volcano Plot: Diseased vs Control')
plt.savefig('/workspace/volcano_plot.png')
plt.close()

# === export_outputs: Final logging ===
print('Analysis complete. Artifacts written to /workspace.')
