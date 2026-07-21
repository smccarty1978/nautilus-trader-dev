"""matched_random_summary.parquet: for A1/A2/A4 (each window), 1000+ matched-
random skip-selection controls per evaluation block.

Within each (month, direction, session, atr_bucket, entry_delay_bucket)
stratum, draws a random subset of episodes to "skip" of the SAME SIZE as the
real policy's skip count in that stratum, computes the resulting EV lift vs
the all-eligible R0 baseline, and repeats 1000 times. Reports where the real
(score-based) EV lift falls in that random-selection distribution.

atr_bucket here is a single global tercile split of ATR over the whole
eligible population (episode_status.parquet's atr_bucket_static) -- a
consistent stratification variable, not to be confused with the per-fold
validation-frozen ATR edges recorded in the training audit (which are used
for the score-threshold fitting diagnostics, not for this control).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c
from compute_metrics import POOLED_BLOCKS, month_in_block

WORK_DIR = c.OUT.parent / "_work"
N_SIMS = 1000
RNG_SEED = 7


def real_ev_lift(status: pd.DataFrame, policy: str, block: tuple[str, str]) -> tuple[float, pd.DataFrame]:
    r0 = status[(status["policy"] == "r0") & (status["deploy_month"].apply(lambda m: month_in_block(m, block)))].set_index("confirmation_ts")
    pol = status[(status["policy"] == policy) & (status["deploy_month"].apply(lambda m: month_in_block(m, block)))].set_index("confirmation_ts")
    r0_contrib = np.where(r0["filled"], r0["net_pnl"], 0.0)
    pol_contrib = np.where(pol["filled"], pol["net_pnl"], 0.0)
    lift = float(pol_contrib.mean() - r0_contrib.mean())
    frame = pd.DataFrame({"r0_pnl": r0["net_pnl"].values, "r0_filled": r0["filled"].values,
                           "skipped": pol["skipped"].values,
                           "month": r0.index.map(lambda ts: pd.to_datetime(ts, unit="ns", utc=True).tz_convert("America/Chicago").strftime("%Y-%m")),
                           "direction": r0["direction"].values, "session": r0["session"].values,
                           "atr_bucket": r0["atr_bucket_static"].astype(str).values,
                           "entry_delay_bucket": r0["entry_delay_bucket"].values}, index=r0.index)
    return lift, frame


def matched_random_sim(frame: pd.DataFrame, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    r0_all_contrib = np.where(frame["r0_filled"], frame["r0_pnl"], 0.0)
    baseline_ev = r0_all_contrib.mean()

    strata_cols = ["month", "direction", "session", "atr_bucket", "entry_delay_bucket"]
    frame = frame.copy()
    frame["_stratum"] = frame[strata_cols].astype(str).agg("|".join, axis=1)

    lifts = np.empty(n_sims)
    grouped = {k: v.index.values for k, v in frame.groupby("_stratum")}
    real_skip_counts = {k: int(frame.loc[v, "skipped"].sum()) for k, v in grouped.items()}
    r0_contrib_by_idx = pd.Series(r0_all_contrib, index=frame.index)

    n_total = len(frame)
    for s in range(n_sims):
        skip_mask = np.zeros(n_total, dtype=bool)
        pos = 0
        idx_order = []
        for stratum, idxs in grouped.items():
            k = real_skip_counts[stratum]
            idx_order.extend(idxs)
            if k > 0 and len(idxs) > 0:
                chosen = rng.choice(len(idxs), size=min(k, len(idxs)), replace=False)
                local_mask = np.zeros(len(idxs), dtype=bool)
                local_mask[chosen] = True
                skip_mask[pos:pos + len(idxs)] = local_mask
            pos += len(idxs)
        idx_order = np.array(idx_order)
        random_pol_contrib = np.where(skip_mask, 0.0, r0_contrib_by_idx.loc[idx_order].values)
        lifts[s] = random_pol_contrib.mean() - baseline_ev
    return lifts


def main():
    status = pd.read_parquet(WORK_DIR / "episode_status.parquet")
    adaptive_policies = [p for p in status["policy"].unique() if p.split("_", 1)[0] in ("a1", "a2", "a4")]
    rng = np.random.default_rng(RNG_SEED)

    rows = []
    for block_name, block in POOLED_BLOCKS.items():
        for policy in adaptive_policies:
            lift, frame = real_ev_lift(status, policy, block)
            if len(frame) == 0:
                continue
            random_lifts = matched_random_sim(frame, N_SIMS, rng)
            frac_ge = float((random_lifts >= lift).mean())
            rows.append({
                "block": block_name, "policy": policy,
                "n_sims": N_SIMS,
                "real_ev_lift": lift,
                "random_median": float(np.median(random_lifts)),
                "random_p95": float(np.percentile(random_lifts, 95)),
                "fraction_random_ge_real": frac_ge,
                "empirical_p_value": frac_ge,
            })
            print(f"  {block_name}/{policy}: real={lift:.4f} random_median={np.median(random_lifts):.4f} p={frac_ge:.4f}")

    out = pd.DataFrame(rows)
    out.to_parquet(c.OUT / "matched_random_summary.parquet", index=False)
    print("matched_random_summary:", out.shape)


if __name__ == "__main__":
    main()
