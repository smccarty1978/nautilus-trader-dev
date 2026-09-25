"""Robustness vetting of the atlas candidates (Phase 6/9): block x direction, tail-trimmed, one episode per regime.

For each candidate (threshold k, feature, outcome) the top bin is compared with the bottom bin (block-A bins, as in atlas.py)
on the location residual, and separately:
  * by block x direction (2023 was a strong up year: a 'value' effect that only exists for longs may be drift)
  * with the outcome trimmed at its 1st/99th percentile
  * with one episode per regime (the first qualifying one), so long regimes with many episodes are not over-weighted

    python studies/nq_regime_challenge_lifecycle_2023/vet.py
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

import atlas as at

OUT = Path(__file__).resolve().parent / "artifacts"
CANDIDATES = [
    # (k, feature, outcome)
    (0.5, "atr_pts", "hold_A_res"), (1.0, "atr_pts", "hold_A_res"), (0.5, "rv30_pts", "hold_A_res"),
    (0.5, "1h_aligned", "hold_A_res"), (1.0, "1h_aligned", "hold_A_res"),
    (0.5, "15m_flips_since_start", "hold_A_res"), (1.0, "15m_flips_since_start", "hold_A_res"), (1.5, "15m_flips_since_start", "hold_A_res"),
    (0.5, "opening_drive", "hold_A_res"),
    (1.5, "prev_rec_time_s", "hold_A_res"), (2.0, "prev_rec_time_s", "hold_A_res"), (2.0, "imp_bars", "hold_A_res"),
    (2.0, "since_prev_onset_s", "hold_A_res"), (1.5, "deepest_prior_A", "hold_A_res"),
    (0.5, "ch_dur_s", "res_new_ext_res"), (0.5, "ret15_A", "res_new_ext_res"), (1.0, "ch_wick_frac", "res_new_ext_res"),
    (1.5, "since_prev_onset_s", "res_new_ext_res"), (2.0, "imp_bars", "res_new_ext_res"), (1.5, "opening_drive", "res_new_ext_res"),
    (1.5, "prog_last_A", "res_new_ext_res"),
]


def contrast(df, b, col, trim=False):
    y = df[col]
    if trim:
        lo, hi = y.quantile([0.01, 0.99])
        y = y.clip(lo, hi)
    top, bot = b == b.max(), b == b.min()
    return float(y[top].mean() - y[bot].mean()), int(top.sum()), int(bot.sum())


def main() -> None:
    t0 = time.time()
    ev = pd.read_parquet(OUT / "CHALLENGE_EVENTS.parquet")
    frames = {k: at.add_baseline(ev[ev.k == k].copy(), "dist_flip_A", at.OUTC) for k in sorted({c[0] for c in CANDIDATES})}
    rows = []
    for k, f, o in CANDIDATES:
        df = frames[k]
        a = (df.block == "A").to_numpy()
        b = at.qbin(df[f], a)
        ok = b.notna()
        d, b = df[ok], b[ok]
        rec = {"k": k, "feature": f, "outcome": o}
        for blk in ("A", "B"):
            m = d.block == blk
            rec[f"{blk}"], rec[f"{blk}_n_top"], rec[f"{blk}_n_bot"] = contrast(d[m], b[m], o)
            rec[f"{blk}_trim"] = contrast(d[m], b[m], o, trim=True)[0]
            for dr, name in ((1, "long"), (-1, "short")):
                mm = m & (d.dir == dr)
                rec[f"{blk}_{name}"], rec[f"{blk}_{name}_n_top"], _ = contrast(d[mm], b[mm], o)
            first = d[m].assign(_b=b[m]).sort_values("n").drop_duplicates("regime_start_ns")
            rec[f"{blk}_one_per_regime"] = contrast(first, first._b, o)[0]
        signs = [np.sign(rec[x]) for x in ("A", "B", "A_trim", "B_trim", "A_long", "A_short", "B_long", "B_short", "A_one_per_regime", "B_one_per_regime")]
        rec["consistent_of_10"] = int(sum(s == signs[0] for s in signs))
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "CANDIDATE_VETTING.csv", index=False)
    pd.set_option("display.width", 250)
    print(out[["k", "feature", "outcome", "A", "B", "A_trim", "B_trim", "A_long", "A_short", "B_long", "B_short", "A_one_per_regime", "B_one_per_regime",
               "B_n_top", "B_short_n_top", "consistent_of_10"]].round(3).to_string(index=False))
    print(f"runtime {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
