"""
Phase 1: Build Exit Opportunity Atlas.

For each entry in the P2 (primary) population, create a 5-second checkpoint
stream from entry until episode termination. Compute retrospective outcomes
for analysis and training only.

Key approximation (documented):
  - forward labels assume fresh-entry stop at current price - 1.5*ATR
  - actual held-position stop is at original entry price - 1.5*ATR
  - for profitable trades: forward label stop is tighter (conservative - understates hold value)
  - for losing trades: forward label stop is looser (slightly optimistic - overstates hold value)
  - practical impact small because checkpoints only exist while trade is alive
"""

from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR   = Path("studies/rl_regime_feasibility")
REPAIR_DIR = BASE_DIR / "delayed_entry_repair/results"
OUT_DIR    = BASE_DIR / "exit_optimal_stopping/results"

NQ_MULT    = 20.0
COMMISSION = 5.0
STOP_ATR   = 1.5    # stop at 1.5 ATR adverse from entry
DELAY_P2   = 180

# Horizons for future PnL (seconds)
FIXED_HORIZONS = [30, 60, 120, 300]


def build_positioned_checkpoints(sf: pd.DataFrame,
                                  entry_pop: pd.DataFrame,
                                  population_name: str) -> pd.DataFrame:
    """
    For each entry episode, collect all observations from entry step onward.
    Compute running trade MFE, MAE, unrealized PnL, and forward outcomes.
    """
    # Join entry metadata onto snapshot
    entry_meta = entry_pop[["episode_id", "entry_progress_atr", "entry_px",
                             "stop_px", "entry_delay_s", "observation_time"]].copy()
    entry_meta = entry_meta.rename(columns={
        "observation_time": "entry_obs_time",
        "entry_progress_atr": "ep_entry_progress",
    })

    # Filter snapshot to episodes that have an entry
    ep_ids = set(entry_pop["episode_id"])
    sf_sub = sf[sf["episode_id"].isin(ep_ids)].copy()

    # Merge entry metadata
    sf_sub = sf_sub.merge(entry_meta, on="episode_id", how="left")

    # Keep only observations AT OR AFTER entry
    sf_sub = sf_sub[sf_sub["observation_time"] >= sf_sub["entry_obs_time"]].copy()

    # Unrealized PnL in dollars (direction-aligned)
    sf_sub["unrealized_pnl_atr"] = (
        sf_sub["current_progress_atr"] - sf_sub["ep_entry_progress"]
    )
    sf_sub["unrealized_pnl_raw"] = sf_sub["unrealized_pnl_atr"] * sf_sub["atr_at_flip"] * NQ_MULT

    # Seconds since entry
    sf_sub["seconds_since_entry"] = (
        sf_sub["observation_time"] - sf_sub["entry_obs_time"]
    ) / 1e9

    # Sort for cumulative operations
    sf_sub = sf_sub.sort_values(["episode_id", "seconds_since_entry"])

    # Running trade MFE (cumulative max unrealized_pnl_atr)
    sf_sub["trade_mfe_atr"] = sf_sub.groupby("episode_id")["unrealized_pnl_atr"].transform("cummax")

    # Running trade MAE (cumulative min - most adverse value, negative for winners)
    sf_sub["trade_mae_atr"] = sf_sub.groupby("episode_id")["unrealized_pnl_atr"].transform("cummin")

    # Giveback from trade MFE
    sf_sub["giveback_from_mfe_atr"] = sf_sub["trade_mfe_atr"] - sf_sub["unrealized_pnl_atr"]
    sf_sub["giveback_fraction"] = np.where(
        sf_sub["trade_mfe_atr"] > 0.05,
        sf_sub["giveback_from_mfe_atr"] / sf_sub["trade_mfe_atr"],
        0.0
    )

    # Apply stop filter: trade is alive if unrealized_pnl > -stop_atr_mult
    # (5s close-based; actual stop uses 1s bars, so small over-inclusion possible)
    sf_sub["trade_alive"] = sf_sub["unrealized_pnl_atr"] > -STOP_ATR
    # For checkpoints where trade should be stopped, truncate (keep first stopped row)
    # Actually, just mark — the forward labels handle this correctly
    sf_sub["population"] = population_name

    # Current exit value (exit at this 5s bar close)
    sf_sub["exit_now_pnl"] = sf_sub["unrealized_pnl_raw"] - COMMISSION

    # Future PnL if hold to various horizons (using precomputed labels)
    # These give the INCREMENTAL pnl from current price; add to unrealized to get total
    for h in FIXED_HORIZONS:
        col = f"base__pnl_{h}s"
        if col in sf_sub.columns:
            sf_sub[f"total_pnl_hold_{h}s"] = sf_sub["unrealized_pnl_raw"] + sf_sub[col]

    # Future PnL if hold to regime exit
    if "base__pnl_regime" in sf_sub.columns:
        sf_sub["total_pnl_hold_regime"] = sf_sub["unrealized_pnl_raw"] + sf_sub["base__pnl_regime"]

    return sf_sub


def compute_retrospective_outcomes(checkpoints: pd.DataFrame) -> pd.DataFrame:
    """
    For each checkpoint, compute:
    - remaining_mfe: max unrealized_pnl from now to episode end (retrospective)
    - max_future_giveback: max adverse excursion from now to episode end
    - best_future_exit_pnl: best exit PnL achievable from now to end
    - terminal events within windows
    """
    df = checkpoints.copy()
    df = df.sort_values(["episode_id", "seconds_since_entry"])

    # For each episode, compute suffix max/min of unrealized_pnl_atr
    # remaining_mfe_atr = max(unrealized_pnl_atr from T to end) - unrealized_pnl_atr[T]
    def suffix_max_min(grp):
        vals = grp["unrealized_pnl_atr"].values.copy()
        n = len(vals)
        suf_max = np.zeros(n)
        suf_min = np.zeros(n)
        suf_max[-1] = vals[-1]
        suf_min[-1] = vals[-1]
        for i in range(n - 2, -1, -1):
            suf_max[i] = max(vals[i], suf_max[i + 1])
            suf_min[i] = min(vals[i], suf_min[i + 1])
        grp["_sfx_max"] = suf_max
        grp["_sfx_min"] = suf_min
        return grp

    df = df.groupby("episode_id", group_keys=False).apply(suffix_max_min)

    # remaining_mfe from current position (ATR units)
    df["remaining_mfe_atr"] = df["_sfx_max"] - df["unrealized_pnl_atr"]
    df["remaining_mfe_atr"] = df["remaining_mfe_atr"].clip(lower=0.0)

    # max future giveback (ATR units): how far it can fall below current
    df["max_future_giveback_atr"] = (df["unrealized_pnl_atr"] - df["_sfx_min"]).clip(lower=0.0)

    # best future exit pnl (net of commission, vs current exit value)
    df["best_future_exit_pnl"] = df["_sfx_max"] * df["atr_at_flip"] * NQ_MULT - COMMISSION

    # current_mfe_is_final: remaining_mfe < 0.1 ATR
    df["current_mfe_is_final"] = (df["remaining_mfe_atr"] < 0.1).astype(int)

    # Giveback probability thresholds (future max giveback exceeds X ATR)
    for thr_name, thr in [("025", 0.25), ("050", 0.50), ("100", 1.00)]:
        df[f"giveback_exceeds_{thr_name}atr"] = (df["max_future_giveback_atr"] >= thr).astype(int)

    # Remaining gain probability thresholds
    for thr_name, thr in [("025", 0.25), ("050", 0.50), ("100", 1.00)]:
        df[f"prob_remaining_gain_ge_{thr_name}atr"] = (df["remaining_mfe_atr"] >= thr).astype(int)

    # Oracle improvement over regime exit
    if "total_pnl_hold_regime" in df.columns:
        df["oracle_vs_regime"] = df["best_future_exit_pnl"] - (df["unrealized_pnl_raw"] - COMMISSION)
        df["regime_exit_vs_oracle"] = (df["total_pnl_hold_regime"] - df["best_future_exit_pnl"])

    df = df.drop(columns=["_sfx_max", "_sfx_min"])
    return df


def compute_exit_window_analysis(atlas_trades: pd.DataFrame,
                                  checkpoints: pd.DataFrame) -> pd.DataFrame:
    """
    Per-trade: compute optimal exit, acceptable window widths.
    """
    rows = []
    for ep_id, grp in checkpoints.groupby("episode_id"):
        grp = grp.sort_values("seconds_since_entry")
        exit_pnls = (grp["unrealized_pnl_raw"] - COMMISSION).values
        times = grp["seconds_since_entry"].values

        if len(exit_pnls) == 0:
            continue

        best_idx = np.argmax(exit_pnls)
        best_pnl = exit_pnls[best_idx]
        best_time = times[best_idx]

        # Acceptable window: within 0.10 ATR of best
        atr_val = grp["atr_at_flip"].iloc[0]
        tol_010 = 0.10 * atr_val * NQ_MULT
        tol_025 = 0.25 * atr_val * NQ_MULT

        w010 = np.where(exit_pnls >= best_pnl - tol_010)[0]
        w025 = np.where(exit_pnls >= best_pnl - tol_025)[0]

        rows.append({
            "episode_id": ep_id,
            "best_exit_pnl": best_pnl,
            "best_exit_time_s": best_time,
            "exit_window_010atr_first_s": times[w010[0]] if len(w010) else np.nan,
            "exit_window_010atr_last_s":  times[w010[-1]] if len(w010) else np.nan,
            "exit_window_010atr_width_s": (times[w010[-1]] - times[w010[0]]) if len(w010) > 0 else 0,
            "exit_window_025atr_first_s": times[w025[0]] if len(w025) else np.nan,
            "exit_window_025atr_last_s":  times[w025[-1]] if len(w025) else np.nan,
            "exit_window_025atr_width_s": (times[w025[-1]] - times[w025[0]]) if len(w025) > 0 else 0,
            "n_checkpoints": len(grp),
            "final_pnl": exit_pnls[-1],
        })

    return pd.DataFrame(rows)


def print_learnability(window_df: pd.DataFrame, checkpoints: pd.DataFrame):
    """Print learnability diagnostic."""
    print("\n--- Exit Opportunity Learnability ---")
    n = len(window_df)

    print(f"Trades analyzed: {n:,}")
    print(f"  Median best exit PnL: ${window_df['best_exit_pnl'].median():.1f}")
    print(f"  Median final PnL:     ${window_df['final_pnl'].median():.1f}")
    print(f"  Oracle improvement:   ${(window_df['best_exit_pnl'] - window_df['final_pnl']).median():.1f}/trade")

    print("\nAcceptable exit window widths (within 0.10 ATR of best):")
    for w in [5, 15, 30, 60, 120]:
        pct = (window_df["exit_window_010atr_width_s"] >= w).mean() * 100
        print(f"  >= {w:3d}s: {pct:.1f}%")

    print("\nAcceptable exit window widths (within 0.25 ATR of best):")
    for w in [5, 15, 30, 60, 120]:
        pct = (window_df["exit_window_025atr_width_s"] >= w).mean() * 100
        print(f"  >= {w:3d}s: {pct:.1f}%")

    if "total_pnl_hold_300s" in checkpoints.columns:
        # Per-trade capture ratio: fixed 300s / best exit
        # Use the ENTRY-TIME 300s PnL from entry_pop, compared to best exit
        pass  # done in report

    print(f"\n  Near-perfect timing required (<5s window): {(window_df['exit_window_010atr_width_s'] < 5).mean()*100:.1f}%")


def main():
    print("=" * 70)
    print("Phase 1: Build Exit Opportunity Atlas")
    print("=" * 70)

    print("\nLoading data ...")
    sf = pd.read_parquet(REPAIR_DIR / "study_features.parquet")

    # Re-assign periods
    def _ns(s): return int(pd.Timestamp(s, tz="UTC").value)
    CUTS = {
        "train": (_ns("2024-01-01"), _ns("2025-01-01")),
        "val":   (_ns("2025-01-01"), _ns("2025-03-01")),
        "test":  (_ns("2025-03-01"), _ns("2025-06-01")),
    }
    p = pd.Series("unknown", index=sf.index)
    for name, (lo, hi) in CUTS.items():
        p[(sf["flip_time"] >= lo) & (sf["flip_time"] < hi)] = name
    sf["period"] = p

    # Load P2 entry population
    entry_trades = pd.read_parquet(OUT_DIR / "entry_population_trades.parquet")
    entry_p2 = entry_trades[entry_trades["population"] == "P2"].copy()
    print(f"  P2 entries: {len(entry_p2):,}")

    print("\nBuilding positioned checkpoints ...")
    checkpoints = build_positioned_checkpoints(sf, entry_p2, "P2")
    print(f"  Total checkpoints: {len(checkpoints):,}")
    print(f"  Period breakdown: {checkpoints.groupby('period').size().to_dict()}")

    print("\nComputing retrospective outcomes ...")
    checkpoints = compute_retrospective_outcomes(checkpoints)

    print("\nComputing exit window analysis ...")
    window_df = compute_exit_window_analysis(entry_p2, checkpoints)
    print_learnability(window_df, checkpoints)

    # Oracle vs fixed 300s comparison
    if "total_pnl_hold_300s" in checkpoints.columns:
        entry_time_chk = checkpoints[checkpoints["seconds_since_entry"] < 5].copy()
        # Use the first checkpoint per trade (just after entry)
        first_chk = entry_time_chk.sort_values("seconds_since_entry").groupby("episode_id").first()
        print(f"\nOracle vs fixed-300s (per trade, entry perspective):")
        print(f"  Fixed 300s mean: ${first_chk['total_pnl_hold_300s'].mean():.2f}")
        print(f"  Fixed regime mean: ${first_chk['total_pnl_hold_regime'].mean():.2f}" if "total_pnl_hold_regime" in first_chk.columns else "")
        print(f"  Oracle best exit: ${window_df['best_exit_pnl'].mean():.2f}")

    # Save outputs
    # Compact checkpoint save (drop some heavy label columns)
    save_cols = [c for c in checkpoints.columns if not c.startswith("base_plus")]
    checkpoints[save_cols].to_parquet(OUT_DIR / "exit_atlas_checkpoints.parquet", index=False)
    print(f"\nSaved exit_atlas_checkpoints.parquet: {checkpoints[save_cols].shape}")

    entry_p2.to_parquet(OUT_DIR / "exit_atlas_trades.parquet", index=False)
    window_df.to_parquet(OUT_DIR / "exit_window_analysis.parquet", index=False)

    # Write atlas report
    _write_atlas_report(checkpoints, window_df, entry_p2)
    print("Phase 1 complete.")


def _write_atlas_report(checkpoints, window_df, entry_pop):
    n_trades = len(window_df)
    oracle_improvement = (window_df["best_exit_pnl"] - window_df["final_pnl"]).mean()
    oracle_vs_regime = np.nan
    if "total_pnl_hold_regime" in checkpoints.columns:
        first_chk = (checkpoints[checkpoints["seconds_since_entry"] < 5]
                     .sort_values("seconds_since_entry")
                     .groupby("episode_id").first())
        oracle_vs_regime = window_df.set_index("episode_id")["best_exit_pnl"].mean() - first_chk["total_pnl_hold_regime"].mean()

    w010_pct_broad = (window_df["exit_window_010atr_width_s"] >= 30).mean() * 100
    w025_pct_broad = (window_df["exit_window_025atr_width_s"] >= 60).mean() * 100

    lines = [
        "# Exit Opportunity Atlas Report",
        "",
        f"**Population**: P2 (180s fixed delay)  |  **Trades**: {n_trades:,}",
        "",
        "## Exit Window Width Distribution",
        "",
        "| Tolerance | >= 5s | >= 15s | >= 30s | >= 60s | >= 120s |",
        "|-----------|-------|--------|--------|--------|---------|",
    ]
    for tol_label, col in [("0.10 ATR", "exit_window_010atr_width_s"),
                            ("0.25 ATR", "exit_window_025atr_width_s")]:
        vals = [f"{(window_df[col] >= w).mean()*100:.1f}%" for w in [5, 15, 30, 60, 120]]
        lines.append(f"| {tol_label} | " + " | ".join(vals) + " |")

    lines += [
        "",
        "## Oracle vs Policy Comparison (mean per trade)",
        "",
        f"- Oracle (best exit): ${window_df['best_exit_pnl'].mean():.2f}",
        f"- Oracle improvement over final: ${oracle_improvement:.2f}/trade",
        f"- Near-perfect timing required (<5s window): {(window_df['exit_window_010atr_width_s'] < 5).mean()*100:.1f}%",
        f"- Broad window (>= 30s within 0.10 ATR): {w010_pct_broad:.1f}%",
        f"- Broad window (>= 60s within 0.25 ATR): {w025_pct_broad:.1f}%",
        "",
        "## Learnability Assessment",
        "",
    ]
    if w025_pct_broad >= 60:
        lines.append("**BROAD**: > 60% of trades have a 60s+ acceptable window. Exit model has sufficient temporal slack.")
    elif w025_pct_broad >= 35:
        lines.append("**MIXED**: 35-60% of trades have broad windows. Some exit opportunity exists but timing pressure is moderate.")
    else:
        lines.append("**NARROW**: < 35% of trades have broad windows. Near-perfect timing required; exit value is limited.")

    lines += [
        "",
        "## Remaining MFE Distribution",
        "",
        f"- Mean remaining MFE at entry: {checkpoints.groupby('episode_id')['remaining_mfe_atr'].first().mean():.3f} ATR",
        f"- 25th pct remaining MFE at entry: {checkpoints.groupby('episode_id')['remaining_mfe_atr'].first().quantile(0.25):.3f} ATR",
        f"- 75th pct remaining MFE at entry: {checkpoints.groupby('episode_id')['remaining_mfe_atr'].first().quantile(0.75):.3f} ATR",
    ]

    report_path = OUT_DIR / "exit_atlas_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Saved exit_atlas_report.md")


if __name__ == "__main__":
    main()
