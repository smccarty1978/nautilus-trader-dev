"""The control that decides this study: is the score doing the work?

`gate2_ledger.py` shows that acting on a stream-B flag is net-positive in ATR at
nearly every operating point. That result cannot be taken at face value, for a
specific and well-documented reason.

The counterfactual baseline is *holding to the opposing flip*, and the
predecessor study already established that this is a poor exit -- it was the
worst-capture exit of the eighteen it screened, and its headline recommendation
was "exit at thesis confirmation, not at the opposing flip". So **any** rule that
exits earlier may look profitable without containing a single bit of information.
This research line has already killed one branch for exactly this failure
(`contextual_runner_exit_v3_investigate`: stop timing fails placebo).

Two controls, both matched to the score rule's flag count at each landmark:

* **RANDOM** -- flag a random subset of the alive population. Isolates the value
  of simply exiting early. Run over many draws to get a distribution, so the
  comparison is against a spread rather than a point.

* **WORST_PNL** -- flag the trades with the most negative open PnL at the
  landmark. This is the sharper control. The score flag preferentially selects
  trades that are already losing (median open PnL at flag is negative at every
  early landmark), and exiting a losing trade early is mechanically good when the
  baseline is a 1 ATR stop. If ranking on open PnL alone matches the score, the
  score adds nothing beyond "this trade is currently down".

The score earns its keep only if it beats BOTH.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from .gate2_ledger import HORIZONS, QUANTILES, attach_terminal_gross, snapshot

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
PANEL = OUT / "post_confirm_paths.parquet"

WINNER = "FINAL_FLIP_EXIT_WINNER"
N_DRAWS = 400
SEED = 20260810


def net_atr(flagged: pl.DataFrame) -> tuple[float, float, float]:
    d = (flagged["open_pnl_atr"] - flagged["final_pnl_atr"]).to_numpy()
    is_fail = flagged["is_failure"].to_numpy().astype(bool)
    return float(d.sum()), float(d[is_fail].sum()), float(d[~is_fail].sum())


def main() -> None:
    panel = attach_terminal_gross(pl.read_parquet(PANEL))
    rng = np.random.default_rng(SEED)
    report = {
        "method": (
            "Both controls are matched to the score rule's flag count at each "
            "landmark. RANDOM isolates the value of exiting early at all; "
            "WORST_PNL isolates whether the score adds anything beyond 'the "
            "trade is currently losing'. The score must beat both."
        ),
        "n_random_draws": N_DRAWS,
        "seed": SEED,
        "horizons": [],
    }

    for h in HORIZONS:
        snap = snapshot(panel, h)
        if snap.height == 0:
            continue
        snap = snap.with_columns(
            delta_atr=(pl.col("open_pnl_atr") - pl.col("final_pnl_atr"))
        )
        delta = snap["delta_atr"].to_numpy()
        pnl = snap["open_pnl_atr"].to_numpy()
        score = snap["score_b"].to_numpy()
        n = snap.height

        block = {"horizon_s": h, "n_alive": n, "operating_points": []}
        for q in QUANTILES:
            cutoff = float(np.quantile(score, q))
            sel = score >= cutoff
            k = int(sel.sum())
            if k == 0:
                continue
            actual = float(delta[sel].sum())

            # RANDOM control
            draws = np.empty(N_DRAWS)
            for i in range(N_DRAWS):
                idx = rng.choice(n, size=k, replace=False)
                draws[i] = delta[idx].sum()
            pct = float((draws < actual).mean())

            # WORST_PNL control: the k most-negative open PnL trades
            worst = np.argsort(pnl, kind="mergesort")[:k]
            worst_net = float(delta[worst].sum())

            block["operating_points"].append({
                "quantile": q,
                "n_flagged": k,
                "score_net_atr": round(actual, 2),
                "random_net_atr_mean": round(float(draws.mean()), 2),
                "random_net_atr_p05": round(float(np.percentile(draws, 5)), 2),
                "random_net_atr_p95": round(float(np.percentile(draws, 95)), 2),
                "score_percentile_vs_random": round(pct, 4),
                "beats_random_95": bool(actual > np.percentile(draws, 95)),
                "worst_pnl_net_atr": round(worst_net, 2),
                "score_minus_worst_pnl": round(actual - worst_net, 2),
                "beats_worst_pnl": bool(actual > worst_net),
            })
        report["horizons"].append(block)

        print(f"\n=== t={h}s  alive={n:,}")
        print(f"    {'q':>5} {'k':>6} {'score':>9} {'rand_mu':>9} {'rand_p95':>9} "
              f"{'pct':>6} {'worstPnL':>9} {'score-worst':>12}")
        for p in block["operating_points"]:
            print(f"    {p['quantile']:>5} {p['n_flagged']:>6} "
                  f"{p['score_net_atr']:>9} {p['random_net_atr_mean']:>9} "
                  f"{p['random_net_atr_p95']:>9} {p['score_percentile_vs_random']:>6} "
                  f"{p['worst_pnl_net_atr']:>9} {p['score_minus_worst_pnl']:>12}")

    (OUT / "placebo.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nwrote placebo.json")


if __name__ == "__main__":
    main()
