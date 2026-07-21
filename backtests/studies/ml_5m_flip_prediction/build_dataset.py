"""Phase 1 — Build the ML 5m flip prediction dataset (v1).

Input:  studies/1m_delayed_checkpoint_context/results/trades_all.parquet
Output: studies/ml_5m_flip_prediction/results/ml_5m_flip_prediction_dataset.parquet
        studies/ml_5m_flip_prediction/results/ml_5m_flip_dataset_qa.log

See SPEC.md for locked-in design decisions.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

CHECKPOINTS = [0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600]
HORIZONS = [120, 180, 300, 600]
LABEL_GRID_MAX = 600  # collector's max checkpoint

INPUT_PATH = (
    "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
OUT_DIR = Path("studies/ml_5m_flip_prediction/results")
OUT_PARQUET = OUT_DIR / "ml_5m_flip_prediction_dataset.parquet"
OUT_LOG = OUT_DIR / "ml_5m_flip_dataset_qa.log"


# ------------------------------------------------------------------
# Feature / metadata / label definitions
# ------------------------------------------------------------------

# Root-level features (per trade, keep verbatim)
ROOT_FEATURES = [
    # ATR
    "atr_14", "atr_at_signal",
    # Flip bar anatomy
    "flip_range_atr", "flip_body_atr", "flip_body_pct",
    "flip_close_location", "flip_upper_wick_pct", "flip_lower_wick_pct",
    "flip_volume", "flip_vol_vs_20avg", "flip_close_vs_prior_close_atr",
    "flip_high_vs_prior_high_atr", "flip_low_vs_prior_low_atr",
    "flip_bar_bullish_volume_pct", "flip_bar_vol_rank_20",
    # Bar+1 anatomy
    "bar1_range_atr", "bar1_body_atr", "bar1_body_pct",
    "bar1_close_location", "bar1_upper_wick_pct", "bar1_lower_wick_pct",
    "bar1_volume", "bar1_vol_vs_flip_vol", "bar1_vol_rank_20",
    "bar1_hh_amount_atr", "bar1_close_vs_flip_close_atr",
    "bar1_close_above_flip_close", "bar1_close_above_50pct_range",
    "bar1_bullish_volume_pct",
    # Two-bar sequence
    "two_bar_range_atr", "two_bar_body_atr", "two_bar_close_vs_open_pct",
    "two_bar_volume_total", "two_bar_vol_vs_40avg",
    "flip_low_to_bar1_high_atr",
    # Pre-flip / 1m regime context
    "prior_regime_duration_bars", "consecutive_trend_bars_pre_flip",
    "pre_flip_3bar_body_direction", "pre_flip_3bar_range_atr",
    "pre_flip_5bar_range_atr", "pre_flip_volume_trend",
    "regime_flips_last_30min", "regime_flips_last_60min",
    # 1m MA context
    "price_vs_sma20_atr", "price_vs_sma50_atr", "sma20_slope_atr",
    "sma20_vs_sma50_atr", "sma50_slope_atr", "ema3_slope_atr",
    "ema_spread_atr", "ema3_ema9_spread_atr",
    # 1m volume
    "vol_1m_20avg", "vol_ratio_up_down_10bar",
    "vol_ratio_up_down_20bar", "vol_acceleration_5bar",
    "high_vol_bar_count_10", "cumulative_volume_bias_10",
    # Session / timing at signal
    "is_rth", "hour_of_day", "minute_of_hour", "minutes_since_rth_open",
    "distance_from_session_high_atr", "distance_from_session_low_atr",
    # State at signal
    "regime_30s_aligned_t0", "regime_5m_aligned_t0",
    # Signal direction
    "signal_direction",
]

# Checkpoint-level features at T_d (stem → decision-time column name)
# Keep only fields listed here; drop zero-variance / redundant ones.
CP_FEATURE_STEMS = [
    # ATR
    "atr_14_at",
    # 30s context
    "regime_30s", "regime_30s_aligned", "regime_30s_duration_bars",
    "ema3_slope_30s_atr", "ema_spread_30s_atr",
    "price_vs_sma20_30s_atr", "bar_range_30s_current_atr",
    # 5m context
    "regime_5m", "regime_5m_duration_bars",
    "ema3_slope_5m_atr", "ema_spread_5m_atr",
    "price_vs_sma20_5m_atr", "regime_5m_changed_during_delay_by",
    # 1m context
    "regime_1m",
    # Micro
    "micro_same_dir_count_12s", "micro_opp_dir_count_12s",
    "micro_aligned", "micro_opposing", "micro_net_return_atr",
    "micro_range_compression", "micro_body_pct_avg",
    # Continuation
    "continuation_count_since_signal", "consecutive_continuation_bars",
    "bars_since_last_continuation", "checkpoint_bars_since_signal_1m",
    # Session / timing at decision
    "is_rth", "hour_of_day", "minute_of_hour", "minutes_since_rth_open",
    "distance_from_session_high_atr", "distance_from_session_low_atr",
    # Volume
    "vol_total_30s_recent", "vol_vs_20avg_30s",
]

# Stems explicitly dropped (listed in SPEC.md):
DROPPED_STEMS_NO_VARIANCE = [
    "alive_at", "fillable_at", "regime_5m_aligned",
    "regime_5m_flipped_to_align_by", "dead_before",
    "checkpoint_elapsed_s",
]
DROPPED_STEMS_METADATA = [
    "checkpoint_time", "checkpoint_entry_fill_price",
    "checkpoint_entry_fill_time",
]

# Metadata kept in output (not as features)
# event_id = signal_ts serves as globally-unique trade identifier.
# `trade_id` in trades_all is a per-year counter and COLLIDES across years
# — do NOT use it for grouping or splits.
METADATA_COLS = [
    "trade_id", "signal_time", "signal_ts", "year", "date", "session",
]

# Spec-listed features missing from collector (documented):
MISSING_SPEC_FEATURES = [
    "prior_regime_mfe_atr",
    "bars_since_last_flip",
    "avg_regime_duration_last_5",
    "bar1_confirmed_hh_ll",
]


def compute_label(row, T_d: int, horizon: int):
    """Return 1, 0, or NaN per the SPEC label rule."""
    end_T = T_d + horizon
    if end_T > LABEL_GRID_MAX:
        return np.nan
    # Walk T_f from T_d + 30 up to T_d + horizon in 30s steps
    for T_f in range(T_d + 30, end_T + 1, 30):
        dead_col = f"dead_before_T_{T_f:03d}"
        aligned_col = f"regime_5m_aligned_T_{T_f:03d}"
        if row[dead_col] == 1:
            return np.nan  # censored
        if row[aligned_col] == 1:
            return 1
    return 0


def compute_labels_vectorized(df: pd.DataFrame, T_d: int, horizon: int):
    """Vectorized label computation for a given T_d and horizon.

    Returns an int array where 1/0 are labels and -1 denotes NaN
    (cannot use np.nan in int array; caller will convert).
    """
    end_T = T_d + horizon
    if end_T > LABEL_GRID_MAX:
        return np.full(len(df), np.nan)

    # Collect dead/aligned columns for the forward window
    T_fs = list(range(T_d + 30, end_T + 1, 30))
    dead_cols = np.stack(
        [df[f"dead_before_T_{T_f:03d}"].values for T_f in T_fs], axis=1)
    aligned_cols = np.stack(
        [df[f"regime_5m_aligned_T_{T_f:03d}"].values for T_f in T_fs],
        axis=1)

    n = len(df)
    labels = np.full(n, np.nan)

    # For each row, walk left-to-right through T_fs:
    #   first event = dead=1 → NaN
    #   first event = aligned=1 (and no prior dead) → 1
    #   neither hit in any column → 0
    # Vectorized: find first column where dead==1 (idx_dead), first where
    # aligned==1 (idx_aligned). Compare indices.
    # np.argmax returns 0 if no True (ambiguous with idx=0 True), so use
    # a safety "any" check.
    any_dead = dead_cols.any(axis=1)
    any_aligned = aligned_cols.any(axis=1)

    # idx of first True in each mask (valid only if any_*)
    idx_dead = np.argmax(dead_cols, axis=1)
    idx_aligned = np.argmax(aligned_cols, axis=1)

    # Case 1: aligned appears before dead (or no dead) → label = 1
    case_aligned = any_aligned & (
        ~any_dead | (idx_aligned < idx_dead))
    # Case 2: dead appears before aligned (or no aligned) → NaN (censored)
    case_dead = any_dead & (
        ~any_aligned | (idx_dead < idx_aligned))
    # Case 3: neither → 0
    case_neither = ~any_dead & ~any_aligned
    # Case 4: dead and aligned at SAME index → can't happen (collector
    # returns early on dead, so aligned_col is 0 when dead=1).

    labels[case_aligned] = 1.0
    labels[case_dead] = np.nan
    labels[case_neither] = 0.0
    return labels


def build_decision_rows(df: pd.DataFrame, T_d: int) -> pd.DataFrame:
    """Build rows for one decision checkpoint."""
    tag = f"{T_d:03d}"
    # Eligibility filter
    mask = (
        (df[f"fillable_at_T_{tag}"] == 1)
        & (df[f"regime_5m_aligned_T_{tag}"] == 0)
    )
    sub = df[mask].copy()
    if len(sub) == 0:
        return sub

    # Metadata
    out = sub[METADATA_COLS].copy()
    # event_id = signal_ts — globally unique. `trade_id` alone collides
    # across year-based collector runs; signal_ts is the safe key.
    out["event_id"] = sub["signal_ts"].values
    out["decision_checkpoint_s"] = T_d
    out["decision_ts"] = sub["signal_ts"].values + T_d * 1_000_000_000
    out["decision_fill_ts"] = out["decision_ts"] + 30 * 1_000_000_000

    # Root-level features (copy verbatim)
    for col in ROOT_FEATURES:
        if col in sub.columns:
            out[col] = sub[col].values
        else:
            print(f"  WARN: root feature missing: {col}")

    # Checkpoint-level features at T_d (rename to drop suffix)
    for stem in CP_FEATURE_STEMS:
        src = f"{stem}_T_{tag}"
        if src in sub.columns:
            # Rename stem "atr_14_at" → "atr_14_at_T" for clarity
            # (_T suffix indicates "at decision time")
            dest = f"{stem}_T"
            out[dest] = sub[src].values
        else:
            print(f"  WARN: cp feature missing: {src}")

    # FIX (Apr 2026): the collector's `checkpoint_bars_since_signal_1m_T_*`
    # column was set at trade-finalization time as `len(bars_since_signal_1m)`
    # — the TOTAL trade lifetime in 1m bars. This is a lookahead in the
    # offline dataset (same value for every T, depends on regime exit).
    # The semantically correct value at decision T_d is T_d / 60 (bars
    # elapsed between signal and this checkpoint observation).
    # Override here for parity with runtime computation.
    out["checkpoint_bars_since_signal_1m_T"] = T_d // 60

    # Labels for each horizon
    for h in HORIZONS:
        out[f"target_5m_flip_within_{h}s"] = compute_labels_vectorized(
            sub, T_d, h)

    return out


def main():
    print(f"Loading {INPUT_PATH}...")
    df = pd.read_parquet(INPUT_PATH)
    print(f"  {len(df):,} trades × {len(df.columns)} columns")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Verify required columns exist
    missing_root = [c for c in ROOT_FEATURES if c not in df.columns]
    if missing_root:
        print(f"WARN: {len(missing_root)} root features missing: "
              f"{missing_root}")

    # Build per-T decision rows
    all_rows = []
    per_T_stats = []
    for T_d in CHECKPOINTS:
        tag = f"{T_d:03d}"
        total_trades = len(df)
        n_fillable = (df[f"fillable_at_T_{tag}"] == 1).sum()
        n_aligned = (df[f"regime_5m_aligned_T_{tag}"] == 1).sum()
        n_fillable_not_aligned = (
            (df[f"fillable_at_T_{tag}"] == 1)
            & (df[f"regime_5m_aligned_T_{tag}"] == 0)
        ).sum()
        rows = build_decision_rows(df, T_d)
        all_rows.append(rows)
        per_T_stats.append({
            "T_d": T_d,
            "total_trades": total_trades,
            "fillable": int(n_fillable),
            "fillable_pct": n_fillable / total_trades * 100,
            "aligned_at_T": int(n_aligned),
            "aligned_pct": n_aligned / total_trades * 100,
            "eligible_rows": len(rows),
            "eligible_pct": len(rows) / total_trades * 100,
        })
        print(f"  T_d={T_d}: {len(rows):,} eligible rows "
              f"({len(rows)/total_trades*100:.1f}% of {total_trades:,})")

    dataset = pd.concat(all_rows, ignore_index=True)
    print(f"\nTotal dataset rows: {len(dataset):,}")

    # Save
    dataset.to_parquet(OUT_PARQUET, index=False)
    print(f"Saved: {OUT_PARQUET}")

    # -------------------- QA log --------------------
    lines = []
    lines.append("=" * 110)
    lines.append("ML 5m FLIP PREDICTION — DATASET QA LOG (v1)")
    lines.append(
        "Spec: studies/ml_5m_flip_prediction/SPEC.md")
    lines.append(
        f"Input:  {INPUT_PATH}")
    lines.append(
        f"Output: {OUT_PARQUET}")
    lines.append("=" * 110)

    # 1. Shape & feature counts
    lines.append("\n--- 1. SHAPE & FEATURE COUNTS ---")
    lines.append(f"  Source trades:             {len(df):>8,}")
    lines.append(f"  Total candidate decisions: {11 * len(df):>8,}")
    lines.append(f"  Dataset rows (post-filter):{len(dataset):>8,}")

    feat_cols = [c for c in dataset.columns
                 if c not in METADATA_COLS
                 and c not in ("event_id", "decision_checkpoint_s",
                               "decision_ts", "decision_fill_ts")
                 and not c.startswith("target_")]
    lines.append(f"  Metadata columns:          {len(METADATA_COLS):>8}")
    lines.append(f"  Feature columns:           {len(feat_cols):>8}")
    lines.append(f"  Target columns:            {len(HORIZONS):>8}")

    # 2. Per-T eligibility
    lines.append("\n--- 2. ELIGIBILITY PER DECISION T ---")
    lines.append(
        f"  {'T_d':>4} {'Total':>8} {'Fillable':>9} {'Fill%':>6} "
        f"{'Aligned':>8} {'Al%':>6} {'Eligible':>9} {'Elig%':>6}")
    for s in per_T_stats:
        lines.append(
            f"  {s['T_d']:>3}s {s['total_trades']:>8,} "
            f"{s['fillable']:>9,} {s['fillable_pct']:>5.1f}% "
            f"{s['aligned_at_T']:>8,} {s['aligned_pct']:>5.1f}% "
            f"{s['eligible_rows']:>9,} {s['eligible_pct']:>5.1f}%"
        )

    # 3. Label base rates (per horizon, per T_d, pooled, by session)
    lines.append("\n--- 3. LABEL BASE RATES ---")
    for h in HORIZONS:
        col = f"target_5m_flip_within_{h}s"
        valid = dataset[col].notna()
        pos = (dataset[col] == 1).sum()
        neg = (dataset[col] == 0).sum()
        nan = dataset[col].isna().sum()
        total = len(dataset)
        base_rate = pos / (pos + neg) * 100 if (pos + neg) > 0 else 0
        lines.append(
            f"  {col}: "
            f"N_valid={pos+neg:>7,}  pos={pos:>6,}  neg={neg:>7,}  "
            f"censored/NaN={nan:>7,}  base_rate={base_rate:>5.1f}%")

    # Primary horizon detail
    lines.append("\n  Primary horizon (300s) base rate by T_d:")
    col = "target_5m_flip_within_300s"
    lines.append(
        f"    {'T_d':>4} {'N_valid':>8} {'pos':>6} {'neg':>7} "
        f"{'NaN':>6} {'base_rate%':>10}")
    for T_d in CHECKPOINTS:
        sub = dataset[dataset["decision_checkpoint_s"] == T_d]
        if len(sub) == 0:
            continue
        pos = (sub[col] == 1).sum()
        neg = (sub[col] == 0).sum()
        nan = sub[col].isna().sum()
        if pos + neg > 0:
            rate = pos / (pos + neg) * 100
            lines.append(
                f"    {T_d:>3}s {pos+neg:>8,} {pos:>6,} {neg:>7,} "
                f"{nan:>6,} {rate:>9.1f}%")
        else:
            lines.append(
                f"    {T_d:>3}s (no valid labels for this horizon)")

    # Primary by session
    lines.append("\n  Primary horizon (300s) base rate by session:")
    for val, lbl in [(1, "RTH"), (0, "ETH")]:
        sub = dataset[dataset["is_rth"] == val]
        pos = (sub[col] == 1).sum()
        neg = (sub[col] == 0).sum()
        rate = pos / (pos + neg) * 100 if (pos + neg) > 0 else 0
        lines.append(
            f"    {lbl}: N_valid={pos+neg:>7,} pos={pos:>6,} "
            f"neg={neg:>6,} base_rate={rate:>5.1f}%")

    # Primary by direction
    lines.append("\n  Primary horizon (300s) base rate by direction:")
    for val, lbl in [(1, "LONG"), (-1, "SHORT")]:
        sub = dataset[dataset["signal_direction"] == val]
        pos = (sub[col] == 1).sum()
        neg = (sub[col] == 0).sum()
        rate = pos / (pos + neg) * 100 if (pos + neg) > 0 else 0
        lines.append(
            f"    {lbl:>5}: N_valid={pos+neg:>7,} pos={pos:>6,} "
            f"neg={neg:>6,} base_rate={rate:>5.1f}%")

    # Primary by year
    lines.append("\n  Primary horizon (300s) base rate by year:")
    for y in sorted(dataset["year"].unique()):
        sub = dataset[dataset["year"] == y]
        pos = (sub[col] == 1).sum()
        neg = (sub[col] == 0).sum()
        rate = pos / (pos + neg) * 100 if (pos + neg) > 0 else 0
        lines.append(
            f"    {int(y):>4}: N_valid={pos+neg:>7,} pos={pos:>6,} "
            f"neg={neg:>6,} base_rate={rate:>5.1f}%")

    # 4. No-lookahead verification
    lines.append("\n--- 4. NO-LOOKAHEAD VERIFICATION ---")

    # Check 1: no forward_* in feature columns
    forward_leaks = [c for c in feat_cols if c.startswith("forward_")]
    lines.append(
        f"  Forward_* in features:             "
        f"{'FAIL' if forward_leaks else 'PASS'} "
        f"({len(forward_leaks)} found)")
    # Check 2: no regime_5m_flip_checkpoint
    leak2 = [c for c in feat_cols if "flip_checkpoint" in c]
    lines.append(
        f"  regime_5m_flip_checkpoint leak:    "
        f"{'FAIL' if leak2 else 'PASS'} ({len(leak2)} found)")
    # Check 3: no t0_* forward metrics
    leak3 = [c for c in feat_cols if c.startswith("t0_")
             and any(k in c for k in
                     ["mfe", "mae", "peak", "forward", "fill"])]
    lines.append(
        f"  t0_*_forward metrics leak:         "
        f"{'FAIL' if leak3 else 'PASS'} ({len(leak3)} found)")
    # Check 4: no mfe/mae/pnl_from_t0_to_T_*
    leak4 = [c for c in feat_cols
             if "from_t0_to_T" in c]
    lines.append(
        f"  mfe/mae/pnl_from_t0_to_T_* leak:   "
        f"{'FAIL' if leak4 else 'PASS'} ({len(leak4)} found)")
    # Check 5: no regime_exit_*
    leak5 = [c for c in feat_cols if c.startswith("regime_exit_")]
    lines.append(
        f"  regime_exit_* leak:                "
        f"{'FAIL' if leak5 else 'PASS'} ({len(leak5)} found)")
    # Check 6: no _T_NNN suffixed cols with NNN > 0 leaking (we renamed)
    import re
    ckpt_pat = re.compile(r"_T_\d{3}$")
    leak6 = [c for c in feat_cols if ckpt_pat.search(c)]
    lines.append(
        f"  _T_{{NNN}} suffixes in features:     "
        f"{'FAIL' if leak6 else 'PASS'} ({len(leak6)} found)")
    # Check 7: eligibility implications
    # regime_5m_aligned_T_T should be absent (excluded since always 0)
    leak7 = [c for c in feat_cols if c == "regime_5m_aligned_T"]
    lines.append(
        f"  regime_5m_aligned_T (no-var) leak: "
        f"{'FAIL' if leak7 else 'PASS'} ({len(leak7)} found)")

    # 5. Feature column listing
    lines.append("\n--- 5. FEATURE COLUMNS INCLUDED ---")
    lines.append(f"  Total features: {len(feat_cols)}")
    lines.append("  Root-level features:")
    for c in sorted(feat_cols):
        if c.endswith("_T"):
            continue
        lines.append(f"    {c}")
    lines.append("  Decision-time (_T) features:")
    for c in sorted(feat_cols):
        if c.endswith("_T"):
            lines.append(f"    {c}")
    lines.append(f"  Decision-derived: decision_checkpoint_s")

    # 6. Documented gaps
    lines.append("\n--- 6. SPEC-LISTED FEATURES MISSING FROM COLLECTOR ---")
    lines.append("  (v1 drops these; collector extension candidate if "
                  "baseline justifies)")
    for c in MISSING_SPEC_FEATURES:
        lines.append(f"    {c}")

    # 7. Stems explicitly dropped
    lines.append("\n--- 7. STEMS EXPLICITLY DROPPED ---")
    lines.append("  Zero-variance / eligibility-redundant:")
    for s in DROPPED_STEMS_NO_VARIANCE:
        lines.append(f"    {s}")
    lines.append("  Metadata (not features):")
    for s in DROPPED_STEMS_METADATA:
        lines.append(f"    {s}")

    # 8. Train/val/test row counts
    lines.append("\n--- 8. TRAIN/VAL/TEST SPLIT (by trade signal year) ---")
    tvt = {
        "TRAIN (2020-2023)": dataset["year"].isin([2020, 2021, 2022, 2023]),
        "VAL (2024)": dataset["year"] == 2024,
        "TEST (2025)": dataset["year"] == 2025,
    }
    for lbl, mask in tvt.items():
        sub = dataset[mask]
        n_rows = len(sub)
        n_events = sub["event_id"].nunique() if n_rows > 0 else 0
        col = "target_5m_flip_within_300s"
        n_valid = sub[col].notna().sum()
        pos = (sub[col] == 1).sum()
        rate = pos / n_valid * 100 if n_valid > 0 else 0
        lines.append(
            f"  {lbl}: rows={n_rows:>7,}  events={n_events:>6,}  "
            f"300s_valid={n_valid:>7,}  pos_rate={rate:>5.1f}%")

    # 9. Group-by-trade leakage check (use event_id = signal_ts)
    lines.append("\n--- 9. GROUP-BY-EVENT SPLIT INTEGRITY ---")
    event_years = dataset.groupby("event_id")["year"].nunique()
    leak_events = (event_years > 1).sum()
    lines.append(
        f"  Events with rows in multiple years: "
        f"{'FAIL' if leak_events else 'PASS'} "
        f"({leak_events:,} events)")
    # Also verify event_id uniqueness per year
    lines.append(
        f"  Total unique events in dataset:  "
        f"{dataset['event_id'].nunique():,}")
    lines.append(
        f"  Total dataset rows:              {len(dataset):,}")
    lines.append(
        f"  Avg rows per event (eligible checkpoints): "
        f"{len(dataset) / dataset['event_id'].nunique():.2f}")
    # Note trade_id collision
    tid_years = dataset.groupby("trade_id")["year"].nunique()
    tid_collide = (tid_years > 1).sum()
    lines.append(
        f"  `trade_id` collisions across years (expected — "
        f"per-year counter):")
    lines.append(
        f"    {tid_collide:,} trade_ids span multiple years — "
        f"DO NOT use trade_id for grouping; use event_id.")

    # Write log
    log_text = "\n".join(lines)
    OUT_LOG.write_text(log_text, encoding="utf-8")
    print("\n" + log_text)
    print(f"\nSaved log: {OUT_LOG}")


if __name__ == "__main__":
    main()
