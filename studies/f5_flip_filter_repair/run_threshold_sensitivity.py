"""Phase 11: Threshold sensitivity (diagnostic only -- the frozen threshold
0.15 remains the primary result; no reselection here)."""
import numpy as np
import pandas as pd
from common import OUT
from f5_episodes import build_episodes
from f5_economics import EVAL_PERIODS

THRESHOLDS = [0.10, 0.125, 0.15, 0.175, 0.20]
RANK_SKIP_FRACTIONS = [0.01, 0.02, 0.03, 0.05]


def metrics_for_skip_mask(g: pd.DataFrame, skip: np.ndarray) -> dict:
    baseline = g["baseline_net_pnl"].values
    kept_pnl = np.where(skip, 0.0, baseline)
    n = len(g)
    n_skip = int(skip.sum())
    return {
        "eligible_n": n,
        "skip_count": n_skip,
        "retention": (n - n_skip) / n if n else float("nan"),
        "economic_lift_per_eligible": float((kept_pnl - baseline).mean()) if n else float("nan"),
    }


def run():
    ep = build_episodes()

    thr_rows = []
    for role in EVAL_PERIODS + ["combined_post_train"]:
        mask = ep["period_role"].isin(EVAL_PERIODS) if role == "combined_post_train" else (ep["period_role"] == role)
        g = ep[mask]
        for thr in THRESHOLDS:
            skip = (g["frozen_f5_score"] >= thr).values
            m = metrics_for_skip_mask(g, skip)
            m.update({"period": role, "method": "threshold", "threshold_or_fraction": thr})
            thr_rows.append(m)
        for frac in RANK_SKIP_FRACTIONS:
            n_skip_target = int(round(frac * len(g)))
            order = g["frozen_f5_score"].rank(ascending=False, method="first")
            skip = (order <= n_skip_target).values
            m = metrics_for_skip_mask(g, skip)
            m.update({"period": role, "method": "score_rank_top_fraction", "threshold_or_fraction": frac})
            thr_rows.append(m)

    df = pd.DataFrame(thr_rows)

    # Stability classification per period: is lift a plateau, spike, or monotonic
    # across the 5 nearby threshold candidates (validation-adjacent grid)?
    stability = {}
    for role in EVAL_PERIODS + ["combined_post_train"]:
        sub = df[(df["period"] == role) & (df["method"] == "threshold")].sort_values("threshold_or_fraction")
        lifts = sub["economic_lift_per_eligible"].values
        if np.all(np.isfinite(lifts)) and len(lifts) == len(THRESHOLDS):
            diffs = np.diff(lifts)
            is_monotonic = np.all(diffs >= -1e-9) or np.all(diffs <= 1e-9)
            spread = lifts.max() - lifts.min()
            center = lifts[len(lifts) // 2]
            is_spike = (lifts[len(lifts) // 2] == lifts.max()) and (spread > 2 * max(abs(center), 0.5))
            if is_monotonic and not is_spike:
                label = "monotonic"
            elif spread < 1.0:
                label = "stable_plateau"
            elif is_spike:
                label = "single_threshold_spike"
            else:
                label = "mixed_unstable"
        else:
            label = "insufficient_data"
        stability[role] = {"label": label, "lift_range": float(lifts.max() - lifts.min()) if len(lifts) else float("nan")}

    df["stability_label"] = df["period"].map(lambda r: stability.get(r, {}).get("label"))
    df.to_parquet(OUT / "f5_threshold_sensitivity.parquet", index=False)

    print(df[df["method"] == "threshold"][["period", "threshold_or_fraction", "retention", "economic_lift_per_eligible", "stability_label"]].to_string(index=False))
    return df, stability


if __name__ == "__main__":
    import os
    from common import SRC
    os.chdir(SRC.parent.parent.parent)
    run()
