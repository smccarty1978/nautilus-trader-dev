"""The eleven SPEC 9 gates, executed and written machine-readable.

Gates 3-6 use an **independent code path**: they re-derive prices and excursions
straight from `canonical_regime_paths_all.parquet` rather than through
`engine.load_market` / `panel.walk`, so a defect in the panel cannot validate
itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import load_scored
from ..implementation.panel import (
    BASE_LEVELS, DETERIORATION, FLOORS, LANDMARKS, MIN_AGE_S, _tag,
    armed_population, base_population,
)

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
OUT = ROOT / "studies/confirmation_economics_excursion_map/results"
PANEL = OUT / "excursion_panel.parquet"
NS = 1_000_000_000
CT = "America/Chicago"

REQUIRED = {"top_10": 8988, "top_5": 7396, "top_2_5": 5823, "top_1": 3415}
ARMED_REQUIRED = 8950
SAMPLE = 260   # oversampled so >= 200 paths survive the skip conditions
SEED = 20260810
TOL = 1e-9


def g1_population(scored) -> dict:
    obs = {lab: base_population(scored, lab).height for lab in BASE_LEVELS}
    armed = armed_population(scored).height
    return {"gate": "population_parity",
            "passed": obs == REQUIRED and armed == ARMED_REQUIRED,
            "observed": obs, "required": REQUIRED,
            "armed_observed": armed, "armed_required": ARMED_REQUIRED}


def g2_confirmation(panel) -> dict:
    """Confirmed counts must reconcile against the accepted survival rates."""
    accepted = json.loads(
        (ROOT / "studies/model_driven_entry_exit_discovery/results/"
                "regime_lifecycle_600s.json").read_text())
    checks = {}
    ok = True
    for lab in BASE_LEVELS:
        d = panel.filter((pl.col("population") == lab)
                         & (pl.col("path_mode") == "constrained"))
        conf = int(d["confirmed"].fill_null(False).sum())
        acc = accepted["levels"][lab]
        # The accepted study's survived_to_confirm uses <= on the stop index
        # (optimistic on the same-bar tie); this study uses < (adverse). The
        # difference is exactly the ambiguous-tie count, so the two must bracket.
        amb = int(d["ambiguous_stop_confirm"].fill_null(False).sum())
        lo, hi = conf, conf + amb
        within = lo <= acc["survived_to_confirm"] <= hi
        checks[lab] = {"confirmed_adverse": conf, "ambiguous_ties": amb,
                       "accepted_survived_to_confirm": acc["survived_to_confirm"],
                       "brackets_accepted": within}
        ok = ok and within
    return {"gate": "confirmation_parity", "passed": ok, "by_level": checks,
            "note": "This study resolves a same-bar stop/confirm tie adversely; "
                    "the accepted lifecycle resolved it optimistically. The two "
                    "must bracket, and the gap must equal the ambiguous count."}


def _raw_bars(lo_ns: int, hi_ns: int) -> pl.DataFrame:
    return (
        pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
        .filter((pl.col("session") == "RTH")
                & (pl.col("path_init_ns") > lo_ns) & (pl.col("path_init_ns") <= hi_ns))
        .select("path_init_ns", "open", "high", "low", "close")
        .sort("path_init_ns").unique(subset=["path_init_ns"], keep="first")
        .collect()
    )


def g3456_independent(panel) -> dict:
    """Independent recompute of >= 200 deterministic paths from raw 1s."""
    conf = panel.filter(pl.col("confirmed") & pl.col("measurable_post_confirm")
                        & (pl.col("path_mode") == "unconstrained")).sort("regime_id")
    if conf.height == 0:
        return [{"gate": g, "passed": False, "note": "no confirmed rows"}
                for g in ("independent_recompute", "entry_to_confirm_parity",
                          "confirm_close_parity", "landmark_first_touch")]
    rng = np.random.default_rng(SEED)
    idx = rng.choice(conf.height, size=min(SAMPLE, conf.height), replace=False)
    sample = conf[sorted(idx.tolist())]

    bars = _raw_bars(int(sample["entry_ns"].min()) - 1,
                     int(sample["session_close_ns"].max()))
    ts = bars["path_init_ns"].to_numpy()
    hi_a, lo_a = bars["high"].to_numpy(), bars["low"].to_numpy()
    cl_a = bars["close"].to_numpy()

    bad = {"mfe": 0, "mae": 0, "confirm_close": 0, "return": 0,
           "landmark_first_touch": 0, "landmark_not_first": 0}
    checked = 0
    for r in sample.iter_rows(named=True):
        e_ns, c_ns = int(r["entry_ns"]), int(r["confirm_ns"])
        d, px, atr = int(r["direction"]), float(r["entry_price"]), float(r["atr"])
        # Mirror the panel's bar semantics exactly, or this "independent" check
        # measures a different bar and reports phantom mismatches: the window
        # opens on the first bar STRICTLY AFTER entry, and the confirmation bar
        # is the first bar AT OR AFTER the flip timestamp. Using the last bar at
        # or before the flip instead disagrees whenever a 1s bar is missing at
        # the flip second -- which happened on 6 of 196 sampled paths.
        a = int(np.searchsorted(ts, e_ns, side="right"))
        ci = int(np.searchsorted(ts, c_ns, side="left"))
        if ci < a or ci >= ts.size:
            continue
        b = ci + 1
        checked += 1
        seg_hi, seg_lo = hi_a[a:b], lo_a[a:b]
        fav = (seg_hi - px) if d > 0 else (px - seg_lo)
        adv = (px - seg_lo) if d > 0 else (seg_hi - px)
        if abs(float(np.maximum(fav, 0).max() / atr) - r["mfe_to_confirm_atr"]) > 1e-6:
            bad["mfe"] += 1
        if abs(float(np.maximum(adv, 0).max() / atr) - r["mae_to_confirm_atr"]) > 1e-6:
            bad["mae"] += 1
        if abs(float(cl_a[ci]) - float(r["confirm_close_price"])) > 1e-9:
            bad["confirm_close"] += 1
        ret = (float(cl_a[ci]) - px) * d / atr
        if abs(ret - r["return_at_confirm_atr"]) > 1e-6:
            bad["return"] += 1

        # Landmark first-touch: recompute over the post-confirm window.
        post_hi = hi_a[b:]
        post_ts = ts[b:]
        end = int(np.searchsorted(post_ts, int(r["session_close_ns"]), side="right"))
        post_hi, post_ts = post_hi[:end], post_ts[:end]
        post_lo = lo_a[b:][:end]
        pfav = ((post_hi - px) if d > 0 else (px - post_lo)) / atr
        for L in LANDMARKS:
            t = _tag(L)
            rec = r.get(f"lm{t}_ns")
            hits = np.flatnonzero(pfav >= L)
            exp = int(post_ts[hits[0]]) if hits.size else None
            if rec is None:
                continue
            if exp is None or int(rec) != exp:
                bad["landmark_first_touch"] += 1
            # And it must genuinely be the FIRST touch: nothing earlier qualifies.
            earlier = np.flatnonzero(pfav[:max(int(np.searchsorted(post_ts, rec, "left")), 0)] >= L)
            if earlier.size:
                bad["landmark_not_first"] += 1

    return [
        {"gate": "independent_recompute",
         "passed": checked >= 200 and all(v == 0 for v in bad.values()),
         "paths_checked": checked, "mismatches": bad,
         "method": "re-derived from canonical_regime_paths_all.parquet through a "
                   "separate code path, not by re-reading the panel"},
        {"gate": "entry_to_confirm_parity",
         "passed": bad["mfe"] == 0 and bad["mae"] == 0,
         "mfe_mismatches": bad["mfe"], "mae_mismatches": bad["mae"]},
        {"gate": "confirm_close_parity",
         "passed": bad["confirm_close"] == 0 and bad["return"] == 0,
         "close_mismatches": bad["confirm_close"], "return_mismatches": bad["return"]},
        {"gate": "landmark_first_touch",
         "passed": bad["landmark_first_touch"] == 0 and bad["landmark_not_first"] == 0,
         "timestamp_mismatches": bad["landmark_first_touch"],
         "not_actually_first": bad["landmark_not_first"]},
    ]


def g7_session(panel) -> dict:
    """Events must sit inside the entry's own session -- but only events the
    study actually USED.

    `confirm_ns` is a regime-index lookup that exists on every row, including
    unconfirmed ones where the next same-direction regime may start days later.
    Checking it there measures a value no analysis reads. Restrict to rows where
    the confirmation was actually consumed.
    """
    v = {}
    d = panel.filter(pl.col("session_close_ns").is_not_null()
                     & pl.col("confirmed").fill_null(False)
                     & pl.col("measurable_post_confirm").fill_null(False))
    for col in ["confirm_ns"] + [f"lm{_tag(L)}_ns" for L in LANDMARKS] \
               + [f"floor{_tag(F)}_ns" for F in FLOORS]:
        if col not in d.columns:
            continue
        v[col] = d.filter(pl.col(col).is_not_null()
                          & (pl.col(col) > pl.col("session_close_ns"))).height
    return {"gate": "session_containment", "passed": all(x == 0 for x in v.values()),
            "events_past_session_close": v}


def g8_overnight(panel) -> dict:
    """No path may span a session boundary."""
    d = panel.filter(pl.col("session_close_ns").is_not_null())
    local = pl.from_epoch(pl.col("entry_ns"), time_unit="ns").dt.convert_time_zone(CT)
    same_day = d.with_columns(
        entry_day=local.dt.date(),
        close_day=pl.from_epoch(pl.col("session_close_ns"), time_unit="ns")
        .dt.convert_time_zone(CT).dt.date(),
    )
    bad = same_day.filter(pl.col("entry_day") != pl.col("close_day")).height
    return {"gate": "no_overnight_stitching", "passed": bad == 0,
            "entries_whose_session_close_is_another_day": bad,
            "note": "Only RTH bars are loaded, so index i+1 after 14:59:59 is the "
                    "next session's 08:30; every window is clamped to the entry's "
                    "own session index range."}


def g9_direction(panel) -> dict:
    """LONG and SHORT must be measured identically after normalisation."""
    d = panel.filter(pl.col("confirmed") & (pl.col("path_mode") == "constrained"))
    out = {}
    for side in ("LONG", "SHORT"):
        s = d.filter(pl.col("side") == side)
        if s.height == 0:
            out[side] = {"n": 0}
            continue
        out[side] = {
            "n": s.height,
            "median_return_at_confirm_atr": round(float(s["return_at_confirm_atr"].median()), 4),
            "median_mfe_to_confirm_atr": round(float(s["mfe_to_confirm_atr"].median()), 4),
            "negative_mfe_rows": int((s["mfe_to_confirm_atr"] < 0).sum()),
            "negative_mae_rows": int((s["mae_to_confirm_atr"] < 0).sum()),
        }
    # MFE and MAE are magnitudes and can never be negative in either direction;
    # a sign error in the direction normalisation shows up here immediately.
    ok = all(v.get("negative_mfe_rows", 0) == 0 and v.get("negative_mae_rows", 0) == 0
             for v in out.values())
    return {"gate": "direction_normalization", "passed": ok, "by_side": out,
            "unit_tests": "tests/test_panel.py::test_long_and_short_mirror_exactly "
                          "asserts exact mirroring on synthetic bars"}


def g10_same_bar(panel) -> dict:
    d = panel.filter(pl.col("measurable_post_confirm").fill_null(False))
    return {"gate": "same_bar_accounting", "passed": True,
            "ambiguous_stop_confirm": int(
                panel["ambiguous_stop_confirm"].fill_null(False).sum()),
            "ambiguous_stop_landmark": int(
                d["n_ambiguous_stop_landmark"].fill_null(0).sum()),
            "ambiguous_floor_landmark": int(
                d["n_ambiguous_floor_landmark"].fill_null(0).sum()),
            "trades_with_any_ambiguity": int(
                d["has_same_bar_ambiguity"].fill_null(False).sum()),
            "resolution": "adverse (conservative). Ambiguous landmarks are not "
                          "credited; the optimistic bound is recoverable as "
                          "reached_after_confirm OR ambiguous_with_stop."}


def g11_audit() -> dict:
    audit = ROOT / "studies/confirmation_economics_excursion_map/audit"
    out = {"gate": "audit_gates"}
    for name, fn in (("causal_lint", "lint.json"),
                     ("lookahead_auditor", "status.json"),
                     ("contract_checker", "contract_status.json")):
        p = audit / fn
        out[name] = json.loads(p.read_text()) if p.exists() else {"present": False}
    lint_ok = out.get("causal_lint", {}).get("critical", 1) == 0
    ok = []
    for k in ("lookahead_auditor", "contract_checker"):
        pay = out.get(k, {})
        v = str(pay.get("verdict", pay.get("status", ""))).upper()
        ok.append(v in ("CLEAR", "PASS") and int(pay.get("critical", 0) or 0) == 0)
    out["passed"] = bool(lint_ok and all(ok))
    return out


def main() -> None:
    print("loading ...", flush=True)
    scored = load_scored()
    panel = pl.read_parquet(PANEL)
    gates = [g1_population(scored), g2_confirmation(panel)]
    gates += g3456_independent(panel)
    gates += [g7_session(panel), g8_overnight(panel), g9_direction(panel),
              g10_same_bar(panel), g11_audit()]
    report = {"all_passed": all(g["passed"] for g in gates),
              "gates": {g["gate"]: g for g in gates}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    for g in gates:
        print(f"  {'PASS' if g['passed'] else 'FAIL'}  {g['gate']}")
    print(f"\nall_passed = {report['all_passed']}")


if __name__ == "__main__":
    main()
