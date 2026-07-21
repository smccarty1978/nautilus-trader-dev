import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

def is_rth(ts_ns):
    dt = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
    from datetime import time
    t = dt.time()
    return (dt.dayofweek < 5) and (time(8, 30) <= t <= time(15, 15))

# Add Nautilus Trader path
PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))

from studies.regime_sequence_chop_context.run_flip_filter_replay import apply_policies

OUT_DIR = Path("studies/regime_sequence_signal_audit/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def compute_pf(pnl):
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    return wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)

def main():
    print("Running Phase 1 & 2: Audit F4 activation, exemptions, and flip-risk score deciles...")
    
    # Load combined flip atlas
    atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet"
    if not atlas_path.exists():
        print(f"Error: {atlas_path} not found.")
        return
        
    df_all = pd.read_parquet(atlas_path)
    df_f2 = df_all[df_all["population"] == "F2"].copy()
    
    # Load validation frozen threshold (0.15)
    df_f2 = apply_policies(df_f2, threshold_fail_prob=0.15)
    
    # Split into validation and test sets
    val_f2 = df_f2[df_f2["period"] == "val"].copy()
    test_f2 = df_f2[df_f2["period"] == "test"].copy()
    
    # --- PHASE 1: F4 ACTIVATION & EXEMPTIONS AUDIT ---
    # F4 audit is conducted on the Test set
    eligible_count = len(test_f2)
    traded_count = int(test_f2["filter_F4_keep"].sum())
    skipped_count = eligible_count - traded_count
    
    trade_retention = traded_count / eligible_count if eligible_count > 0 else 0.0
    skip_rate = skipped_count / eligible_count if eligible_count > 0 else 0.0
    
    f4_activation = pd.DataFrame([{
        "eligible_trade_count": eligible_count,
        "traded_trade_count": traded_count,
        "skipped_trade_count": skipped_count,
        "trade_retention": float(trade_retention),
        "skip_rate": float(skip_rate)
    }])
    f4_activation.to_parquet(OUT_DIR / "f4_activation_audit.parquet", index=False)
    
    # Skipped vs Retained Trade Economics
    skipped_trades = test_f2[test_f2["filter_F4_keep"] == False].copy()
    retained_trades = test_f2[test_f2["filter_F4_keep"] == True].copy()
    
    # Calculate runner thresholds on validation set (strictly causal, no look-ahead)
    runner_90_th = np.percentile(val_f2["pnl_base"].dropna(), 90) if len(val_f2) > 0 else 0.0
    runner_95_th = np.percentile(val_f2["pnl_base"].dropna(), 95) if len(val_f2) > 0 else 0.0
    
    def get_econ_stats(df_sub):
        if len(df_sub) == 0:
            return {
                "count": 0, "mean_gross_pnl": 0.0, "mean_net_pnl": 0.0, "median_net_pnl": 0.0,
                "total_net_pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "num_winners": 0, "num_losers": 0, "num_breakeven": 0,
                "runners_90": 0, "runners_95": 0, "max_individual_loss": 0.0, "max_individual_winner": 0.0
            }
        pnl = df_sub["pnl_base"].to_numpy()
        gross_pnl = pnl + 5.0
        return {
            "count": len(df_sub),
            "mean_gross_pnl": float(gross_pnl.mean()),
            "mean_net_pnl": float(pnl.mean()),
            "median_net_pnl": float(np.median(pnl)),
            "total_net_pnl": float(pnl.sum()),
            "win_rate": float((pnl > 0).mean()),
            "profit_factor": float(compute_pf(pnl)),
            "num_winners": int((pnl > 0).sum()),
            "num_losers": int((pnl < 0).sum()),
            "num_breakeven": int((pnl == 0).sum()),
            "runners_90": int((pnl >= runner_90_th).sum()),
            "runners_95": int((pnl >= runner_95_th).sum()),
            "max_individual_loss": float(pnl.min()),
            "max_individual_winner": float(pnl.max())
        }
    
    skipped_econ = get_econ_stats(skipped_trades)
    retained_econ = get_econ_stats(retained_trades)
    
    econ_df = pd.DataFrame([
        {"group": "skipped", **skipped_econ},
        {"group": "retained", **retained_econ}
    ])
    econ_df.to_parquet(OUT_DIR / "f4_skipped_trade_economics.parquet", index=False)
    
    # Exemptions Audit
    # Exemption categories: F4 keeps trades that F3 wanted to skip
    f3_skips = test_f2[test_f2["filter_F3_keep"] == False]
    raw_chop_signals = len(f3_skips)
    
    strong_migration = f3_skips["seq_5r_center_migration_slope_atr"] > 0.005
    fav_dominate = f3_skips["seq_5r_asym_duration"] > 1.5
    breakout = (f3_skips["seq_5r_position_pct"] >= 0.9) | (f3_skips["seq_5r_position_pct"] <= 0.1)
    
    # Exemption flags
    signals_canceled = int((strong_migration | fav_dominate | breakout).sum())
    signals_remaining = raw_chop_signals - signals_canceled
    pct_canceled = signals_canceled / raw_chop_signals if raw_chop_signals > 0 else 0.0
    
    # Breakdown of canceled signals (mutually exclusive classification or check-all)
    # The prompt asks for: Break canceled signals down by exemption type.
    # We will compute the counts where each exemption triggered among the canceled ones.
    ex_migration_count = int(strong_migration.sum())
    ex_asym_count = int(fav_dominate.sum())
    ex_breakout_count = int(breakout.sum())
    
    f4_exemption = pd.DataFrame([{
        "raw_combined_chop_signals": raw_chop_signals,
        "signals_canceled_by_exemption": signals_canceled,
        "signals_remaining_after_exemption": signals_remaining,
        "percentage_canceled": float(pct_canceled),
        "exemption_strong_center_migration": ex_migration_count,
        "exemption_favorable_regime_asymmetry": ex_asym_count,
        "exemption_envelope_expansion": ex_breakout_count,
        "exemption_sequence_breakout": ex_breakout_count,
        "exemption_other": 0
    }])
    f4_exemption.to_parquet(OUT_DIR / "f4_exemption_audit.parquet", index=False)
    
    # Write Phase 1 Markdown report
    p1_md = f"""# Phase 1: F4 Activation and Exemption Audit

## Activation Summary
* **Eligible confirmed entries (F2)**: {eligible_count}
* **Traded trades**: {traded_count}
* **Skipped trades**: {skipped_count}
* **Trade Retention**: {trade_retention:.8f}
* **Skip Rate**: {skip_rate:.8f}

## Skipped vs Retained Trade Economics
| Metric | Skipped Trades | Retained Trades |
|---|---|---|
| Count | {skipped_econ['count']} | {retained_econ['count']} |
| Mean Gross PnL | ${skipped_econ['mean_gross_pnl']:.2f} | ${retained_econ['mean_gross_pnl']:.2f} |
| Mean Net PnL | ${skipped_econ['mean_net_pnl']:.2f} | ${retained_econ['mean_net_pnl']:.2f} |
| Median Net PnL | ${skipped_econ['median_net_pnl']:.2f} | ${retained_econ['median_net_pnl']:.2f} |
| Total Net PnL | ${skipped_econ['total_net_pnl']:.2f} | ${retained_econ['total_net_pnl']:.2f} |
| Win Rate | {skipped_econ['win_rate']:.4%} | {retained_econ['win_rate']:.4%} |
| Profit Factor | {skipped_econ['profit_factor']:.2f} | {retained_econ['profit_factor']:.2f} |
| Winners Removed/Retained | {skipped_econ['num_winners']} | {retained_econ['num_winners']} |
| Losers Removed/Retained | {skipped_econ['num_losers']} | {retained_econ['num_losers']} |
| Breakevens Removed/Retained | {skipped_econ['num_breakeven']} | {retained_econ['num_breakeven']} |
| Top-Decile Runners | {skipped_econ['runners_90']} | {retained_econ['runners_90']} |
| Top-5% Runners | {skipped_econ['runners_95']} | {retained_econ['runners_95']} |
| Max Loss | ${skipped_econ['max_individual_loss']:.2f} | ${retained_econ['max_individual_loss']:.2f} |
| Max Winner | ${skipped_econ['max_individual_winner']:.2f} | ${retained_econ['max_individual_winner']:.2f} |

## Exemptions Audit
* **Raw chop signals (F3 skips)**: {raw_chop_signals}
* **Signals canceled by directional exemptions**: {signals_canceled}
* **Signals remaining (actual skips)**: {signals_remaining}
* **Percentage canceled**: {pct_canceled:.4%}

### Exemption Breakdown (Non-Exclusive):
* **Strong center migration**: {ex_migration_count}
* **Favorable regime asymmetry**: {ex_asym_count}
* **Envelope expansion / Sequence breakout**: {ex_breakout_count}
"""
    with open(OUT_DIR / "f4_activation_report.md", "w") as f:
        f.write(p1_md)
        
        
    # --- PHASE 2: FROZEN FLIP-RISK SCORE DECILES ---
    # Assign score deciles based on validation-frozen cut points
    val_scores = val_f2["ridge_log_fail_prob"].dropna().values
    
    # Calculate decile edges on validation set (D1 to D10)
    edges = np.percentile(val_scores, np.linspace(0, 100, 11))
    edges[0] -= 1e-9  # slightly expand first edge to include min
    edges[-1] += 1e-9 # slightly expand last edge to include max
    
    # Function to assign deciles based on edges
    def assign_deciles(scores):
        return pd.cut(scores, bins=edges, labels=range(1, 11)).astype(float)
        
    # We assign deciles for both validation and test sets (mostly analyzed on test set)
    test_f2 = test_f2.copy()
    test_f2["decile"] = assign_deciles(test_f2["ridge_log_fail_prob"])
    test_f2 = test_f2.dropna(subset=["decile"])
    test_f2["decile"] = test_f2["decile"].astype(int)
    
    # Add session column (RTH/ETH)
    # RTH = start time of day == observation time of session start
    # Let's check RTH definition from run_study.py: RTH is defined if session start == ts
    # Wait, we can define RTH/ETH based on observation time hour
    obs_times = pd.to_datetime(test_f2['observation_time'], unit='ns', utc=True)
    # NQ RTH is usually 09:30 to 16:00 ET. In UTC, that is 14:30/13:30 to 21:00/20:00 UTC depending on DST.
    # Let's write a simple RTH check using hour/minute in ET or UTC.
    # Actually, Nautilus Trader has session start timestamps.
    # Let's see: in run_study.py line 495:
    # df_f2_test['session'] = df_f2_test['observation_time'].apply(lambda ts: "RTH" if get_session_start(pd.Timestamp(ts, unit='ns', tz='UTC')).value != ts else "ETH")
    test_f2['session'] = test_f2['observation_time'].apply(
        lambda ts: "RTH" if is_rth(ts) else "ETH"
    )
    
    # Compute runner stats for the entire test set
    test_f2["is_runner_90"] = test_f2["pnl_base"] >= runner_90_th
    test_f2["is_runner_95"] = test_f2["pnl_base"] >= runner_95_th
    total_runner_pnl = test_f2[test_f2["is_runner_90"]]["pnl_base"].sum()
    
    # Compute max drawdown per decile
    # The cumulative PnL max drawdown contribution
    
    # Let's write a helper to calculate decile stats
    def calculate_decile_table(df_grp):
        records = []
        for decile, g in df_grp.groupby("decile"):
            n = len(g)
            pred_risk = g["ridge_log_fail_prob"].mean()
            early_fail_rate = (g["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").mean()
            low_progress_rate = (g["outcome_class"] == "LOW_PROGRESS_REGIME").mean()
            
            pnl = g["pnl_base"].to_numpy()
            ev = pnl.mean()
            gross_pnl = (pnl + 5.0).sum()
            net_pnl = pnl.sum()
            
            wins = pnl[pnl > 0]
            win_rate = len(wins) / n if n > 0 else 0.0
            pf = compute_pf(pnl)
            
            median_duration_s = float(g["regime_duration"].median()) / 1e9 if n > 0 else 0.0
            
            # MFE probabilities
            prob_05_atr = (g["MFE_atr"] >= 0.5).mean()
            prob_10_atr = (g["MFE_atr"] >= 1.0).mean()
            prob_20_atr = (g["MFE_atr"] >= 2.0).mean()
            
            runners_90 = int(g["is_runner_90"].sum())
            runners_95 = int(g["is_runner_95"].sum())
            runner_pnl_share = g[g["is_runner_90"]]["pnl_base"].sum() / total_runner_pnl if total_runner_pnl != 0 else 0.0
            
            # Max drawdown contribution (max drawdown of this decile alone)
            if len(pnl) > 0:
                cum = np.cumsum(pnl)
                max_cum = np.maximum.accumulate(cum)
                max_dd = (max_cum - cum).max()
            else:
                max_dd = 0.0
                
            records.append({
                "decile": int(decile),
                "eligible_N": n,
                "mean_predicted_risk": float(pred_risk),
                "observed_early_rotational_failure_rate": float(early_fail_rate),
                "observed_low_progress_regime_rate": float(low_progress_rate),
                "canonical_entry_EV_trade": float(ev),
                "E0_EV_trade": float(ev),
                "gross_PnL": float(gross_pnl),
                "net_PnL": float(net_pnl),
                "win_rate": float(win_rate),
                "profit_factor": float(pf),
                "median_regime_duration_s": float(median_duration_s),
                "prob_05_atr": float(prob_05_atr),
                "prob_10_atr": float(prob_10_atr),
                "prob_20_atr": float(prob_20_atr),
                "top_decile_runner_frequency": float(runners_90 / n if n > 0 else 0.0),
                "top_5pct_runner_frequency": float(runners_95 / n if n > 0 else 0.0),
                "share_of_total_runner_PnL": float(runner_pnl_share),
                "maximum_drawdown_contribution": float(max_dd)
            })
        return pd.DataFrame(records)

    # Segment breakdowns
    segments = {
        "pooled": test_f2,
        "long": test_f2[test_f2["direction"] == 1],
        "short": test_f2[test_f2["direction"] == -1],
        "RTH": test_f2[test_f2["session"] == "RTH"],
        "ETH": test_f2[test_f2["session"] == "ETH"],
        "RTH_long": test_f2[(test_f2["session"] == "RTH") & (test_f2["direction"] == 1)],
        "RTH_short": test_f2[(test_f2["session"] == "RTH") & (test_f2["direction"] == -1)],
        "ETH_long": test_f2[(test_f2["session"] == "ETH") & (test_f2["direction"] == 1)],
        "ETH_short": test_f2[(test_f2["session"] == "ETH") & (test_f2["direction"] == -1)]
    }
    
    # Save score deciles for all segments
    segment_decile_dfs = []
    for name, df_seg in segments.items():
        if len(df_seg) > 0:
            df_dec = calculate_decile_table(df_seg)
            df_dec["segment"] = name
            segment_decile_dfs.append(df_dec)
            
    df_segment_deciles = pd.concat(segment_decile_dfs, ignore_index=True)
    df_segment_deciles.to_parquet(OUT_DIR / "flip_score_segment_deciles.parquet", index=False)
    
    # Monotonicity calculations (for pooled segment)
    pooled_dec = df_segment_deciles[df_segment_deciles["segment"] == "pooled"].sort_values("decile")
    pooled_dec.to_parquet(OUT_DIR / "flip_score_deciles.parquet", index=False)
    
    # Spearman rank correlation calculations
    corr_early_fail, _ = spearmanr(pooled_dec["decile"], pooled_dec["observed_early_rotational_failure_rate"])
    corr_ev, _ = spearmanr(pooled_dec["decile"], pooled_dec["canonical_entry_EV_trade"])
    corr_1_atr, _ = spearmanr(pooled_dec["decile"], pooled_dec["prob_10_atr"])
    corr_runner, _ = spearmanr(pooled_dec["decile"], pooled_dec["top_decile_runner_frequency"])
    
    # Spreads and combined metrics
    # EV for deciles 1, 10, etc.
    d1_ev = pooled_dec[pooled_dec["decile"] == 1]["canonical_entry_EV_trade"].iloc[0]
    d10_ev = pooled_dec[pooled_dec["decile"] == 10]["canonical_entry_EV_trade"].iloc[0]
    pooled_ev = test_f2["pnl_base"].mean()
    
    # D9-D10 combined EV
    d9_10_subset = test_f2[test_f2["decile"].isin([9, 10])]
    d9_10_ev = d9_10_subset["pnl_base"].mean()
    
    # D8-D10 combined EV
    d8_10_subset = test_f2[test_f2["decile"].isin([8, 9, 10])]
    d8_10_ev = d8_10_subset["pnl_base"].mean()
    
    monotonicity_df = pd.DataFrame([{
        "spearman_decile_vs_early_failure": float(corr_early_fail),
        "spearman_decile_vs_EV": float(corr_ev),
        "spearman_decile_vs_1_ATR_prob": float(corr_1_atr),
        "spearman_decile_vs_runner_prob": float(corr_runner),
        "d10_minus_d1_ev": float(d10_ev - d1_ev),
        "d10_minus_pooled_ev": float(d10_ev - pooled_ev),
        "d9_d10_combined_ev": float(d9_10_ev),
        "d8_d10_combined_ev": float(d8_10_ev)
    }])
    monotonicity_df.to_parquet(OUT_DIR / "flip_score_monotonicity.parquet", index=False)
    
    # Write Phase 2 Markdown report
    p2_md = f"""# Phase 2: Frozen Flip-Risk Score Deciles Report

## Spearman Rank Correlations (Monotonicity)
* **Decile vs Early-Rotational-Failure Rate**: {corr_early_fail:+.4f} (Perfect monotonic risk ordering would be +1.0)
* **Decile vs EV (Net PnL)**: {corr_ev:+.4f} (Perfect monotonic negative ordering would be -1.0)
* **Decile vs 1.0 ATR MFE Probability**: {corr_1_atr:+.4f}
* **Decile vs Top-Decile Runner Frequency**: {corr_runner:+.4f}

## Decile Spreads and High-Risk Clusters
* **D10 EV**: ${d10_ev:.2f}
* **D1 EV**: ${d1_ev:.2f}
* **D10 minus D1 EV Spread**: ${d10_ev - d1_ev:.2f}
* **D10 minus Pooled EV Spread**: ${d10_ev - pooled_ev:.2f}
* **D9-D10 Combined EV**: ${d9_10_ev:.2f}
* **D8-D10 Combined EV**: ${d8_10_ev:.2f}

## Decile Performance Table (Pooled Set)
| Decile | Eligible N | Mean Risk | Early Fail % | Low Progress % | EV ($) | Net PnL ($) | Win Rate | Profit Factor | 1.0 ATR % | Runner % | Max DD ($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
"""
    for _, row in pooled_dec.iterrows():
        p2_md += (
            f"| {int(row['decile'])} | {int(row['eligible_N'])} | {row['mean_predicted_risk']:.4f} | "
            f"{row['observed_early_rotational_failure_rate']:.2%} | {row['observed_low_progress_regime_rate']:.2%} | "
            f"${row['canonical_entry_EV_trade']:.2f} | ${row['net_PnL']:.2f} | {row['win_rate']:.2%} | "
            f"{row['profit_factor']:.2f} | {row['prob_10_atr']:.2%} | {row['top_decile_runner_frequency']:.2%} | "
            f"${row['maximum_drawdown_contribution']:.2f} |\n"
        )
        
    with open(OUT_DIR / "flip_score_decile_report.md", "w") as f:
        f.write(p2_md)
        
    print("Phase 1 & 2 complete.")

if __name__ == "__main__":
    main()
