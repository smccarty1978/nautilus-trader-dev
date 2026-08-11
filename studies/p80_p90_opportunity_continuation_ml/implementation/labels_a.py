"""Model-A forward labels and geometry. LABELS ONLY -- never features (gate V4).

Every window here begins at ``index_strictly_after(candidate_ns)``: the first 1s
bar that STARTS at or after the decision second. The bar completing AT the
decision second covers [t-1s, t) and is already known, so it belongs to the
feature side; admitting it to the label side would price the decision on its own
outcome bar.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    MarketData, RegimeIndex,
)

from .common import HORIZONS_S, NS, REWARD_ATR, RISK_ATR

# Names produced by this module. Gate V4 intersects every feature matrix with
# this set and requires the intersection to be EMPTY.
LABEL_NAMES: set[str] = set()


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def _classify(fav_i: int, adv_i: int) -> tuple[str, str, bool]:
    """(primary label, optimistic label, is_ambiguous).

    Intrabar ordering is unknowable from OHLC. A bar that touches both barriers is
    AMBIGUOUS; the primary economic reading is LOSS and the optimistic bound is
    reported alongside -- never instead.
    """
    if fav_i < 0 and adv_i < 0:
        return "TIMEOUT", "TIMEOUT", False
    if adv_i < 0:
        return "WIN", "WIN", False
    if fav_i < 0:
        return "LOSS", "LOSS", False
    if fav_i < adv_i:
        return "WIN", "WIN", False
    if adv_i < fav_i:
        return "LOSS", "LOSS", False
    return "LOSS", "WIN", True


def walk_candidate(market: MarketData, regimes: RegimeIndex, cand: dict) -> dict | None:
    """Forward geometry for one candidate. Returns None if the window is empty."""
    t0 = int(cand["candidate_ns"])
    d = int(cand["direction"])
    px = float(cand["reference_price_at_candidate"])
    atr = float(cand["frozen_atr"])

    start = market.index_strictly_after(t0)
    if start >= market.n:
        return None
    # Only RTH bars are loaded, so consecutive indices jump the overnight gap.
    # Clamping to the candidate's own session is what enforces the 15:00 CT flat.
    sess_end = int(np.searchsorted(market.day_close_ns,
                                   market.day_close_ns[start], side="right"))
    close_ns = int(market.day_close_ns[start])

    opposing_ns = regimes.next_start_after(t0, -d, inclusive=True)
    confirm_ns = regimes.next_start_after(t0, d, inclusive=True)
    horizon_ns = close_ns if opposing_ns is None else min(close_ns, opposing_ns)
    unc_end = min(int(np.searchsorted(market.ts, horizon_ns, side="right")),
                  sess_end, market.n)
    if unc_end <= start:
        return None

    hi = market.high[start:unc_end]
    lo = market.low[start:unc_end]
    ts = market.ts[start:unc_end]
    fav = ((hi - px) if d > 0 else (px - lo)) / atr
    adv = ((px - lo) if d > 0 else (hi - px)) / atr

    out: dict = {
        "regime_id": cand["regime_id"], "prime_type": cand["prime_type"],
        "candidate_ns": t0, "side": cand["side"], "direction": d,
        "n_forward_bars_unconstrained": int(ts.size),
    }

    # ---- barrier labels at each frozen horizon ---------------------------
    for H in HORIZONS_S:
        stop = int(np.searchsorted(ts, t0 + H * NS, side="right"))
        f_i = _first(fav[:stop] >= REWARD_ATR)
        a_i = _first(adv[:stop] >= RISK_ATR)
        primary, optimistic, ambiguous = _classify(f_i, a_i)
        seg_fav = fav[:stop]
        seg_adv = adv[:stop]
        out[f"label_{H}"] = primary
        out[f"label_{H}_optimistic"] = optimistic
        out[f"ambiguous_{H}"] = ambiguous
        out[f"resolved_{H}"] = primary != "TIMEOUT"
        out[f"mfe_{H}"] = float(max(0.0, seg_fav.max())) if stop > 0 else 0.0
        out[f"mae_{H}"] = float(max(0.0, seg_adv.max())) if stop > 0 else 0.0
        out[f"n_bars_{H}"] = int(stop)
        out[f"truncated_by_session_{H}"] = bool(stop < ts.size
                                                and int(ts[stop - 1]) < t0 + H * NS
                                                if stop > 0 else True)

    # ---- times to barrier, over the UNCONSTRAINED window ------------------
    f_all = _first(fav >= REWARD_ATR)
    a_all = _first(adv >= RISK_ATR)
    out["time_to_reward_s"] = float((int(ts[f_all]) - t0) / NS) if f_all >= 0 else None
    out["time_to_risk_s"] = float((int(ts[a_all]) - t0) / NS) if a_all >= 0 else None

    # ---- regime diagnostics (NOT part of any target) ---------------------
    reached_opp = opposing_ns is not None and int(ts[-1]) >= opposing_ns - NS
    out["terminal_regime_outcome"] = "OPPOSING_FLIP" if reached_opp else "SESSION"
    out["eventual_mfe_atr"] = float(max(0.0, fav.max()))
    out["eventual_mae_atr"] = float(max(0.0, adv.max()))
    if confirm_ns is not None and confirm_ns <= int(ts[-1]):
        secs = float((confirm_ns - t0) / NS)
        out["confirm_flip_occurred"] = True
        out["seconds_to_confirm_flip"] = secs
        for H in HORIZONS_S:
            out[f"confirmed_before_{H}"] = bool(secs <= H)
    else:
        out["confirm_flip_occurred"] = False
        out["seconds_to_confirm_flip"] = None
        for H in HORIZONS_S:
            out[f"confirmed_before_{H}"] = False

    # ---- REF_NEXT_OPEN sensitivity (SPEC 4.3) ----------------------------
    # The accepted lineage anchors at the checkpoint reference price. This is the
    # H4-style alternative: price the opportunity from the open of the first bar
    # that could actually have been traded. Reported, never substituted.
    px2 = float(market.open_[start])
    fav2 = ((hi - px2) if d > 0 else (px2 - lo)) / atr
    adv2 = ((px2 - lo) if d > 0 else (hi - px2)) / atr
    stop = int(np.searchsorted(ts, t0 + 300 * NS, side="right"))
    p2, _, _ = _classify(_first(fav2[:stop] >= REWARD_ATR),
                         _first(adv2[:stop] >= RISK_ATR))
    out["label_300_ref_next_open"] = p2
    out["ref_next_open_price"] = px2
    out["ref_slippage_atr"] = float((px2 - px) * d / atr)
    return out


def build_forward_labels(market, regimes, cand: pl.DataFrame) -> pl.DataFrame:
    rows, dropped = [], 0
    for c in cand.iter_rows(named=True):
        r = walk_candidate(market, regimes, c)
        if r is None:
            dropped += 1
            continue
        rows.append(r)
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.lit(dropped).alias("_n_dropped_no_window"))
    LABEL_NAMES.update(c for c in df.columns if c not in
                       ("regime_id", "prime_type", "candidate_ns", "side", "direction"))
    return df.drop("_n_dropped_no_window"), dropped
