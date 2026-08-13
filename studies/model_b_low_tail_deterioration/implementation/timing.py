"""Phase 7 timing re-derivation, and its self-verification gate (V7).

`_continuation_labels` in the predecessor persisted `fwd_mfe / fwd_mae / fwd_bars` but
threw away the first-hit INDICES, so "how long until the next favourable extreme" and
"how long until the adverse barrier" cannot be answered from the frozen artifacts.

This module re-walks the identical 2024 trade windows with the identical accepted
`prepare()` engine and recovers those indices. It is a re-derivation, not a new
measurement: before a single timing number is used, gate V7 requires that the walk
reproduce every frozen `fwd_mfe`, every frozen `fwd_mae`, and all 12 `lab_f050_a*_*`
labels on all 2,991 rows with ZERO mismatches. If it does not, the timing columns are
withheld and Phase 7 reports `NOT_AVAILABLE` -- nothing else in the study changes.

Conventions inherited verbatim, none re-decided here:
  * barriers are HWM-anchored: favourable `hwm + f`, adverse `hwm - a`
  * the forward segment is `(r, stop]`, clamped to the unconstrained terminal `unc_i`
  * a bar that both sets a new high and breaches the adverse level counts ADVERSE
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from studies.p80_p90_opportunity_continuation_ml.implementation.common import NS
from studies.p80_p90_opportunity_continuation_ml.implementation.observations_b import (
    load_rung_events)
from studies.top10_fast_confirm_runner_path.implementation.engine import prepare

from .common import ADVERSE_LEVELS, HORIZONS_S, SRC

FAVOURABLE = 0.50
LONG_HORIZON = max(HORIZONS_S)


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def _walk(w, r: int, hwm: float, unc_i: int, rung_ts: int) -> dict:
    """Re-derive the frozen quantities AND the first-hit timings for one rung."""
    hi, lo, ts = w.bar_hi, w.bar_lo, w.ts
    out: dict = {}

    for H in HORIZONS_S:
        stop = min(int(np.searchsorted(ts, rung_ts + H * NS, side="right")) - 1, unc_i)
        seg = slice(r + 1, stop + 1)
        n = max(0, stop - r)
        f_hi, f_lo = hi[seg], lo[seg]
        out[f"chk_fwd_mfe_{H}"] = float(max(0.0, f_hi.max() - hwm)) if n else 0.0
        out[f"chk_fwd_mae_{H}"] = float(max(0.0, hwm - f_lo.min())) if n else 0.0
        fi = _first(f_hi >= hwm + FAVOURABLE) if n else -1
        for a in ADVERSE_LEVELS:
            ai = _first(f_lo <= hwm - a) if n else -1
            tag = f"f{FAVOURABLE:.2f}_a{a:.2f}_{H}".replace(".", "")
            if fi < 0 and ai < 0:
                lab = "TIMEOUT"
            elif ai < 0:
                lab = "FAVOURABLE"
            elif fi < 0:
                lab = "ADVERSE"
            else:
                # Same-bar resolution counts ADVERSE, matching the frozen convention.
                lab = "FAVOURABLE" if fi < ai else "ADVERSE"
            out[f"chk_lab_{tag}"] = lab

    # Timing is measured over the LONGEST horizon only. Asking "how long until X"
    # inside a 180 s window would censor every answer at 180 s and report a shorter
    # median purely because the window is shorter -- the length-blindness failure.
    stop = min(int(np.searchsorted(ts, rung_ts + LONG_HORIZON * NS, side="right")) - 1,
               unc_i)
    seg = slice(r + 1, stop + 1)
    n = max(0, stop - r)
    f_hi, f_lo, f_ts = hi[seg], lo[seg], ts[seg]

    # "Next favourable extreme" is the first bar to exceed the HWM at all, which is
    # what fwd_mfe > 0 encodes. The +0.50 crossing is reported separately.
    ni = _first(f_hi > hwm) if n else -1
    out["secs_to_new_extreme"] = float((f_ts[ni] - rung_ts) / NS) if ni >= 0 else None
    fi = _first(f_hi >= hwm + FAVOURABLE) if n else -1
    out["secs_to_fav_050"] = float((f_ts[fi] - rung_ts) / NS) if fi >= 0 else None
    for a in ADVERSE_LEVELS:
        ai = _first(f_lo <= hwm - a) if n else -1
        out[f"secs_to_adv_{a:.2f}".replace(".", "")] = (
            float((f_ts[ai] - rung_ts) / NS) if ai >= 0 else None)
    out["window_bars_available"] = int(n)
    # True when the window ran out before the trade did, i.e. a null timing above is a
    # genuine non-event rather than a censored one.
    out["window_reached_horizon"] = bool(
        n and int(ts[stop]) >= rung_ts + LONG_HORIZON * NS)
    return out


def rederive(rung_events_path, market, regimes) -> tuple[pd.DataFrame, dict]:
    """Walk every 2024 POST_CONFIRM rung event. Returns (frame, verification)."""
    ev = load_rung_events(rung_events_path)
    wcache: dict = {}
    rows = []
    for e in ev.iter_rows(named=True):
        rid = e["regime_id"]
        w = wcache.get(rid)
        if w is None:
            w = prepare(market, regimes, {
                "entry_ns": e["entry_ns"], "direction": e["direction"],
                "entry_price": e["entry_price"], "entry_atr": e["entry_atr"],
                "confirm_ns": e["confirm_ns"], "regime_id": rid})
            if w is None:
                continue
            wcache[rid] = w
        r = int(np.searchsorted(w.ts, int(e["rung_ts"]), side="left"))
        if r >= w.ts.size or int(w.ts[r]) != int(e["rung_ts"]):
            continue
        hwm = float(w.run_mfe[r])
        if abs(hwm - float(e["hwm_at_arm_atr"])) > 1e-9:
            continue
        rows.append({"regime_id": rid, "rung_ts": int(e["rung_ts"]),
                     "rung_atr": float(e["rung_atr"]),
                     **_walk(w, r, hwm, int(w.unc_i), int(e["rung_ts"]))})
    out = pd.DataFrame(rows)
    return out, _verify(out)


def _verify(out: pd.DataFrame) -> dict:
    """Gate V7. Zero mismatches against the frozen labels, or the timing is withheld."""
    frozen = pd.read_parquet(SRC / "model_b_forward_labels.parquet")
    key = ["regime_id", "rung_ts", "rung_atr"]
    m = frozen.merge(out, on=key, how="left", validate="1:1")

    checks, mismatches = [], 0
    if len(m) != len(frozen) or m["window_bars_available"].isna().any():
        return {"passed": False, "reason": "ROW_COVERAGE",
                "n_frozen": len(frozen), "n_rederived": int(len(out)),
                "n_unmatched": int(m["window_bars_available"].isna().sum()),
                "checks": [], "total_mismatches": None}

    for H in HORIZONS_S:
        for q in ("fwd_mfe", "fwd_mae"):
            bad = int((~np.isclose(m[f"{q}_{H}"], m[f"chk_{q}_{H}"],
                                   rtol=0, atol=1e-12)).sum())
            checks.append({"quantity": f"{q}_{H}", "mismatches": bad})
            mismatches += bad
    for a in ADVERSE_LEVELS:
        for H in HORIZONS_S:
            tag = f"f{FAVOURABLE:.2f}_a{a:.2f}_{H}".replace(".", "")
            bad = int((m[f"lab_{tag}"] != m[f"chk_lab_{tag}"]).sum())
            checks.append({"quantity": f"lab_{tag}", "mismatches": bad})
            mismatches += bad

    return {"passed": bool(mismatches == 0), "reason": None if mismatches == 0 else "MISMATCH",
            "n_frozen": len(frozen), "n_rederived": int(len(out)),
            "n_quantities_checked": int(len(checks) * len(frozen)),
            "total_mismatches": mismatches, "checks": checks}


def timing_columns(out: pd.DataFrame) -> pd.DataFrame:
    keep = ["regime_id", "rung_ts", "rung_atr", "secs_to_new_extreme", "secs_to_fav_050",
            "window_bars_available", "window_reached_horizon"]
    keep += [f"secs_to_adv_{a:.2f}".replace(".", "") for a in ADVERSE_LEVELS]
    return out[keep]
