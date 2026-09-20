import sys
sys.path.insert(0, ".")
import json
from pathlib import Path
import pandas as pd
import numpy as np

REPO_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
STUDY_DIR = REPO_ROOT / "studies/index_pullback_portability_and_trend_mirror"
BRANCH_A_DIR = STUDY_DIR / "branch_a_leaf4_portability"
BRANCH_B_DIR = STUDY_DIR / "branch_b_trend_mirror"

# Load artifacts
with open(BRANCH_A_DIR / "leaf4_nq_reproduction.json") as f:
    nq_repro = json.load(f)
with open(BRANCH_A_DIR / "leaf4_es_results.json") as f:
    es_results = json.load(f)
with open(BRANCH_A_DIR / "leaf4_ym_results.json") as f:
    ym_results = json.load(f)
with open(BRANCH_A_DIR / "leaf4_portfolio_results.json") as f:
    port_results = json.load(f)
with open(BRANCH_A_DIR / "leaf4_overlap_analysis.json") as f:
    overlap = json.load(f)
with open(BRANCH_A_DIR / "leaf4_cross_instrument_correlation.json") as f:
    corr = json.load(f)

with open(BRANCH_B_DIR / "nq_trend_matrix.json") as f:
    trend_matrix = json.load(f)
with open(BRANCH_B_DIR / "trend_entry_parity.json") as f:
    parity = json.load(f)
with open(BRANCH_B_DIR / "trend_cross_instrument_gate.json") as f:
    gate = json.load(f)
with open(BRANCH_B_DIR / "trend_tail_stress.json") as f:
    tail_stress = json.load(f)
with open(BRANCH_B_DIR / "nq_directional_results.json") as f:
    dir_results = json.load(f)

# Write study.yaml
study_yaml_content = """# Governed Study Specification: index_pullback_portability_and_trend_mirror
study_id: index_pullback_portability_and_trend_mirror
date: 2026-09-17
lineage:
  upstream: studies/nq_h050_economic_subpopulation_mining
  branch_a: Leaf 4 cross-instrument portability (NQ -> ES, YM)
  branch_b: H050 trend-following mirror (E0, E1 x R0, R1, R2)
instruments:
  - NQ
  - ES
  - YM
temporal_coverage:
  train: 2023-01-03 to 2024-12-31
  oos_diagnostic: 2025-01-02 to 2025-03-31
governance:
  causal_feature_contracts: STRICT
  no_in_sample_retuning: ENFORCED
  terminal_state: COMPLETED
"""
with open(STUDY_DIR / "study.yaml", "w") as f:
    f.write(study_yaml_content)
print("Saved study.yaml")

# Build Markdown Report
lines = []
lines.append("# Index Pullback Portability & Trend-Following Mirror Study")
lines.append("## Executive Technical Report across NQ, ES, and YM (2023–2025 Q1)")
lines.append("")
lines.append("**Study ID:** `index_pullback_portability_and_trend_mirror`  ")
lines.append("**Date:** 2026-09-17  ")
lines.append("**Lineage:** Downstream of `studies/nq_h050_economic_subpopulation_mining`  ")
lines.append("**Instruments Evaluated:** CME NQ, ES, YM (1-second regularized causal bars)  ")
lines.append("**Temporal Windows:** 2023 Discovery / Baseline | 2024 Untouched Validation | 2025 Q1 Frozen Diagnostic  ")
lines.append("**Status:** COMPLETED  ")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## Executive Summary")
lines.append("")
lines.append("This study conducted a rigorous, two-branch bounded empirical program investigating two core hypotheses:")
lines.append("1. **Branch A (Leaf 4 Portability):** Does the robust, low-frequency `Interpretable_Leaf_4` state discovered on NQ represent a portable equity-index market phenomenon that also operates profitably on ES and YM without instrument-specific retuning?")
lines.append("2. **Branch B (H050 Trend-Following Mirror):** Does inverting the trade premise at the 0.50 ATR pullback—entering *with* the incumbent regime instead of fading it—produce a healthy strategy with ~5–10 trades/day, $\ge 55\%$ win rate, positive reward/risk, and materially lower drawdown?")
lines.append("")
lines.append("### Key Findings:")
lines.append("* **Branch A (Leaf 4 is NQ-Specific, Fails Portability Completely):**")
lines.append("  - On **NQ**, Leaf 4 reproduces with high fidelity: **+0.704A** in 2023, **+0.417A** in 2024 (PF 1.51, Max DD 49.6A), and **+0.097A** in 2025 Q1 at **1.75 trades/day**.")
lines.append("  - On **ES**, the exact same rule suffers catastrophic failure: **-1.669A** in 2023, **-1.666A** in 2024 (PF 0.05, Win Rate 20.1%, Max DD >6,200A).")
lines.append("  - On **YM**, the exact same rule also collapses: **-1.553A** in 2023, **-1.567A** in 2024 (PF 0.06, Win Rate 20.6%, Max DD >5,300A).")
lines.append("  - **Root Cause:** NQ possesses idiosyncratic intraday range dynamics. When NQ pulls back within 1.74A of prior swing extreme in calm volatility, it frequently mean-reverts. On ES and YM, however, 0.50 ATR pullbacks within 1.74A of prior MFE represent early trend continuation impulses that vigorously run over counter-regime fade entries. **Leaf 4 is strictly an NQ-specific artifact and does not transfer to broader index futures.**")
lines.append("")
lines.append("* **Branch B (Raw Trend-Following Continuation Has Negative Net Expectancy):**")
lines.append("  - Across all 6 evaluated cells ($2\\text{ entries} \\times 3\\text{ brackets}$), raw trend-following pullback entries produce **negative net expectancy** in both 2023 and 2024.")
lines.append("  - Immediate continuation (E0) yields **-0.060A to -0.066A** in 2024, with win rates between **43.4% and 50.9%** (far below the 55% target profile).")
lines.append("  - Re-acceleration confirmation (E1) degrades performance further (**-0.064A to -0.083A** in 2024) because waiting for a completed 5s directional bar surrenders favorable entry pricing.")
lines.append("  - While max drawdown is significantly smaller than counter-regime trading (**728A–937A** vs **2,296A** on broad H050), friction (0.75 pts RT) and regime-termination exits (occurring on ~16–17% of trades) completely erode gross continuation gains.")
lines.append("  - **Gate Decision:** The Branch B Cross-Instrument Gate returns **`FAIL`**. Neither ES nor YM trend-following continuation was run, preventing ungrounded search.")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## Master Final Comparison Table")
lines.append("")
lines.append("| Architecture | Instruments | Unique Trades/Day | Net ATR/Trade (2024) | Win Rate (2024) | Avg Win (ATR) | Avg Loss (ATR) | Realized W/L | Profit Factor | Max DD ATR (2024) | Worst Month (2024) | Tail Dependent? |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

# Row 1: NQ Leaf 4
m_nq = nq_repro['reconciled_metrics']['2024']
lines.append(f"| **NQ Leaf 4** | NQ | {m_nq['trades_per_day']:.2f} | **+{m_nq['mean_pnl_atr']:.4f}A** | {m_nq['win_rate']*100:.1f}% | +{m_nq['avg_win']:.2f}A | {m_nq['avg_loss']:.2f}A | {m_nq['win_loss_ratio']:.2f} | {m_nq['profit_factor']:.2f} | **{m_nq['max_dd_atr']:.1f}A** | Oct (-27.7A) | YES (83% top 1%) |")

# Row 2: ES Leaf 4
m_es = es_results['2024']
lines.append(f"| **ES Leaf 4** | ES | {m_es['leaf4_trades_per_day']:.2f} | **{m_es['mean_pnl_atr']:.4f}A** | {m_es['win_rate']*100:.1f}% | +{m_es['avg_win_atr']:.2f}A | {m_es['avg_loss_atr']:.2f}A | {m_es['win_loss_ratio']:.2f} | {m_es['profit_factor']:.2f} | {m_es['max_dd_atr']:.1f}A | {m_es['worst_month']} | NO (Negative) |")

# Row 3: YM Leaf 4
m_ym = ym_results['2024']
lines.append(f"| **YM Leaf 4** | YM | {m_ym['leaf4_trades_per_day']:.2f} | **{m_ym['mean_pnl_atr']:.4f}A** | {m_ym['win_rate']*100:.1f}% | +{m_ym['avg_win_atr']:.2f}A | {m_ym['avg_loss_atr']:.2f}A | {m_ym['win_loss_ratio']:.2f} | {m_ym['profit_factor']:.2f} | {m_ym['max_dd_atr']:.1f}A | {m_ym['worst_month']} | NO (Negative) |")

# Row 4: Leaf 4 Portfolio
m_port = port_results['portfolio_all_signals']
lines.append(f"| **Leaf 4 Portfolio** | NQ+ES+YM | {m_port['trades_per_day']:.2f} | **{m_port['mean_net_atr_per_trade']:.4f}A** | 22.8% | +0.72A | -2.14A | 0.34 | {m_port['profit_factor']:.2f} | {m_port['max_drawdown_atr']:.1f}A | {m_port['worst_month']} | NO (Negative) |")

# Rows 5-10: NQ Trend Mirror Cells
for cell in ['E0_R0', 'E0_R1', 'E0_R2', 'E1_R0', 'E1_R1', 'E1_R2']:
    m_c = trend_matrix['2024'][cell]
    tail_dep = "NO (Negative)" if m_c['mean_pnl_atr'] <= 0 else ("YES" if m_c['top_1pct_pnl_share'] > 0.4 else "NO")
    lines.append(f"| **{cell}** | NQ | {m_c['trades_per_day']:.2f} | **{m_c['mean_pnl_atr']:.4f}A** | {m_c['win_rate']*100:.1f}% | +{m_c['avg_win_atr']:.2f}A | {m_c['avg_loss_atr']:.2f}A | {m_c['realized_win_loss_ratio']:.2f} | {m_c['profit_factor']:.2f} | {m_c['max_dd_atr']:.1f}A | {m_c['worst_month']} | {tail_dep} |")

lines.append("| **ES/YM Trend Mirror** | ES, YM | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | **GATE FAILED (Not Run)** |")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## Explicit Answers to Required Questions")
lines.append("")
lines.append("### Branch A: Leaf 4 Portability")
lines.append("")
lines.append("1. **What is the exact Leaf 4 rule?**  ")
lines.append("   - `minutes_from_rth_open <= 380.649994` (RTH execution prior to 14:50:39 CT).  ")
lines.append("   - `realized_range_15m_atr <= 9.344128` (15m rolling high-low range $\le 9.344$ ATR).  ")
lines.append("   - `current_price_from_prior_mfe_atr__tf_1m <= 1.738367` (current price signed distance from prior completed 1m regime MFE $\le 1.738$ ATR).  ")
lines.append("")
lines.append("2. **Which condition contributes most to its economic separation?**  ")
lines.append("   - `current_price_from_prior_mfe_atr__tf_1m <= 1.74` contributes the decisive economic separation. In 2023 discovery, adding Condition 3 to Conditions 1 and 2 lifts mean net PnL from **-0.088A up to +0.704A** (+0.792A lift), directly isolating shallow breakouts from runaway momentum.")
lines.append("")
lines.append("3. **Is the logic economically interpretable?**  ")
lines.append("   - **YES.** It restricts entries to periods where (a) the market is not distorted by late-day MOC imbalances, (b) 15m realized volatility is moderate, and (c) the incumbent regime has not broken out far beyond the prior swing high/low, creating a favorable mean-reverting environment.")
lines.append("")
lines.append("4. **Does NQ reproduce exactly?**  ")
lines.append("   - **YES (PASS).** Reproduced: 2023 OOF = **+0.7040A** ($N=512$), 2024 Validation = **+0.4166A** ($N=451$, PF 1.51, Catastrophic 8.65%, Max DD 49.58A), and 2025 Q1 = **+0.0974A** ($N=102$). All match the mining study.")
lines.append("")
lines.append("5. **Does the same rule work on ES?**  ")
lines.append("   - **NO (NOT_FOUND).** On ES, Leaf 4 yields **-1.669A (2023)** and **-1.666A (2024)** with a 20.1% win rate and Profit Factor of 0.05. Max drawdown exceeds **6,200 ATR**.")
lines.append("")
lines.append("6. **YM?**  ")
lines.append("   - **NO (NOT_FOUND).** On YM, Leaf 4 yields **-1.553A (2023)** and **-1.567A (2024)** with a 20.6% win rate and Profit Factor of 0.06. Max drawdown exceeds **5,300 ATR**.")
lines.append("")
lines.append("7. **How correlated are the signals?**  ")
lines.append("   - When signals overlap within a 5-minute window, directional agreement is **96.8%**. Daily PnL correlations between ES and YM are high ($r = +0.68$), while NQ displays negative correlation ($r = -0.32$ to $-0.35$) because NQ's edge is positive while ES/YM are heavily negative.")
lines.append("")
lines.append("8. **How many genuinely unique trades/day does the portfolio provide?**  ")
lines.append("   - Total raw signals across NQ, ES, and YM average **30.49 signals/day**. Clustering into 5-minute unique opportunity windows yields **16.08 unique clusters/day**.")
lines.append("")
lines.append("9. **Does combined DD remain acceptable?**  ")
lines.append("   - **NO (POOR).** Because ES and YM trades lose persistently (-1.6A/trade), combining all three instruments creates an astronomical max drawdown of **26,205 ATR**.")
lines.append("")
lines.append("10. **Is Leaf 4 a portable state or an NQ-specific anomaly?**  ")
lines.append("    - **NQ-SPECIFIC.** The structural threshold combination does not describe an invariant index-futures market state. It is an artifact of NQ's specific volatility and mean-reversion profile.")
lines.append("")
lines.append("---")
lines.append("")
lines.append("### Branch B: H050 Trend-Following Mirror")
lines.append("")
lines.append("11. **Is immediate H050 continuation profitable?**  ")
lines.append("    - **NO.** Immediate continuation (E0) prints **-0.060A to -0.066A net** across all brackets in 2024 (and -0.080A to -0.090A in 2023).")
lines.append("")
lines.append("12. **Does re-acceleration improve WR enough to justify worse entry price?**  ")
lines.append("    - **NO.** Re-acceleration (E1) win rate is actually 0.1% to 1.2% *lower* than E0 (49.7% vs 50.9% in R0; 42.3% vs 43.4% in R1), while net PnL worsens from -0.065A to **-0.081A**. Waiting for a completed 5s directional bar degrades entry price without filtering false continuations.")
lines.append("")
lines.append("13. **Which fixed bracket has the healthiest distribution?**  ")
lines.append("    - **R2 (1.00 SL / 1.25 PT)** has the least negative expectancy (-0.0600A in E0_R2) and the highest realized W/L ratio (1.14), but remains net negative after costs.")
lines.append("")
lines.append("14. **Does any policy naturally reach ~55% WR?**  ")
lines.append("    - **NO.** Realized win rates range from **42.3% to 50.9%** across all cells.")
lines.append("")
lines.append("15. **Does realized W/L remain >= 1?**  ")
lines.append("    - For R0 (symmetric), realized W/L is **0.81** (compressed below 1.0 by friction and regime exits).  ")
lines.append("    - For R1, realized W/L is **1.12** (below nominal 1.33).  ")
lines.append("    - For R2, realized W/L is **1.14** (below nominal 1.25).")
lines.append("")
lines.append("16. **Does any policy exceed +0.15A?**  ")
lines.append("    - **NO.** No policy is positive net.")
lines.append("")
lines.append("17. **+0.20A?**  ")
lines.append("    - **NO.**")
lines.append("")
lines.append("18. **+0.30A?**  ")
lines.append("    - **NO.**")
lines.append("")
lines.append("19. **How much smaller is DD than the reversal lineage?**  ")
lines.append("    - Drawdown is **60% to 68% smaller**: Max DD on E0_R2 is **728.6 ATR**, compared to **2,296.5 ATR** on the broad counter-regime H050 baseline.")
lines.append("")
lines.append("20. **Are profits broad or month-concentrated?**  ")
lines.append("    - There are no profits; losses are steady and widespread across months. In E0_R1, 9 out of 12 months in 2024 are negative.")
lines.append("")
lines.append("21. **Does trend-follow LONG work?**  ")
lines.append("    - In pooled 2023–2024, Trend-Follow LONG in E0_R0 produces **-0.0385A net** (42.0 trades/day, 52.6% WR, PF 0.94). It loses less than SHORT, but remains negative.")
lines.append("")
lines.append("22. **Does trend-follow SHORT work?**  ")
lines.append("    - Trend-Follow SHORT produces **-0.1064A net** (41.6 trades/day, 47.9% WR, PF 0.77). Trend-following in bear regimes suffers severe chop and rapid re-exhaustion.")
lines.append("")
lines.append("23. **Are both directions required?**  ")
lines.append("    - Neither direction has positive raw expectancy without conditioning.")
lines.append("")
lines.append("24. **Does the NQ result qualify for ES/YM portability testing?**  ")
lines.append("    - **NO (GATE FAILED).** Since no NQ cell achieved positive expectancy in 2023 and 2024, B20 mandates stopping before ES/YM.")
lines.append("")
lines.append("25. **Does a multi-index portfolio reach 5–10 unique trades/day?**  ")
lines.append("    - On raw frequency it easily exceeds 15+ trades/day, but the underlying trade has negative expectancy.")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## Formal Verdicts")
lines.append("")
lines.append("```yaml")
lines.append("LEAF4_CONTRACT_RECONSTRUCTED: PASS")
lines.append("LEAF4_NQ_REPRODUCTION: PASS")
lines.append("LEAF4_ES_PORTABILITY: NOT_FOUND")
lines.append("LEAF4_YM_PORTABILITY: NOT_FOUND")
lines.append("LEAF4_CROSS_INSTRUMENT_STATE: NQ_SPECIFIC")
lines.append("LEAF4_PORTFOLIO_TARGET_FREQUENCY: ACHIEVED")
lines.append("H050_TREND_CONTINUATION_EDGE: NOT_FOUND")
lines.append("REACCELERATION_ADDS_VALUE: NO")
lines.append("HIGH_WIN_PROFILE: NOT_FOUND")
lines.append("POSITIVE_RR_PROFILE: NOT_FOUND")
lines.append("LOW_DRAWDOWN_PROFILE: FOUND")
lines.append("TREND_MIRROR_CROSS_INSTRUMENT_GATE: FAIL")
lines.append("MULTI_INDEX_5_TO_10_TRADES_DAY: ACHIEVED")
lines.append("BEST_RESEARCH_PATH: NEITHER")
lines.append("```")
lines.append("")
lines.append("### Final Strategic Recommendation:")
lines.append("1. **Do not deploy or trade Leaf 4 on ES or YM.** The edge is non-existent outside NQ.")
lines.append("2. **Do not deploy unconditioned H050 trend-following continuation.** A simple pullback into the incumbent trend is insufficient to overcome exchange friction and regime transition exits without secondary state conditioning.")
lines.append("3. **Terminate both lineages.** Neither Branch A nor Branch B warrants production NautilusTrader event-driven backtesting.")

report_path = STUDY_DIR / "INDEX_PULLBACK_PORTABILITY_AND_TREND_MIRROR_REPORT.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Saved {report_path}")
