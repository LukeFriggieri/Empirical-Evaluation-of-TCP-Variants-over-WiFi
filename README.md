# Empirical Evaluation of TCP Congestion Control Variants and a Loadable Kernel Module Amendment to TCP Veno over a Calibrated RF-Impaired Wi-Fi Link

Reproducibility repository for the accompanying paper. Contains raw data, processed statistical results, kernel module source, and analysis scripts.

## Structure
data/
├── raw/
│ ├── tcp_results_cleaned_final.csv # Baseline measurements (CUBIC, Westwood, Veno, Vegas)
│ └── tcp_results_veno_ab_rttguard.csv # Validation measurements (Legacy Veno, Adaptive Beta, RTT Growth Guard)
└── processed/
├── Baseline_Results/ # Stats + plots for the four baseline variants (Section IV)
└── AdaptiveBeta&RTTGrowthGuard/ # Stats + plots for the kernel module validation (Section V)
├── A_AdaptiveBeta_vs_RTTGrowthGuard/
├── B_Veno_Variants_3way/
└── C_All_Variants/

scripts/
├── fyp_FINAL_CLEAN.py # Main analysis pipeline
└── stats.py # Statistical tests (ANOVA, Tukey HSD, Cohen's d, Shapiro-Wilk, Levene's)

kernel_module/
├── tcp_veno_adaptiveBeta.c # Adaptive Beta threshold amendment
├── tcp_veno_rttGrowthGuard.c # RTT Growth Guard amendment
└── MakeFile


## Data

**Raw**: 55-second `iperf3` downstream runs (5 repetitions per variant per SNR bin), swept from 35 dB to 5 dB SNR on a VNA-calibrated, RF-isolated 802.11g ad-hoc testbed.

**Processed**: descriptive statistics, one-way ANOVA, Tukey HSD, Cohen's d, Shapiro-Wilk, and Levene's test outputs, plus the corresponding goodput/RTT/retransmission plots, split by comparison:
- `Baseline_Results/` — CUBIC vs. Westwood vs. Veno vs. Vegas
- `AdaptiveBeta&RTTGrowthGuard/A_AdaptiveBeta_vs_RTTGrowthGuard/` — the two amendments compared directly
- `B_Veno_Variants_3way/` — Legacy Veno vs. Adaptive Beta vs. RTT Growth Guard
- `C_All_Variants/` — full cross-variant comparison

## Kernel module

`tcp_veno_adaptiveBeta.c` and `tcp_veno_rttGrowthGuard.c` implement the two amendments as loadable kernel modules (LKMs), registered as selectable congestion-control identifiers alongside the unmodified in-tree TCP Veno. Build with the included `MakeFile`; load via `insmod` and select via `sysctl net.ipv4.tcp_congestion_control`.

## Reproducing the analysis

Requires Python 3.x with `pandas`, `scipy`, `statsmodels`, and a plotting library (`matplotlib`/`plotly`). Run `scripts/fyp_FINAL_CLEAN.py` or `scripts/stats.py` against the corresponding CSV in `data/raw/` to regenerate the tables and figures in `data/processed/`.

## Citation

If referencing this repository, cite the paper: *[full citation once published]*.