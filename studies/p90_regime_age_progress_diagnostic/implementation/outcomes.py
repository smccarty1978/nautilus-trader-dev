"""The three outcomes, simulated ONCE per distinct (regime_id, arm_ns) event.

All three are LABELS. None of them may enter a bucket definition or a row filter
(SPEC 4, gate V-LABEL):

    Outcome 1  P(prevailing 1m regime flips within 300s)  -- the model's real target
    Outcome 2  P(accepted opposite confirmation before a 1 ATR stop)
    Outcome 3  eventual MaxMFE in the trade direction, for confirmers only

Outcomes 2 and 3 reuse already-audited engines verbatim -- ``measure_to_confirm``
from the accepted arm study and ``prepare`` from the accepted runner-path study.
Nothing about the walk is re-derived here; this module only chooses the entry and
records the result.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.armed_fade_score_path_progression.implementation.walks import (
    CONFIRMED,
    measure_to_confirm,
)
from studies.model_driven_entry_exit_discovery.implementation.engine import (
    NS,
    STORE,
    MarketData,
    RegimeIndex,
    load_market,
    load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.engine import prepare

FLIP_HORIZONS_S = (120, 180, 300)
MFE_TIERS = (1.0, 2.0, 3.0)


def load_regime_ends() -> pl.DataFrame:
    """Prevailing-regime end times -- Outcome 1's label source.

    `regime_end_decision_ns` is NULL for the 54 `sealed_boundary_censored` regimes
    (dataset/partition boundaries). Those are right-censored, mirroring the training
    labeller's own `dataset_end_unresolved_action: right_censor`. They are never
    imputed and never counted as "did not flip" (SPEC 4.1).
    """
    return pl.read_parquet(
        STORE / "canonical_regimes_all.parquet",
        columns=["regime_id", "regime_start_decision_ns", "regime_end_decision_ns",
                 "regime_end_reason", "regime_direction"],
    )


def check_tiling(ends: pl.DataFrame, armed_ids: set[str], regimes: RegimeIndex) -> dict:
    """Gate V-TILE: the prevailing regime's end IS the next regime start.

    Checked against the independently-built `RegimeIndex` rather than assumed, and
    only on armed regimes with a non-null end. Regimes tile time and strictly
    alternate, so this is what makes "the prevailing regime flipped" and "the next
    regime started" the same event -- the identity Outcome 1 depends on.
    """
    sub = ends.filter(pl.col("regime_id").is_in(list(armed_ids)))
    non_null = sub.filter(pl.col("regime_end_decision_ns").is_not_null())
    starts = regimes.start_ns
    s = non_null["regime_start_decision_ns"].to_numpy()
    e = non_null["regime_end_decision_ns"].to_numpy()
    idx = np.searchsorted(starts, s, side="left")
    nxt = np.where(idx + 1 < starts.size, starts[np.minimum(idx + 1, starts.size - 1)], -1)
    mismatches = int(np.count_nonzero(nxt != e))
    return {
        "n_armed_regimes": len(armed_ids),
        "n_checked": int(non_null.height),
        "n_null_end_censored": int(sub.height - non_null.height),
        "n_mismatches": mismatches,
        "pass": mismatches == 0,
    }


def simulate(events: pl.DataFrame, market: MarketData, regimes: RegimeIndex,
             ends: pl.DataFrame, progress_every: int = 1000) -> pl.DataFrame:
    """One row per distinct (regime_id, arm_ns) event, carrying all three outcomes.

    Simulating the union ONCE and joining it onto both populations is what
    guarantees A and B report identical numbers for a shared event. Recomputing per
    population would let a subtle window difference manufacture a difference that is
    really just two code paths.
    """
    end_map = {
        r["regime_id"]: r["regime_end_decision_ns"]
        for r in ends.select("regime_id", "regime_end_decision_ns").iter_rows(named=True)
    }

    rows: list[dict] = []
    n = events.height
    for i, ev in enumerate(events.iter_rows(named=True)):
        if progress_every and i % progress_every == 0:
            print(f"  simulate {i}/{n}", flush=True)

        rid = ev["regime_id"]
        arm_ns = int(ev["checkpoint_decision_ns"])
        d = int(ev["direction"])
        px = ev["checkpoint_reference_price"]
        atr = ev["atr_at_checkpoint"]

        out: dict = {"regime_id": rid, "checkpoint_decision_ns": arm_ns}

        # ---- Outcome 1: the model's literal training target --------------
        flip_ns = end_map.get(rid)
        out["flip_censored"] = flip_ns is None
        if flip_ns is None:
            out["seconds_to_prevailing_flip"] = None
            for h in FLIP_HORIZONS_S:
                out[f"flip_le_{h}s"] = None
        else:
            dt = (int(flip_ns) - arm_ns) / NS
            out["seconds_to_prevailing_flip"] = float(dt)
            # Half-open (T, T+X], matching the training labeller exactly.
            for h in FLIP_HORIZONS_S:
                out[f"flip_le_{h}s"] = bool(0.0 < dt <= float(h))

        # Session disclosure -- reported, never used to filter Outcome 1 (SPEC 4.1).
        start = market.index_strictly_after(arm_ns)
        if start < market.n:
            close_ns = int(market.day_close_ns[start])
            secs_close = (close_ns - arm_ns) / NS
            out["secs_to_session_close"] = float(secs_close)
            out["flip_window_crosses_session_close"] = bool(secs_close < 300.0)
            out["flip_le_300s_session_gated"] = (
                None if flip_ns is None
                else bool(0.0 < (int(flip_ns) - arm_ns) / NS <= 300.0
                          and int(flip_ns) <= close_ns)
            )
        else:
            out["secs_to_session_close"] = None
            out["flip_window_crosses_session_close"] = None
            out["flip_le_300s_session_gated"] = None

        # ---- Outcome 2: accepted Walk-A trade path -----------------------
        w = measure_to_confirm(market, regimes, arm_ns, d, px, atr)
        out["terminal_label"] = w.get("terminal_label")
        out["walk_valid"] = bool(w.get("valid", False))
        out["ambiguous"] = bool(w.get("ambiguous", False))
        confirmed = bool(w.get("valid") and w.get("terminal_label") == CONFIRMED)
        out["confirmed"] = confirmed
        out["seconds_to_confirm"] = w.get("seconds_to_confirm")
        out["mae_to_confirm_atr"] = w.get("mae_to_confirm_atr")
        out["return_at_confirm_atr"] = w.get("return_at_confirm_atr")

        # ---- Outcome 3: eventual MaxMFE, confirmers only, UNCONSTRAINED --
        out["eventual_max_mfe_atr"] = None
        for t in MFE_TIERS:
            out[f"mfe_ge_{str(t).replace('.', '_')}"] = None
        if confirmed and w.get("confirm_ns") is not None:
            win = prepare(market, regimes, {
                "entry_ns": arm_ns, "direction": d, "entry_price": px,
                "entry_atr": atr, "confirm_ns": int(w["confirm_ns"]),
            })
            if win is not None:
                ev_mfe = float(win.run_mfe[win.unc_i])
                out["eventual_max_mfe_atr"] = ev_mfe
                for t in MFE_TIERS:
                    out[f"mfe_ge_{str(t).replace('.', '_')}"] = bool(ev_mfe >= t)

        rows.append(out)

    return pl.DataFrame(rows, infer_schema_length=None)


def load_engines():
    print("loading RTH 1s path + regime index ...", flush=True)
    return load_market(), load_regimes()
