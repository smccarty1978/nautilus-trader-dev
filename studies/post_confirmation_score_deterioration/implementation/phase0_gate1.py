"""Gate 1 landmark test: does any post-confirmation score separate failures?

Probe 2 showed the in-domain new-regime score is unusable: it exists for 69.4%
of winners but only 7.7% of failures, because the established-regime gate opens
a median 352-448s after confirmation while failed trades die at a median
217-300s. Availability is determined by the outcome, which is an unfixable
selection bias, not a small-sample problem.

The only stream with complete coverage is the **raw, ungated** probability of the
model whose domain is the new regime. This module tests whether it carries
management information.

**That stream is read OUTSIDE the frozen model's domain contract, and almost
totally so at the early landmarks.** Quantified by the reconciliation against the
Codex replication (`reconciliation/landmark_availability_reconciliation.json`),
the share of evaluated trades holding a contract-valid in-domain score is:

    60s    0 of 4,594   (0.0%)
    120s   0 of 4,403   (0.0%)
    180s  61 of 3,908   (1.6%)
    300s 525 of 3,209  (16.4%)

The scores are genuine causally-available dispatches -- `*_score_is_new` is true
for 100% of rows, `*_score_available_ns - checkpoint_decision_ns == 0` for all
5,665,103 RTH rows, and nothing is carried forward or as-of joined. But the AUC
this module reports is **exploratory out-of-domain evidence, not deployable
evidence**, and must be cited as such.

The column was originally named `in_domain_score`, which was a misnomer -- it is
not gated on the `*_in_domain` flag -- and that name is the direct cause of an
apparent conflict with the Codex replication. Renamed `domain_model_raw_score`.

**Landmark design.** Everything is evaluated at a FIXED elapsed time from
confirmation, among trades still open at that time. This is deliberate:

  * It is the deployable question -- you can only act on a trade still open.
  * It removes the duration confound that has now bitten this research line
    twice (shape classes in the predecessor study, and the raw per-trade score
    maxima in probe 1, where winners' higher peak score was almost entirely an
    artifact of observing them for 111 dispatches versus 16 for losers).

Path-summary statistics over a window that ends at the terminal event cannot be
used for this question at all, and none are computed here.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
NS = 1_000_000_000

HORIZONS_S = (60, 120, 180, 300)
FAIL = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER")
WIN = ("FINAL_FLIP_EXIT_WINNER",)
LABELS = FAIL + WIN + ("SESSION_EXIT",)


def auc(scores: np.ndarray, positive: np.ndarray) -> float | None:
    """Rank AUC for `positive` (1 = failure) against `scores`. Ties averaged."""
    n_pos = int(positive.sum())
    n_neg = int((~positive.astype(bool)).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # average ties
    vals, inv, cnt = np.unique(scores, return_inverse=True, return_counts=True)
    sums = np.zeros(len(vals))
    np.add.at(sums, inv, ranks)
    ranks = (sums / cnt)[inv]
    return float((ranks[positive.astype(bool)].sum()
                  - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def build_panel() -> pl.DataFrame:
    paths = pl.read_parquet(PRIOR).filter(pl.col("valid"))
    regimes = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_id", "regime_direction", "regime_start_decision_ns")
        .collect()
    )
    conf = (
        paths.filter(
            pl.col("terminal_label_full").is_in(list(LABELS))
            & pl.col("walk_a_confirm_ns").is_not_null()
        )
        .select("regime_id", "direction", "side", "entry_year",
                "terminal_label_full", "walk_a_confirm_ns", "full_exit_ns",
                "full_mfe_atr", "full_gross_atr", "arm_atr")
        .join(
            regimes.rename({"regime_id": "new_regime_id"}),
            left_on=["walk_a_confirm_ns", "direction"],
            right_on=["regime_start_decision_ns", "regime_direction"],
            how="left",
        )
        .drop_nulls("new_regime_id")
        .with_columns(hold_s=((pl.col("full_exit_ns") - pl.col("walk_a_confirm_ns")) / NS))
    )

    scores = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("session") == "RTH")
        .select("regime_id", "checkpoint_decision_ns", "checkpoint_reference_price",
                "bullish_in_domain", "bullish_probability", "bearish_probability")
        .collect()
    )
    post = (
        scores.join(
            conf.select("new_regime_id", "direction", "side", "entry_year",
                        "terminal_label_full", "walk_a_confirm_ns",
                        "full_exit_ns", "full_mfe_atr", "arm_atr", "hold_s"),
            left_on="regime_id", right_on="new_regime_id", how="inner",
        )
        .filter(
            (pl.col("checkpoint_decision_ns") >= pl.col("walk_a_confirm_ns"))
            & (pl.col("checkpoint_decision_ns") <= pl.col("full_exit_ns"))
        )
        .with_columns(
            elapsed_s=((pl.col("checkpoint_decision_ns") - pl.col("walk_a_confirm_ns")) / NS),
            # In a regime of direction d, the in-domain model is bullish iff
            # d == +1 (established in probe 1 at rate 1.0). The other model is
            # out of domain and exploratory, but is populated regardless of the
            # established-regime gate.
            ood_score=pl.when(pl.col("direction") == 1)
            .then(pl.col("bearish_probability"))
            .otherwise(pl.col("bullish_probability")),
            domain_model_raw_score=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_probability"))
            .otherwise(pl.col("bearish_probability")),
        )
    )
    return post


def landmark(post: pl.DataFrame, horizon: int, col: str) -> dict:
    """State of `col` as of `horizon` seconds, among trades still open then."""
    alive = post.filter(pl.col("hold_s") > horizon)
    upto = alive.filter(
        (pl.col("elapsed_s") <= horizon) & pl.col(col).is_not_null()
    )
    if upto.height == 0:
        return {"horizon_s": horizon, "column": col, "n": 0}

    snap = (
        upto.sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .agg(
            label=pl.col("terminal_label_full").first(),
            side=pl.col("side").first(),
            year=pl.col("entry_year").first(),
            n_obs=pl.len(),
            first=pl.col(col).first(),
            last=pl.col(col).last(),
            peak=pl.col(col).max(),
            trough=pl.col(col).min(),
        )
        .with_columns(
            retreat_from_peak=(pl.col("peak") - pl.col("last")),
            change_from_first=(pl.col("last") - pl.col("first")),
        )
        .filter(pl.col("label").is_in(list(FAIL + WIN)))
    )
    if snap.height == 0:
        return {"horizon_s": horizon, "column": col, "n": 0}

    is_fail = np.isin(snap["label"].to_numpy(), FAIL)
    out = {
        "horizon_s": horizon,
        "column": col,
        "n": snap.height,
        "n_fail": int(is_fail.sum()),
        "n_win": int((~is_fail).sum()),
        "base_failure_rate": round(float(is_fail.mean()), 4),
        "median_obs_by_horizon": float(snap["n_obs"].median()),
        "auc": {},
        "median_by_outcome": {},
    }
    for feat in ("last", "peak", "retreat_from_peak", "change_from_first"):
        v = snap[feat].to_numpy().astype(float)
        ok = np.isfinite(v)
        a = auc(v[ok], is_fail[ok]) if ok.sum() > 10 else None
        out["auc"][feat] = round(a, 4) if a is not None else None
        out["median_by_outcome"][feat] = {
            "fail": round(float(np.median(v[ok & is_fail])), 4) if (ok & is_fail).any() else None,
            "win": round(float(np.median(v[ok & ~is_fail])), 4) if (ok & ~is_fail).any() else None,
        }
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    post = build_panel()
    report = {
        "design": (
            "Landmark: state evaluated at a fixed elapsed time from "
            "confirmation, among trades still open at that time. AUC target is "
            "FAILURE (CONFIRMED_THEN_STOPPED or FINAL_FLIP_EXIT_LOSER) versus "
            "FINAL_FLIP_EXIT_WINNER. 0.50 = no information."
        ),
        "ood_score": [],
        "domain_model_raw_score": [],
    }
    for h in HORIZONS_S:
        report["ood_score"].append(landmark(post, h, "ood_score"))
        report["domain_model_raw_score"].append(landmark(post, h, "domain_model_raw_score"))

    (OUT / "phase0_gate1.json").write_text(json.dumps(report, indent=2, default=str))
    for stream in ("ood_score", "domain_model_raw_score"):
        print(f"\n=== {stream}")
        for r in report[stream]:
            if not r.get("n"):
                print(f"  t={r['horizon_s']:>4}s  n=0")
                continue
            a = r["auc"]
            print(f"  t={r['horizon_s']:>4}s  n={r['n']:>5} "
                  f"(fail {r['n_fail']:>4} / win {r['n_win']:>5}, base {r['base_failure_rate']:.3f})  "
                  f"AUC last={a['last']} peak={a['peak']} "
                  f"retreat={a['retreat_from_peak']} delta={a['change_from_first']}")


if __name__ == "__main__":
    main()
