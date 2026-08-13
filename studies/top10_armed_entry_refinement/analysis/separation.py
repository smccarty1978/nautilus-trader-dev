"""Phase 2 — where do SUCCESS and FAILURE score paths separate, and how early?

Landmark design: state is read at a FIXED elapsed time from the arm, among arms
still unresolved at that time. This is the deployable question (you can only act
on a live armed state) and it removes the duration confound that has corrupted
results twice in this research line -- a path summary running to the terminal
event encodes the outcome it is being used to predict.

AUC is the probability that a randomly chosen SUCCESS ranks above a randomly
chosen FAILURE on that feature. 0.50 is no information. Cliff's delta is
2*AUC - 1, reported because it is the effect size the brief asks for.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..implementation.paths import LANDMARK_TIMES_S, LEVELS, SLOPE_WINDOWS_S

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/top10_armed_entry_refinement/results"
STREAM = OUT / "armed_score_path_diagnostics.parquet"
NS = 1_000_000_000

FEATURES = (
    "score", "delta_from_arm", "score_running_max", "drawdown_from_max",
    "consec_top_10", "price_move_from_arm_atr",
    *[f"slope_{w}s" for w in SLOPE_WINDOWS_S],
)


def auc(x: np.ndarray, pos: np.ndarray) -> float | None:
    """P(x[success] > x[failure]), ties averaged. `pos` marks SUCCESS."""
    ok = np.isfinite(x)
    x, pos = x[ok], pos[ok]
    np_, nn = int(pos.sum()), int((~pos).sum())
    if np_ < 20 or nn < 20:
        return None
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(x.size, dtype=float)
    ranks[order] = np.arange(1, x.size + 1)
    vals, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(vals.size)
    np.add.at(sums, inv, ranks)
    ranks = (sums / cnt)[inv]
    return float((ranks[pos].sum() - np_ * (np_ + 1) / 2) / (np_ * nn))


def snapshot(stream: pl.DataFrame, t: int) -> pl.DataFrame:
    """Last true dispatch at or before `t` seconds, among arms alive at `t`."""
    alive = stream.filter(
        (pl.col("arm_terminal_ns") - pl.col("arm_ns")) / NS > t
    )
    upto = alive.filter(pl.col("elapsed_s") <= t)
    if upto.height == 0:
        return upto
    return (
        upto.sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .agg(
            arm_outcome=pl.col("arm_outcome").first(),
            side=pl.col("side").first(),
            entry_year=pl.col("entry_year").first(),
            n_obs=pl.len(),
            # `consec_top_10` is already in FEATURES; adding it again here would
            # pass the same keyword twice.
            **{f: pl.col(f).last() for f in FEATURES if f in upto.columns},
            **{f"ge_{k}": pl.col(f"ge_{k}").any() for k in LEVELS},
            **{f"consec_{k}": pl.col(f"consec_{k}").last()
               for k in ("INTERP_L1", "INTERP_L2", "top_5")},
        )
        .filter(pl.col("arm_outcome").is_in(["SUCCESS", "FAILURE"]))
    )


def main() -> None:
    stream = pl.read_parquet(STREAM).with_columns(
        # Signed and normalised by the ARM's ATR so candidates stay commensurable
        # (SPEC 4.2). Positive means the move already went our way while we waited.
        price_move_from_arm_atr=(
            (pl.col("checkpoint_reference_price") - pl.col("arm_price"))
            * pl.col("direction") / pl.col("arm_atr")
        ),
        side=pl.when(pl.col("direction") > 0).then(pl.lit("LONG")).otherwise(pl.lit("SHORT")),
    )
    rows = []
    for t in LANDMARK_TIMES_S:
        snap = snapshot(stream, t)
        if snap.height == 0:
            continue
        pos = (snap["arm_outcome"] == "SUCCESS").to_numpy()
        base = {"landmark_s": t, "n_alive": snap.height,
                "n_success": int(pos.sum()), "n_failure": int((~pos).sum()),
                "median_obs_by_t": float(snap["n_obs"].median())}
        for f in FEATURES:
            if f not in snap.columns:
                continue
            x = snap[f].to_numpy().astype(float)
            a = auc(x, pos)
            ok = np.isfinite(x)
            rows.append({**base, "feature": f, "kind": "continuous",
                         "auc": round(a, 4) if a is not None else None,
                         "cliffs_delta": round(2 * a - 1, 4) if a is not None else None,
                         "median_success": round(float(np.median(x[ok & pos])), 4) if (ok & pos).any() else None,
                         "median_failure": round(float(np.median(x[ok & ~pos])), 4) if (ok & ~pos).any() else None,
                         "coverage": round(float(ok.mean()), 4)})
        # Binary reach flags and persistence counts, as rate differences.
        for k in LEVELS:
            col = f"ge_{k}"
            v = snap[col].fill_null(False).to_numpy()
            rows.append({**base, "feature": col, "kind": "binary",
                         "auc": None, "cliffs_delta": None,
                         "rate_success": round(float(v[pos].mean()), 4),
                         "rate_failure": round(float(v[~pos].mean()), 4),
                         "rate_diff": round(float(v[pos].mean() - v[~pos].mean()), 4)})
        for k in ("top_10", "INTERP_L1", "INTERP_L2", "top_5"):
            for n in (2, 3):
                v = (snap[f"consec_{k}"].fill_null(0) >= n).to_numpy()
                rows.append({**base, "feature": f"consec_{k}_ge{n}", "kind": "binary",
                             "rate_success": round(float(v[pos].mean()), 4),
                             "rate_failure": round(float(v[~pos].mean()), 4),
                             "rate_diff": round(float(v[pos].mean() - v[~pos].mean()), 4)})

    df = pl.DataFrame(rows, infer_schema_length=None)
    df.write_parquet(OUT / "success_failure_separation.parquet")
    df.write_csv(OUT / "success_failure_separation.csv")

    print("=== continuous features, AUC (SUCCESS vs FAILURE) by landmark")
    piv = (df.filter(pl.col("kind") == "continuous")
           .select("landmark_s", "feature", "auc")
           .pivot(on="landmark_s", index="feature", values="auc"))
    print(piv)
    print("\n=== binary reach / persistence, success-minus-failure rate")
    piv2 = (df.filter(pl.col("kind") == "binary")
            .select("landmark_s", "feature", "rate_diff")
            .pivot(on="landmark_s", index="feature", values="rate_diff"))
    print(piv2)
    n = df.select("landmark_s", "n_alive", "n_success", "n_failure").unique().sort("landmark_s")
    print("\n", n)


if __name__ == "__main__":
    main()
