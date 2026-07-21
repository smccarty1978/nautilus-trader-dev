"""Phase 3 (5m) — state interpretation for 5m regime classification.

For each (model, k) combination from Phase 2 (5m):
  - Time share per state (% of rows)
  - Mean feature values per state (normalized: z-score within that model)
  - Mean state duration (consecutive 5m bars in same state)
  - Transition matrix
  - Time-of-day distribution (by ET hour)
  - Year distribution

Then surfaces a per-model interpretability note: state separation on
feature means (using max - min spread across states per feature) and
state-share concentration (Herfindahl: if one state holds >50% the
model is degenerate).

Output:
  - studies/regime_classification/results/interpretation_summary_nq_5m.csv
  - printed summary tables
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
OUT = Path("studies/regime_classification/results")

FEATURE_COLS = [
    "ret_25s", "ret_150s", "ret_300s", "ret_1500s", "cum_abs_300s",
    "rv_150s", "rv_1500s",
    "range_atr_300s", "range_atr_1500s", "range_atr_9000s",
    "vol_expansion",
    "efficiency_1500s", "chop_ratio_1500s", "n_dir_changes_300s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_25m_atr", "session_pos",
    "range_pct_300s_vs_5h", "compress_drift",
]

# Headline features to print per state (subset for readability)
HEADLINE_FEATS = [
    "rv_1500s", "range_atr_300s", "range_atr_1500s", "range_atr_9000s",
    "efficiency_1500s", "vwap_z_abs", "vol_expansion",
    "range_pct_300s_vs_5h", "compress_drift",
]


def state_duration_stats(state_series):
    """Mean and median consecutive-bar duration of a state."""
    s = state_series.values
    durations = {}
    cur_state = -999
    cur_len = 0
    for v in s:
        if v == cur_state:
            cur_len += 1
        else:
            if cur_state in durations:
                durations[cur_state].append(cur_len)
            else:
                durations[cur_state] = [cur_len]
            cur_state = v
            cur_len = 1
    if cur_state in durations:
        durations[cur_state].append(cur_len)
    return {st: (np.mean(d), np.median(d)) for st, d in durations.items()
            if st >= 0}


def transition_matrix(state_series):
    """N x N transition matrix (rows = from, cols = to). Normalised."""
    s = state_series.values
    states = sorted([x for x in pd.unique(s) if x >= 0])
    n = len(states)
    mat = np.zeros((n, n))
    st_idx = {st: i for i, st in enumerate(states)}
    prev = s[0] if s[0] >= 0 else -1
    for v in s[1:]:
        if prev >= 0 and v >= 0:
            mat[st_idx[prev], st_idx[v]] += 1
        prev = v
    row_sum = mat.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0] = 1
    return states, mat / row_sum


def main():
    t0 = time.time()
    in_p = OUT / f"states_{PRODUCT.lower()}_5m.parquet"
    df = pd.read_parquet(in_p)
    print(f"Loaded {len(df):,} rows from {in_p.name}")

    state_cols = [c for c in df.columns if any(c.startswith(p) for p in
                   ("hmm_", "gmm_", "kmeans_"))]
    print(f"State columns: {state_cols}\n")

    # ── Per (model, k) summary ──
    summary_rows = []
    for sc in state_cols:
        kind, k = sc.split("_")
        k = int(k)
        sub = df[df[sc] >= 0].copy()
        if len(sub) == 0:
            continue
        # Time share per state
        share = sub[sc].value_counts(normalize=True).sort_index()
        max_share = share.max()
        # Feature-mean spread (z-scored within column)
        feat = sub.groupby(sc)[FEATURE_COLS].mean()
        feat_z = (feat - feat.mean()) / feat.std().replace(0, 1)
        # Separation = mean max-abs feature z across all features
        separation = feat_z.abs().max(axis=0).mean()
        # State duration: mean
        dur = state_duration_stats(sub[sc])
        mean_dur = np.mean([d[0] for d in dur.values()])
        summary_rows.append({
            "model": kind, "k": k,
            "max_share": max_share,
            "min_share": share.min(),
            "separation": separation,
            "mean_duration_bars": mean_dur,
            "mean_duration_min": mean_dur * 5,
        })

    summary = pd.DataFrame(summary_rows)
    print(f"{'='*78}")
    print(f"5M MODEL SUMMARY (degeneracy + state separation)")
    print(f"{'='*78}")
    print(summary.to_string(
        formatters={"max_share": "{:.1%}".format,
                     "min_share": "{:.1%}".format,
                     "separation": "{:.2f}".format,
                     "mean_duration_bars": "{:.1f}".format,
                     "mean_duration_min": "{:.1f}".format}))

    # Per-state detail for each model
    for sc in state_cols:
        kind, k = sc.split("_")
        k = int(k)
        sub = df[df[sc] >= 0]
        if len(sub) == 0:
            continue
        print(f"\n{'='*78}\n{sc.upper()} — per-state detail (5m)\n{'='*78}")
        share = sub[sc].value_counts(normalize=True).sort_index()
        # Mean of headline features per state
        feat = sub.groupby(sc)[HEADLINE_FEATS].mean()
        # Mean state duration
        dur = state_duration_stats(sub[sc])
        durs_bars = pd.Series({st: round(d[0], 1) for st, d in dur.items()})
        durs_min = pd.Series({st: round(d[0] * 5, 1) for st, d in dur.items()})
        # Show
        report = feat.copy()
        report.insert(0, "share", (share * 100).round(1).astype(str) + "%")
        report.insert(1, "dur_bars", durs_bars.astype(float))
        report.insert(2, "dur_min", durs_min.astype(float))
        print(report.to_string(float_format=lambda x: f"{x:6.3f}"))

        # Transition matrix
        states_list, tm = transition_matrix(sub[sc])
        tm_df = pd.DataFrame(tm, index=states_list, columns=states_list)
        print(f"\n  Transition matrix (rows=from, cols=to):")
        print((tm_df * 100).round(1).to_string(
            float_format=lambda x: f"{x:5.1f}"))

    summary.to_csv(OUT / f"interpretation_summary_{PRODUCT.lower()}_5m.csv",
                    index=False)
    print(f"\nsaved interpretation summary CSV")
    print(f"[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
