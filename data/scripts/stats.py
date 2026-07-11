import os
import pandas as pd
import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt
import seaborn as sns
from statsmodels.stats.multicomp import pairwise_tukeyhsd
import warnings
warnings.filterwarnings('ignore')

# --- 1. CONFIGURATION & DATA LOADING ---
FILE_PATH = 'Stats/tcp_results_all_sessions_final.xlsx'

try:
    df = pd.read_excel(FILE_PATH)
except FileNotFoundError:
    try:
        df = pd.read_excel('tcp_results_all_sessions_cleaned_final.xlsx')
    except FileNotFoundError:
        print(f"Error: Could not find '{FILE_PATH}'. Ensure your terminal is in the same folder.")
        exit()

print("="*60)
print("TCP VARIANTS STATISTICAL ANALYSIS REPORT (FYP EDITION)")
print("="*60)

# Rename veno2 to amended_veno
df['tcp_variant'] = df['tcp_variant'].replace({'veno2': 'amended_veno'})

# Defined metrics for statistical analysis
metrics = ['throughput_mbps', 'rtt_ms', 'retransmissions']

# Set graphing style for FYP Report
sns.set_theme(style="whitegrid")
plt.rcParams.update({'font.size': 12, 'figure.dpi': 300})

# --- 2. SNR COLUMN SELECTION ---
if 'snr_avg' in df.columns:
    df['snr_avg'] = pd.to_numeric(df['snr_avg'], errors='coerce')
    snr_col = 'snr_avg'
    print("INFO: Using 'snr_avg' column for all binning and plotting.")

# --- 3. BINNING LOGIC (For Inferential Stats) ---
target_snrs = np.arange(35, -1, -3)

def assign_to_closest_bin(snr_val):
    closest = target_snrs[np.abs(target_snrs - snr_val).argmin()]
    if abs(closest - snr_val) <= 2.0:
        return closest
    return np.nan

df['snr_bin'] = df[snr_col].apply(assign_to_closest_bin)
df_binned = df.dropna(subset=['snr_bin']).copy()

# --- 4. DEFINE ANALYSIS GROUPS ---
analysis_groups = {
    '1_General_Variants': ['cubic', 'westwood', 'veno', 'vegas'],
    '2_Veno_vs_Amended': ['veno', 'amended_veno'],
    '3_All_Variants': ['cubic', 'westwood', 'veno', 'vegas', 'amended_veno']
}

def cohens_d(group1, group2):
    diff = group1.mean() - group2.mean()
    n1, n2 = len(group1), len(group2)
    var1, var2 = group1.var(ddof=1), group2.var(ddof=1)
    pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    if pooled_var == 0: return 0
    return diff / np.sqrt(pooled_var)

# --- 5. LOOP THROUGH EACH GROUP AND GENERATE STATS/GRAPHS ---
for group_name, variants in analysis_groups.items():
    print(f"\nProcessing Group: {group_name}...")
    out_dir = os.path.join('Stats', group_name)
    os.makedirs(out_dir, exist_ok=True)

    df_group = df[df['tcp_variant'].isin(variants)].copy()
    df_binned_group = df_binned[df_binned['tcp_variant'].isin(variants)].copy()

    # -- 5A. Plotting --
    def generate_scatter_lineplot(metric, title, ylabel, filename, log_scale=False):
        plt.figure(figsize=(10, 6))
        sns.lineplot(data=df_group, x='snr_bin', y=metric, hue='tcp_variant',
                     marker='o', markersize=8, linewidth=2.5,
                     errorbar=('ci', 95), err_style='bars', err_kws={'capsize': 4, 'linewidth': 1.5})
        plt.title(title, pad=15, fontweight='bold', fontsize=14)
        plt.xlabel('Signal-to-Noise Ratio (dB)', fontweight='bold', fontsize=12)
        plt.ylabel(ylabel, fontweight='bold', fontsize=12)
        if log_scale: plt.yscale('log')
        plt.xlim(36, -1)
        leg_loc = 'lower left' if metric == 'throughput_mbps' else 'upper left'
        plt.legend(title='TCP Variant', loc=leg_loc, framealpha=1.0, edgecolor='black')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, filename))
        plt.close()

    generate_scatter_lineplot('throughput_mbps', 'Goodput vs. SNR', 'Goodput (Mbps)', 'plot_goodput_vs_snr.png')
    generate_scatter_lineplot('rtt_ms', 'Average RTT vs. SNR', 'Round Trip Time (ms)', 'plot_rtt_vs_snr.png', log_scale=True)
    generate_scatter_lineplot('retransmissions', 'Retransmissions vs. SNR', 'Retransmission Count', 'plot_retransmissions_vs_snr.png')

    # -- 5B. Descriptive Stats --
    desc_stats = df_binned_group.groupby(['snr_bin', 'tcp_variant'])[metrics].agg(['mean', 'std', 'count']).round(2)
    desc_stats.to_csv(os.path.join(out_dir, 'descriptive_statistics_binned.csv'))

    # -- 5C. Inferential Stats (ANOVA & Tukey) --
    anova_summary = []
    tukey_summary = []

    for metric in metrics:
        snr_levels = sorted(df_binned_group['snr_bin'].unique(), reverse=True)
        for snr in snr_levels:
            data_subset = df_binned_group[df_binned_group['snr_bin'] == snr]
            vs = data_subset['tcp_variant'].unique()

            if len(vs) > 1:
                groups = [data_subset[data_subset['tcp_variant'] == v][metric].dropna().values for v in vs]

                if all(len(g) > 1 for g in groups):
                    f_stat, p_val = stats.f_oneway(*groups)
                    is_sig = p_val < 0.05

                    anova_summary.append({
                        'Metric': metric, 'SNR_Bin_dB': snr,
                        'F_Statistic': round(f_stat, 3), 'P_Value': round(p_val, 4),
                        'Significant': 'Yes' if is_sig else 'No'
                    })

                    if is_sig:
                        tukey = pairwise_tukeyhsd(endog=data_subset[metric], groups=data_subset['tcp_variant'], alpha=0.05)
                        tukey_df = pd.DataFrame(data=tukey._results_table.data[1:], columns=tukey._results_table.data[0])
                        sig_pairs = tukey_df[tukey_df['reject'] == True]

                        for _, row in sig_pairs.iterrows():
                            v1, v2 = row['group1'], row['group2']
                            g1_data = data_subset[data_subset['tcp_variant'] == v1][metric]
                            g2_data = data_subset[data_subset['tcp_variant'] == v2][metric]
                            d_val = abs(cohens_d(g1_data, g2_data))

                            tukey_summary.append({
                                'Metric': metric, 'SNR_Bin_dB': snr,
                                'Variant_1': v1, 'Variant_2': v2,
                                'Mean_Difference': round(row['meandiff'], 3),
                                'P_Value_Adj': round(row['p-adj'], 4), 'Cohens_d': round(d_val, 2)
                            })

    pd.DataFrame(anova_summary).to_csv(os.path.join(out_dir, 'FYP_ANOVA_Table.csv'), index=False)
    pd.DataFrame(tukey_summary).to_csv(os.path.join(out_dir, 'FYP_Tukey_EffectSize_Table.csv'), index=False)

    # =========================================================
    # --- 5D. ASSUMPTION CHECKS ---
    # =========================================================

    # -- Shapiro-Wilk Normality Test --
    # Pooled per variant across all SNR bins for meaningful n (n=5 per bin is too small).
    print(f"\n{'='*60}")
    print(f"ASSUMPTION CHECKS — {group_name}")
    print(f"{'='*60}")
    print("\n[Shapiro-Wilk Normality Test]")
    print("(Per variant, pooled across all SNR bins — larger n improves test power)")
    print(f"{'Metric':<25} {'Variant':<18} {'W':<10} {'p-value':<12} {'Result'}")
    print("-" * 80)

    shapiro_summary = []
    for metric in metrics:
        for variant in sorted(df_binned_group['tcp_variant'].unique()):
            data = df_binned_group[df_binned_group['tcp_variant'] == variant][metric].dropna()
            if len(data) >= 3:
                w_stat, p_sw = stats.shapiro(data)
                result = "Normal (p>0.05)" if p_sw > 0.05 else "Non-normal (p<=0.05)"
                print(f"{metric:<25} {variant:<18} {w_stat:<10.4f} {p_sw:<12.4f} {result}")
                shapiro_summary.append({
                    'Metric': metric, 'Variant': variant,
                    'W_Statistic': round(w_stat, 4), 'P_Value': round(p_sw, 4),
                    'Normal': 'Yes' if p_sw > 0.05 else 'No',
                    'Note': 'Pooled across all SNR bins'
                })

    pd.DataFrame(shapiro_summary).to_csv(os.path.join(out_dir, 'shapiro_wilk_normality.csv'), index=False)
    print(f" -> Saved: shapiro_wilk_normality.csv")

    # -- Levene's Test for Homogeneity of Variance --
    # Per metric, per SNR bin — tests equal variance across TCP variants at each SNR level.
    print("\n[Levene's Test — Homogeneity of Variance]")
    print("(Per metric, per SNR bin — tests equal variance across TCP variants)")
    print(f"{'Metric':<25} {'SNR_Bin':<12} {'W':<10} {'p-value':<12} {'Result'}")
    print("-" * 80)

    levene_summary = []
    for metric in metrics:
        snr_levels = sorted(df_binned_group['snr_bin'].unique(), reverse=True)
        for snr in snr_levels:
            data_subset = df_binned_group[df_binned_group['snr_bin'] == snr]
            groups = [data_subset[data_subset['tcp_variant'] == v][metric].dropna().values
                      for v in data_subset['tcp_variant'].unique()
                      if len(data_subset[data_subset['tcp_variant'] == v]) > 1]
            if len(groups) >= 2:
                l_stat, p_lev = stats.levene(*groups)
                result = "Equal variance (p>0.05)" if p_lev > 0.05 else "Unequal variance (p<=0.05)"
                print(f"{metric:<25} {snr:<12.0f} {l_stat:<10.3f} {p_lev:<12.4f} {result}")
                levene_summary.append({
                    'Metric': metric, 'SNR_Bin_dB': snr,
                    'Levene_W': round(l_stat, 3), 'P_Value': round(p_lev, 4),
                    'Equal_Variance': 'Yes' if p_lev > 0.05 else 'No'
                })

    pd.DataFrame(levene_summary).to_csv(os.path.join(out_dir, 'levene_homogeneity.csv'), index=False)
    print(f" -> Saved: levene_homogeneity.csv")

print("\nAll categories successfully processed")