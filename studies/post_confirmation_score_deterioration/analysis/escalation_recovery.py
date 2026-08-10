"""Phase 5: is the escalation temporary? Plus two manifest path-drift fixes.

The brief asks whether a deterioration signal is often followed by the score
recovering and the regime continuing -- i.e. whether acting on the flag would
frequently eject a trade that was never really in trouble. That question is only
meaningful against the landmark flag, because the path-threshold events fire on
~100% of trades and have nothing to recover from.

Definition, causal throughout: a trade flagged at a landmark (score_b >= cutoff)
**recovers** if score_b subsequently falls back below that same cutoff before the
terminal event. Recovery is measured strictly after the flag.

Also emits, per contract-checker pass 1:
  * `landmark_features.json` -- manifest item 8, whose content shipped under the
    filename `phase0_gate1.json`.
  * `divergence.json`        -- manifest item 11, whose content shipped as one
    embedded row inside `deterioration_event_table.json`.
Both are path drift, not missing work; the files are written to the manifest
names rather than the manifest being quietly amended to match the code.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from .gate2_ledger import attach_terminal_gross

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
PANEL = OUT / "post_confirm_paths.parquet"

WINNER = "FINAL_FLIP_EXIT_WINNER"
HORIZONS = (60, 120, 180, 300)
QUANTILES = (0.70, 0.85, 0.95)


def recovery_block(panel: pl.DataFrame, horizon: int) -> dict:
    alive = panel.filter(pl.col("hold_s") > horizon)
    upto = alive.filter(pl.col("elapsed_s") <= horizon)
    if upto.height == 0:
        return {}
    snap = (
        upto.sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .agg(
            terminal_label=pl.col("terminal_label").first(),
            is_failure=pl.col("is_failure").first(),
            full_mfe_atr=pl.col("full_mfe_atr").first(),
            score_b=pl.col("score_b").last(),
            open_pnl_atr=pl.col("open_pnl_atr_conf").last(),
        )
        .filter(pl.col("terminal_label").is_not_null())
    )
    vals = snap["score_b"].to_numpy()

    points = []
    for q in QUANTILES:
        cutoff = float(np.quantile(vals, q))
        flagged = snap.filter(pl.col("score_b") >= cutoff)
        if flagged.height == 0:
            continue
        # Did the score fall back below the cutoff after the landmark?
        after = (
            alive.filter(
                pl.col("elapsed_s") > horizon
                & pl.col("regime_id").is_in(flagged["regime_id"].to_list())
            )
            if False else
            alive.filter(pl.col("elapsed_s") > horizon)
                 .filter(pl.col("regime_id").is_in(flagged["regime_id"].to_list()))
        )
        rec = (
            after.group_by("regime_id")
            .agg(min_score_after=pl.col("score_b").min(),
                 max_pnl_after=pl.col("open_pnl_atr_conf").max())
        )
        j = flagged.join(rec, on="regime_id", how="left").with_columns(
            recovered=(pl.col("min_score_after") < cutoff),
            remaining_mfe_atr=(pl.col("max_pnl_after").fill_null(pl.col("open_pnl_atr"))
                               - pl.col("open_pnl_atr")),
        )
        r = j.filter(pl.col("recovered").fill_null(False))
        nr = j.filter(~pl.col("recovered").fill_null(False))
        big = j.filter(pl.col("full_mfe_atr") >= 2.5)
        big_r = big.filter(pl.col("recovered").fill_null(False))
        points.append({
            "quantile": q,
            "score_cutoff": round(cutoff, 4),
            "n_flagged": j.height,
            "n_recovered": r.height,
            "recovery_rate": round(r.height / j.height, 4),
            "failure_rate_if_recovered": (
                round(float(r["is_failure"].mean()), 4) if r.height else None),
            "failure_rate_if_not_recovered": (
                round(float(nr["is_failure"].mean()), 4) if nr.height else None),
            "median_remaining_mfe_if_recovered": (
                round(float(r["remaining_mfe_atr"].median()), 4) if r.height else None),
            "median_remaining_mfe_if_not_recovered": (
                round(float(nr["remaining_mfe_atr"].median()), 4) if nr.height else None),
            "ge_2_5atr_runners_flagged": big.height,
            "ge_2_5atr_runners_that_recovered": big_r.height,
            "ge_2_5atr_recovery_rate": (
                round(big_r.height / big.height, 4) if big.height else None),
        })
    return {"horizon_s": horizon, "n_alive": snap.height, "operating_points": points}


def main() -> None:
    panel = attach_terminal_gross(pl.read_parquet(PANEL))

    blocks = [b for b in (recovery_block(panel, h) for h in HORIZONS) if b]
    (OUT / "escalation_recovery.json").write_text(json.dumps({
        "question": (
            "When the landmark flag fires, how often does the score recover "
            "(fall back below the same cutoff) before the trade ends -- i.e. how "
            "often would acting on the flag eject a trade that was not really in "
            "trouble?"
        ),
        "definition": (
            "Flagged at horizon t if score_b >= the q-quantile of the alive "
            "cross-section at t. Recovered if score_b subsequently falls back "
            "below that same cutoff strictly after t and before the terminal."
        ),
        "note": (
            "Only defined against the landmark flag. The path-threshold events "
            "fire on ~100% of trades and have nothing to recover from."
        ),
        "horizons": blocks,
    }, indent=2, default=str))

    # --- manifest path-drift fixes (contract-checker pass 1) ---------------
    g1 = json.loads((OUT / "phase0_gate1.json").read_text())
    (OUT / "landmark_features.json").write_text(json.dumps({
        "note": "Manifest item 8. Content generated by "
                "implementation/phase0_gate1.py and originally written to "
                "phase0_gate1.json; emitted here under the manifest name.",
        **g1,
    }, indent=2, default=str))

    tbl = json.loads((OUT / "deterioration_event_table.json").read_text())
    div = [e for e in tbl["events"] if e["event"].startswith("DIVERGENCE")]
    (OUT / "divergence.json").write_text(json.dumps({
        "note": "Manifest item 11. Phase 3 price/score divergence, extracted "
                "from deterioration_event_table.json.",
        "definition": (
            "Price sets a new favorable extreme for the trade while stream B "
            "simultaneously sets a new high -- the regime is still paying, but "
            "the model's conviction that it is about to end is at its worst so "
            "far. Simplest interpretable form; no parameter search."
        ),
        "base_failure_rate": tbl["base_failure_rate"],
        "verdict": (
            "NULL. Fires on 157 trades at precision 0.338, BELOW the 0.481 base "
            "rate -- it weakly predicts winners, not failures."
        ),
        "events": div,
    }, indent=2, default=str))

    for b in blocks:
        print(f"\n=== t={b['horizon_s']}s  alive={b['n_alive']:,}")
        for p in b["operating_points"]:
            print(f"  q={p['quantile']}  flagged={p['n_flagged']:>5}  "
                  f"recovery={p['recovery_rate']:.3f}  "
                  f"fail|rec={p['failure_rate_if_recovered']}  "
                  f"fail|no-rec={p['failure_rate_if_not_recovered']}  "
                  f">=2.5ATR rec={p['ge_2_5atr_recovery_rate']}")
    print("\nwrote escalation_recovery.json, landmark_features.json, divergence.json")


if __name__ == "__main__":
    main()
