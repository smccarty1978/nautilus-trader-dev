"""Regime table, D10 crossing events, coverage report, forward diagnostics.

All offline artifacts here are DESCRIPTIVE/DIAGNOSTIC ONLY; final economics
come from the NT event loop (run_nt.py). In particular, no stop multiplier or
policy is selected from these diagnostics — the spec mandates reporting all
three stops without a test-optimized winner, so nothing downstream conditions
on these numbers.

Timing conventions per SPEC.md and audit/fill_fixture_observations.json:

- flip known at 1m bar CLOSE (close_ts);
- score at observation_time=T available at T+1s;
- the executable price for a decision at boundary A is the CLOSE of the 1s
  bar ending at A (NT bar execution fills market orders immediately at the
  decision boundary against the just-completed bar's close — verified by
  test_fill_fixture.py). For a D10 decision at T+1s that is the checkpoint
  bar's own close; for a flip decision at close_ts it is the last 1s close
  of the flip minute.
- stop diagnostics mirror NT stop-market semantics (touch -> fill at
  trigger) EXCEPT that bars gapping through the trigger are conservatively
  repriced to the bar open (NT itself optimistically fills at trigger there;
  analyze.py applies the same repricing to the NT results).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
STUDY_DIR = Path(__file__).resolve().parent
UPSTREAM_DIR = Path(__file__).resolve().parents[1] / "regime_sequence_chop_context"
sys.path.insert(0, str(UPSTREAM_DIR))

from reproduce_regimes import aggregate_and_run_regimes  # noqa: E402
from studies.fable5_pre_flip_d10_reversal_entry.common import (  # noqa: E402
    AUDIT, ECON_WINDOWS, MAX_CHECKPOINT_AGE_S, NS_PER_S, RAW_1S, RESULTS,
    STOP_GRID, TICK, WORK, is_rth, load_frozen_threshold,
)


def _tick_round(v: float) -> float:
    return round(v / TICK) * TICK


def build_regime_table(year: int, df_1s: pd.DataFrame) -> pd.DataFrame:
    """All regimes (completed + trailing censored) for one year.

    Regime k runs (flip_k.close_ts, flip_{k+1}.close_ts]; the regime open at
    data end is retained with end_censored=True.
    """
    df_1m = aggregate_and_run_regimes(df_1s, "1m")
    df_1m = df_1m.sort_values("close_ts").reset_index(drop=True)
    prev = df_1m["regime"].shift(1).fillna(0).astype(int)
    flips = df_1m[(df_1m["regime"] != 0) & (prev != 0)
                  & (df_1m["regime"] != prev)]
    data_end_ns = int(df_1s.index.view(np.int64)[-1]) + NS_PER_S  # last 1s close

    rows = []
    frows = list(flips.itertuples())
    for i, r in enumerate(frows):
        start = int(r.close_ts)
        if i + 1 < len(frows):
            end = int(frows[i + 1].close_ts)
            censored = False
        else:
            end = data_end_ns
            censored = True
        rows.append({
            "year": year,
            "regime_start_ns": start,
            "regime_end_ns": end,
            "direction": int(r.regime),
            "duration_s": (end - start) / 1e9,
            "duration_bars": int(round((end - start) / 60e9)),
            "atr_at_start": float(r.atr),
            "end_censored": censored,
        })
    out = pd.DataFrame(rows)
    out["rth"] = is_rth(out["regime_start_ns"].to_numpy())
    return out


def add_regime_mfe(reg: pd.DataFrame, df_1s: pd.DataFrame) -> pd.DataFrame:
    """Regime MFE in ATR units, anchored at the first 1s open inside the
    regime (same anchor family as upstream build_regime_history)."""
    ts = df_1s.index.view(np.int64)
    highs = df_1s["high"].to_numpy()
    lows = df_1s["low"].to_numpy()
    opens = df_1s["open"].to_numpy()
    mfe = np.full(len(reg), np.nan)
    for i, r in enumerate(reg.itertuples()):
        a = np.searchsorted(ts, r.regime_start_ns, side="left")
        b = np.searchsorted(ts, r.regime_end_ns, side="left")
        if b <= a:
            continue
        anchor = opens[a]
        if r.direction == 1:
            m = np.max(highs[a:b]) - anchor
        else:
            m = anchor - np.min(lows[a:b])
        mfe[i] = m / r.atr_at_start if r.atr_at_start > 0 else np.nan
    reg = reg.copy()
    reg["regime_mfe_atr"] = mfe
    return reg


def summarize_coverage(cov: pd.DataFrame) -> pd.DataFrame:
    cov = cov.copy()
    cov["atr_bucket"] = pd.qcut(cov["atr_at_start"], 4,
                                labels=["q1", "q2", "q3", "q4"], duplicates="drop")
    cov["dur_bucket"] = pd.cut(cov["regime_duration_s"],
                               [0, 120, 300, 600, 1200, 1800, np.inf],
                               labels=["<2m", "2-5m", "5-10m", "10-20m",
                                       "20-30m", ">30m"])
    cov["mfe_bucket"] = pd.cut(cov["regime_mfe_atr"],
                               [-np.inf, 0.5, 1.0, 2.0, np.inf],
                               labels=["<0.5", "0.5-1", "1-2", ">2"])
    frames = []
    for key in ["year", "direction", "rth", "atr_bucket", "dur_bucket",
                "mfe_bucket"]:
        g = cov.groupby(key, observed=True).agg(
            n_regimes=("regime_start_ns", "count"),
            n_validly_scored=("validly_scored", "sum"),
            n_ever_d10=("ever_reached_D10", "sum"),
            n_d10_before_end=("d10_before_end", "sum"),
            n_d10_at_end_only=("d10_at_end_only", "sum"),
            median_duration_s=("regime_duration_s", "median"),
        ).reset_index().rename(columns={key: "segment_value"})
        g.insert(0, "segment", key)
        g["segment_value"] = g["segment_value"].astype(str)
        frames.append(g)
    out = pd.concat(frames, ignore_index=True)
    out["pct_ever_d10_of_scored"] = out["n_ever_d10"] / out["n_validly_scored"]
    return out


def main() -> None:
    t0 = time.time()
    thr_info = load_frozen_threshold()
    thr = thr_info["threshold"]
    print(f"Frozen D10 threshold: {thr:.6f}")

    scores = pd.read_parquet(WORK / "causal_scores.parquet")
    assert "in_econ_window" in scores.columns, \
        "causal_scores.parquet missing in_econ_window (rerun build_scores.py)"

    all_cov, all_events, all_diag, id_audit = [], [], [], []
    offline_skips: list[dict] = []

    for year, raw_path in RAW_1S.items():
        print(f"\n=== {year} ===")
        df_1s = pd.read_parquet(raw_path)
        ts_1s = df_1s.index.view(np.int64)
        opens = df_1s["open"].to_numpy()
        highs = df_1s["high"].to_numpy()
        lows = df_1s["low"].to_numpy()
        closes = df_1s["close"].to_numpy()

        reg = build_regime_table(year, df_1s)
        reg = add_regime_mfe(reg, df_1s)
        print(f"  {len(reg):,} regimes (incl. 1 censored tail) "
              f"({time.time()-t0:.0f}s)")

        sy = scores[scores["year"] == year]
        # group score rows by exact regime start
        grp = {k: v for k, v in sy.groupby("regime_start_ns")}

        # --- regime/score identity audit ---
        reg_starts = set(reg["regime_start_ns"].tolist())
        score_starts = set(grp.keys())
        matched = reg_starts & score_starts
        id_audit.append({
            "year": year,
            "n_regimes": len(reg_starts),
            "n_score_regimes": len(score_starts),
            "n_matched": len(matched),
            "n_regime_only": len(reg_starts - score_starts),
            "n_score_only": len(score_starts - reg_starts),
        })

        econ_s, econ_e = ECON_WINDOWS[year]

        for r in reg.itertuples():
            g = grp.get(r.regime_start_ns)
            n_cp = 0 if g is None else len(g)
            n_valid = 0 if g is None else int(g["score_valid"].sum())
            max_score = np.nan
            first_d10 = None
            dir_mismatch = False
            if g is not None and n_valid > 0:
                if not (g["direction"] == r.direction).all():
                    dir_mismatch = True
                gv = g[g["score_valid"] & g["w4_score"].notna()]
                max_score = float(gv["w4_score"].max())
                hits = gv[gv["w4_score"] >= thr]
                if len(hits):
                    first_d10 = int(hits["observation_time"].iloc[0])

            if n_cp == 0:
                reason = ("no_checkpoint_rows" if r.duration_s >= 5
                          else "regime_too_short")
            elif n_valid == 0:
                reason = "warmup_or_features_nan"
            else:
                reason = ""
            validly_scored = n_valid > 0
            ever_d10 = first_d10 is not None
            d10_at_end = ever_d10 and first_d10 >= r.regime_end_ns
            d10_before_end = ever_d10 and first_d10 < r.regime_end_ns
            # scoring stops at 1800s; note the uncovered tail explicitly
            uncovered_tail = r.duration_s > MAX_CHECKPOINT_AGE_S

            all_cov.append({
                "regime_id": f"{year}_{r.regime_start_ns}",
                "year": year,
                "direction": r.direction,
                "regime_start_ns": r.regime_start_ns,
                "regime_end_ns": r.regime_end_ns,
                "end_censored": r.end_censored,
                "regime_duration_s": r.duration_s,
                "regime_duration_bars": r.duration_bars,
                "rth": r.rth,
                "atr_at_start": r.atr_at_start,
                "regime_mfe_atr": r.regime_mfe_atr,
                "max_w4_score": max_score,
                "d10_threshold": thr,
                "validly_scored": validly_scored,
                "ever_reached_D10": ever_d10,
                "d10_before_end": d10_before_end,
                "d10_at_end_only": d10_at_end,
                "first_D10_time": first_d10,
                "seconds_start_to_D10":
                    (first_d10 - r.regime_start_ns) / 1e9 if ever_d10 else np.nan,
                "seconds_D10_to_end":
                    (r.regime_end_ns - first_d10) / 1e9 if ever_d10 else np.nan,
                "D10_same_timestamp_as_regime_end":
                    ever_d10 and first_d10 == r.regime_end_ns,
                "score_checkpoint_count": n_cp,
                "valid_score_checkpoint_count": n_valid,
                "score_unavailable_reason": reason,
                "age_coverage_truncated_at_1800s": uncovered_tail,
                "direction_mismatch_flag": dir_mismatch,
            })

            # ---- entry event (strictly pre-flip crossing, in econ window) ----
            if not d10_before_end:
                continue  # no crossing / crossing at end: measured in coverage
            if not (econ_s.value <= first_d10 < econ_e.value):
                offline_skips.append({
                    "regime_id": f"{year}_{r.regime_start_ns}",
                    "reason": "crossing_outside_econ_window",
                })
                continue
            row_cp = g[g["observation_time"] == first_d10].iloc[0]
            avail_ns = first_d10 + NS_PER_S  # score available T+1s
            entry_dir = -r.direction

            # executable D10 entry price under the NT event loop: fill at the
            # decision boundary against the checkpoint bar's own close
            # (fixture-verified); exposure starts with the next 1s bar.
            i_ent = np.searchsorted(ts_1s, avail_ns, side="left")
            d10_px = float(row_cp["close"])
            d10_fill_ts = avail_ns

            # wait-for-flip executable price: last 1s close before the flip
            # boundary (what a flip entry submitted at close_ts fills at)
            wait_px = np.nan
            wait_fill_ts = None
            if not r.end_censored:
                i_w = np.searchsorted(ts_1s, r.regime_end_ns, side="left") - 1
                if i_w >= 0:
                    wait_px = float(closes[i_w])
                    wait_fill_ts = int(r.regime_end_ns)

            atr_cp = float(row_cp["atr"])
            ev = {
                "regime_id": f"{year}_{r.regime_start_ns}",
                "year": year,
                "old_direction": r.direction,
                "entry_dir": entry_dir,
                "regime_start_ns": r.regime_start_ns,
                "regime_end_ns": r.regime_end_ns,
                "end_censored": r.end_censored,
                "d10_obs_time": first_d10,
                "score": float(row_cp["w4_score"]),
                "threshold": thr,
                "regime_age_at_d10": float(row_cp["regime_age"]),
                "atr_at_d10": atr_cp,
                "cp_close": float(row_cp["close"]),
                "current_mfe": float(row_cp["current_mfe"]),
                "current_pnl": float(row_cp["current_pnl"]),
                "giveback": float(row_cp["giveback"]),
                "rth": bool(is_rth(first_d10)),
                "d10_entry_px": d10_px,
                "d10_fill_ts": d10_fill_ts,
                "wait_for_flip_px": wait_px,
                "wait_fill_ts": wait_fill_ts,
                "seconds_d10_to_flip":
                    (r.regime_end_ns - first_d10) / 1e9
                    if not r.end_censored else np.nan,
                "frontrun_advantage_pts":
                    (wait_px - d10_px) * entry_dir
                    if np.isfinite(wait_px) else np.nan,
            }
            ev["frontrun_advantage_atr"] = (
                ev["frontrun_advantage_pts"] / atr_cp
                if np.isfinite(ev["frontrun_advantage_pts"]) and atr_cp > 0
                else np.nan)
            all_events.append(ev)

            # ---- offline pre-flip path diagnostics (fill -> flip) ----
            i_end = (np.searchsorted(ts_1s, r.regime_end_ns, side="left")
                     if not r.end_censored else len(ts_1s))
            hh = highs[i_ent:i_end]
            ll = lows[i_ent:i_end]
            oo = opens[i_ent:i_end]
            tt = ts_1s[i_ent:i_end]
            if len(hh) == 0 or atr_cp <= 0:
                offline_skips.append({
                    "regime_id": ev["regime_id"],
                    "reason": "no_bars_for_diag" if len(hh) == 0 else "bad_atr",
                })
                continue
            if entry_dir == 1:
                mae_pts = np.maximum.accumulate(d10_px - ll)
                mfe_pts = np.maximum.accumulate(hh - d10_px)
            else:
                mae_pts = np.maximum.accumulate(hh - d10_px)
                mfe_pts = np.maximum.accumulate(d10_px - ll)
            diag = {
                "regime_id": ev["regime_id"],
                "year": year,
                "entry_dir": entry_dir,
                "d10_obs_time": first_d10,
                "atr_at_d10": atr_cp,
                "end_censored": r.end_censored,
                "preflip_mae_atr": float(mae_pts[-1]) / atr_cp,
                "preflip_mfe_atr": float(mfe_pts[-1]) / atr_cp,
                "seconds_d10_to_flip": ev["seconds_d10_to_flip"],
            }
            for s_mult in STOP_GRID:
                stop_px = _tick_round(d10_px - entry_dir * s_mult * atr_cp)
                if entry_dir == 1:
                    hit = ll <= stop_px
                else:
                    hit = hh >= stop_px
                idx = np.argmax(hit) if hit.any() else -1
                tag = f"{s_mult:.2f}".replace(".", "")
                diag[f"stop{tag}_hit_before_flip"] = bool(hit.any())
                if hit.any():
                    gap = (oo[idx] < stop_px) if entry_dir == 1 else (oo[idx] > stop_px)
                    diag[f"stop{tag}_fill_px"] = float(oo[idx]) if gap else stop_px
                    diag[f"stop{tag}_hit_ts"] = int(tt[idx])
                else:
                    diag[f"stop{tag}_fill_px"] = np.nan
                    diag[f"stop{tag}_hit_ts"] = None
            all_diag.append(diag)

        all_cov_year_n = sum(1 for c in all_cov if c["year"] == year)
        print(f"  coverage rows {all_cov_year_n:,}, events so far "
              f"{len(all_events):,} ({time.time()-t0:.0f}s)")
        del df_1s

    cov = pd.DataFrame(all_cov)
    events = pd.DataFrame(all_events)
    diag = pd.DataFrame(all_diag)

    # tag calibration vs economics window so the 2025 summary never blends
    # Jan-Feb (threshold calibration) with the traded Mar-Dec window
    win = np.full(len(cov), "other", dtype=object)
    for yr, (s, e) in ECON_WINDOWS.items():
        m = ((cov["year"] == yr) & (cov["regime_start_ns"] >= s.value)
             & (cov["regime_start_ns"] < e.value))
        win[m.to_numpy()] = "economics"
    cal = ((cov["year"] == 2025)
           & (cov["regime_start_ns"] < ECON_WINDOWS[2025][0].value))
    win[cal.to_numpy()] = "calibration"
    cov["window"] = win

    cov.to_parquet(RESULTS / "regime_d10_coverage.parquet", index=False)
    summarize_coverage(cov[cov["window"] == "economics"]).to_parquet(
        RESULTS / "regime_d10_coverage_summary.parquet", index=False)
    events.to_parquet(RESULTS / "d10_entry_events.parquet", index=False)
    diag.to_parquet(RESULTS / "forward_reversal_diagnostics.parquet", index=False)

    pvw = events[["regime_id", "year", "entry_dir", "d10_obs_time",
                  "d10_entry_px", "wait_for_flip_px", "seconds_d10_to_flip",
                  "frontrun_advantage_pts", "frontrun_advantage_atr",
                  "end_censored"]].copy()
    pvw.to_parquet(RESULTS / "preflip_vs_wait_for_flip.parquet", index=False)

    pd.DataFrame(id_audit).to_parquet(
        AUDIT / "score_regime_id_audit.parquet", index=False)
    pd.DataFrame(offline_skips).to_parquet(
        AUDIT / "offline_event_skips.parquet", index=False)

    # fail-fast: every score-stream regime must exist in the regime table
    # (same raw data, same engine — any orphan means identity drift)
    for a in id_audit:
        if a["n_score_only"] > 0:
            raise SystemExit(
                f"FAIL-FAST: {a['n_score_only']} score regimes missing from "
                f"regime table in {a['year']}")

    n_mm = int(cov["direction_mismatch_flag"].sum())
    print(f"\nRegimes: {len(cov):,} | validly scored: "
          f"{int(cov['validly_scored'].sum()):,} | ever D10: "
          f"{int(cov['ever_reached_D10'].sum()):,} | entry events: "
          f"{len(events):,} | direction mismatches: {n_mm}")
    print(pd.DataFrame(id_audit))
    if n_mm:
        raise SystemExit("FAIL-FAST: direction mismatch between regime table "
                         "and score stream")
    print(f"Done ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
