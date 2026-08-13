"""Model-B rung observations, continuation labels, and causal trade state.

The rung population is IMPORTED from the accepted
`post_confirm_profit_ratchet/results/rung_events.parquet`, never re-derived. The
trade window is rebuilt with the accepted `prepare()` so the bar arrays are the
same objects the accepted geometry was measured on, and the rung is then located
BY TIMESTAMP inside that window (never by trusting an index across two
implementations) and asserted to agree.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.top10_fast_confirm_runner_path.implementation.engine import prepare

from .common import B_ADVERSE, B_FAVOURABLE, HORIZONS_S, NS
from .features import PathContext, ScoreHistory, market_features, score_state

LABEL_NAMES_B: set[str] = set()

_RETROSPECTIVE = {
    "eventual_max_mfe_atr", "runner_bucket", "nat_terminal_return_atr",
    "unc_terminal_return_atr", "nat_terminal_ns", "unc_terminal_ns",
    "baseline_return_atr", "baseline_net_atr", "nat_giveback_atr",
    "nat_max_mfe_atr", "unc_kind", "nat_kind", "terminal_label",
    "secs_arm_to_nat_terminal", "secs_arm_to_unc_terminal",
}


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def load_rung_events(path, year: int = 2024) -> pl.DataFrame:
    ev = (pl.read_parquet(path)
          .filter((pl.col("entry_year") == year) & (pl.col("basis") == "POST_CONFIRM"))
          .sort(["regime_id", "rung_atr"]))
    return ev


def _continuation_labels(w, r: int, hwm: float, unc_i: int, rung_ts: int) -> dict:
    """Forward barrier labels from the causal state at the rung bar.

    PRIMARY (the brief's B2): both barriers are STATIC levels set at the rung --
    favourable = HWM + f, adverse = HWM - a. This is a clean question about the
    forward path from a known state.

    SECONDARY: a RATCHETING adverse barrier trailing the causal running high-water
    mark through the PREVIOUS completed bar, which is the accepted ratchet study's
    D4 geometry. `run_mfe[k-1]` is used deliberately: a bar that both sets a new
    high and breaches the trailing level counts as adverse, because letting the
    bar's own high raise the level before its own low tests it is a same-bar
    look-ahead.
    """
    out: dict = {}
    hi = w.bar_hi
    lo = w.bar_lo
    ts = w.ts
    prev_hwm = np.concatenate(([hwm], np.maximum.accumulate(
        np.maximum(hi[r + 1:unc_i + 1], hwm))[:-1])) if unc_i > r else np.zeros(0)

    for H in HORIZONS_S:
        stop = min(int(np.searchsorted(ts, rung_ts + H * NS, side="right")) - 1, unc_i)
        seg = slice(r + 1, stop + 1)
        n = max(0, stop - r)
        f_hi = hi[seg]
        f_lo = lo[seg]
        for f in B_FAVOURABLE:
            fi = _first(f_hi >= hwm + f) if n else -1
            for a in B_ADVERSE:
                ai = _first(f_lo <= hwm - a) if n else -1
                tag = f"f{f:.2f}_a{a:.2f}_{H}".replace(".", "")
                if fi < 0 and ai < 0:
                    lab, opt = "TIMEOUT", "TIMEOUT"
                elif ai < 0:
                    lab, opt = "FAVOURABLE", "FAVOURABLE"
                elif fi < 0:
                    lab, opt = "ADVERSE", "ADVERSE"
                elif fi < ai:
                    lab, opt = "FAVOURABLE", "FAVOURABLE"
                elif ai < fi:
                    lab, opt = "ADVERSE", "ADVERSE"
                else:
                    lab, opt = "ADVERSE", "FAVOURABLE"   # same-bar -> adverse
                out[f"lab_{tag}"] = lab
                out[f"lab_{tag}_optimistic"] = opt
                # RATCHETING variant, primary favourable only.
                if f == 0.50:
                    if n:
                        ph = prev_hwm[:n]
                        ri = _first(f_lo <= ph - a)
                        rl = ("TIMEOUT" if fi < 0 and ri < 0 else
                              "FAVOURABLE" if ri < 0 or (fi >= 0 and fi < ri) else "ADVERSE")
                    else:
                        rl = "TIMEOUT"
                    out[f"labratchet_{tag}"] = rl
        out[f"fwd_mfe_{H}"] = float(max(0.0, f_hi.max() - hwm)) if n else 0.0
        out[f"fwd_mae_{H}"] = float(max(0.0, hwm - f_lo.min())) if n else 0.0
        out[f"fwd_bars_{H}"] = int(n)
    return out


def build_observations(events: pl.DataFrame, market, regimes, regime_tbl: pl.DataFrame,
                       scores: pl.DataFrame, hist: ScoreHistory, thresholds: dict):
    """One row per rung event: causal features + forward continuation labels."""
    path = PathContext(market)
    feat_cols = [c for c in scores.columns if c.startswith(("bullish__", "bearish__"))]
    fcache = {c: scores[c].to_numpy() for c in feat_cols}
    key_ns = scores["score_decision_ns"].to_numpy()
    key_rid = np.asarray(scores["regime_id"].to_list(), dtype=object)
    order = np.lexsort((key_ns, key_rid))

    rstart = regime_tbl["regime_start_decision_ns"].to_numpy()
    rid_arr = np.asarray(regime_tbl["regime_id"].to_list(), dtype=object)

    wcache: dict[str, object] = {}
    rows, feats, dropped = [], [], {"no_window": 0, "rung_not_found": 0, "hwm_mismatch": 0}

    for ev in events.iter_rows(named=True):
        rid = ev["regime_id"]
        w = wcache.get(rid)
        if w is None:
            w = prepare(market, regimes, {
                "entry_ns": ev["entry_ns"], "direction": ev["direction"],
                "entry_price": ev["entry_price"], "entry_atr": ev["entry_atr"],
                "confirm_ns": ev["confirm_ns"], "regime_id": rid,
            })
            if w is None:
                dropped["no_window"] += 1
                continue
            wcache[rid] = w
        r = int(np.searchsorted(w.ts, int(ev["rung_ts"]), side="left"))
        if r >= w.ts.size or int(w.ts[r]) != int(ev["rung_ts"]):
            dropped["rung_not_found"] += 1
            continue
        hwm = float(w.run_mfe[r])
        if abs(hwm - float(ev["hwm_at_arm_atr"])) > 1e-9:
            dropped["hwm_mismatch"] += 1
            continue

        rung_ts = int(ev["rung_ts"])
        d = int(ev["direction"])
        lab = _continuation_labels(w, r, hwm, int(w.unc_i), rung_ts)
        lab.update({
            "regime_id": rid, "rung_atr": float(ev["rung_atr"]), "side": ev["side"],
            "direction": d, "rung_ts": rung_ts, "entry_ns": int(ev["entry_ns"]),
            "stop_live_reachable": bool(ev["stop_live_reachable"]),
            "eventual_max_mfe_atr": float(ev["eventual_max_mfe_atr"]),
            "runner_bucket": ev["runner_bucket"],
            "nat_terminal_return_atr": float(ev["nat_terminal_return_atr"]),
            "unc_terminal_return_atr": float(ev["unc_terminal_return_atr"]),
            "entry_atr": float(ev["entry_atr"]),
        })
        rows.append(lab)

        # ---------------- causal features at the rung bar ------------------
        ci = int(w.ci)
        f: dict = {
            "regime_id": rid, "rung_ts": rung_ts, "rung_atr": float(ev["rung_atr"]),
            "side": ev["side"], "is_long": int(d > 0),
            "current_mfe_atr": hwm,
            "hwm_at_arm_atr": hwm,
            "return_from_entry_atr": float(w.mark[r]),
            "return_since_confirm_atr": float(w.mark[r] - w.mark[ci]),
            "drawdown_from_hwm_atr": float(hwm - w.mark[r]),
            "rung_overshoot_atr": float(ev["rung_overshoot_atr"]),
            "seconds_since_confirm": float((rung_ts - int(ev["confirm_ns"])) / NS),
            "seconds_since_entry": float((rung_ts - int(ev["entry_ns"])) / NS),
            "entry_atr": float(ev["entry_atr"]),
            "mfe_at_confirm_atr": float(w.run_mfe[ci]),
            "mae_at_confirm_atr": float(w.run_mae[ci]),
            "return_at_confirm_atr": float(w.mark[ci]),
        }
        le = int(w.last_ext[r])
        anchor = le if le >= 0 else 0
        f["seconds_since_last_favourable_extreme"] = float(
            (int(w.ts[r]) - int(w.ts[anchor])) / NS)
        f["n_recent_favourable_extremes"] = int(w.new_ext[max(ci, 0):r + 1].sum())
        for W in (15, 30, 60):
            j = int(np.searchsorted(w.ts, rung_ts - W * NS, side="left"))
            if j <= r:
                f[f"progress_{W}s_atr"] = float(w.run_mfe[r] - w.run_mfe[j])
                f[f"adverse_progress_{W}s_atr"] = float(w.run_mae[r] - w.run_mae[j])
                f[f"mark_progress_{W}s_atr"] = float(w.mark[r] - w.mark[j])
            else:
                f[f"progress_{W}s_atr"] = None
                f[f"adverse_progress_{W}s_atr"] = None
                f[f"mark_progress_{W}s_atr"] = None

        # Post-confirmation the prevailing regime has flipped INTO the trade, so
        # the model in domain is the OPPOSITE one -- the model whose flip would
        # END this trade. That is the causally correct exit-warning score.
        exit_model = "BEARISH" if d < 0 else "BULLISH"
        exit_side = "LONG" if exit_model == "BEARISH" else "SHORT"
        k = int(np.searchsorted(rstart, rung_ts, side="right")) - 1
        prevailing = str(rid_arr[k]) if k >= 0 else None
        f["prevailing_regime_id_known"] = int(prevailing is not None)
        if prevailing is not None:
            st = score_state(hist, prevailing, rung_ts, thresholds, exit_side,
                             prefix="exit_")
            f.update(st)
            f["exit_warning_in_domain"] = int(bool(st))
            mkt = _market_at(prevailing, rung_ts, key_rid, key_ns, order, fcache,
                             exit_model)
            f.update(mkt)
            f["market_features_available"] = int(bool(mkt))
        else:
            f["exit_warning_in_domain"] = 0
            f["market_features_available"] = 0
        f.update(path.features(rung_ts, d, float(ev["entry_atr"]),
                               int(ev["entry_ns"]), anchor_label="entry"))
        feats.append(f)

    obs = pl.DataFrame(rows)
    fx = pl.DataFrame(feats)
    LABEL_NAMES_B.update(c for c in obs.columns
                         if c.startswith(("lab_", "labratchet_", "fwd_")))
    LABEL_NAMES_B.update(_RETROSPECTIVE)
    return obs, fx, dropped


def _market_at(regime_id: str, t0: int, key_rid, key_ns, order, fcache, model: str) -> dict:
    """The 25 inline features of `model` at its last dispatch <= t0 in `regime_id`."""
    lo = int(np.searchsorted(key_rid[order], regime_id, side="left"))
    hi = int(np.searchsorted(key_rid[order], regime_id, side="right"))
    if hi <= lo:
        return {}
    blk = order[lo:hi]
    ns = key_ns[blk]
    i = int(np.searchsorted(ns, t0, side="right")) - 1
    if i < 0:
        return {}
    row_i = int(blk[i])
    pre = "bullish" if model == "BULLISH" else "bearish"
    out = {}
    for c, arr in fcache.items():
        if c.startswith(f"{pre}__"):
            v = arr[row_i]
            out[c.removeprefix(f"{pre}__")] = None if v is None else v
    if all(v is None or (isinstance(v, float) and np.isnan(v)) for v in out.values()):
        return {}
    return out
