"""Targeted, NT-independent first-divergence audit for OHLCVDeltaTracker.

Drives the SAME production CandidateTracker / RegimeEngine /
ReducedFeatureEngine (specifically its OHLCVDeltaTracker) as strategy.py,
replicating strategy.py's exact _on_1s/_on_1m control flow bar-by-bar over a
bounded raw-data window, while feeding an IDENTICAL call sequence to
shadow_ohlcv.ShadowOHLCVCalculator in parallel (a diagnostic-only, freshly-
recomputed cross-check -- see shadow_ohlcv.py's module docstring).

Deliberately NOT a BacktestEngine run: CandidateTracker/RegimeEngine/
ReducedFeatureEngine are already NT-independent pure Python (established
earlier in this study's reconciliation work), so a raw-bar replay loop
reproduces their behavior exactly, at a fraction of the cost -- this is the
"targeted diagnostic" the audit calls for; a full engine rerun happens only
after this passes.

Usage:
    python diagnostics/run_targeted_replay.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPL = HERE.parent / "implementation"
ROOT = HERE.parents[2]
for p in (str(IMPL), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine  # noqa: E402
from candidate_tracker import CandidateTracker, is_rth_minute_of_day  # noqa: E402
from reduced_feature_engine import ReducedFeatureEngine  # noqa: E402
from shadow_ohlcv import ShadowOHLCVCalculator, FLAGGED_FEATURES, compare  # noqa: E402
import common as C  # noqa: E402

NS = 1_000_000_000
TOL = 1e-6  # per-feature abs tolerance; see README note below if relaxed further

FULL_YEAR_START = pd.Timestamp("2025-01-01", tz="UTC")  # matches run_nt.py's LOAD_START -- RegimeEngine cold-starts here
REPLAY_START = pd.Timestamp("2025-03-30 22:00:00", tz="UTC")  # Sunday evening open
REPLAY_END = pd.Timestamp("2025-04-02 00:00:00", tz="UTC")    # covers 2 full RTH sessions
RAW_1S_PATH = ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet"
OFFLINE_REF_PATH = (ROOT / "studies" / "nt_reduced_f3_top25_population_parity_smoke"
                    / "results" / "offline_candidates_march_2025.parquet")
OUT_DIR = HERE / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _minute_bucket_key(bar_ts: int) -> int:
    return (bar_ts - 1) // (60 * NS)


def build_1m_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """Resample('1min', label='right', closed='left') on raw 1s OHLC --
    confirmed 0.0 diff against the actual NT catalog's 1m bars for this exact
    window (spot-checked before this script was written: 2,880/2,880 common
    bars, max abs diff 0.0 on open/high/low/close)."""
    res = raw.resample("1min", label="right", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return res


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=str(REPLAY_START))
    ap.add_argument("--end", default=str(REPLAY_END))
    ap.add_argument("--simulate-ts-init-1s", action="store_true",
                    help="hypothesis test: shift every 1s bar ts forward 1s to simulate bar.ts_init")
    args = ap.parse_args()
    start = pd.Timestamp(args.start, tz="UTC") if pd.Timestamp(args.start).tzinfo is None else pd.Timestamp(args.start)
    end = pd.Timestamp(args.end, tz="UTC") if pd.Timestamp(args.end).tzinfo is None else pd.Timestamp(args.end)

    print(f"[targeted-replay] loading raw 1s bars {FULL_YEAR_START} .. {end} "
         f"(full range needed for RegimeEngine warmup; only [{start}, {end}] is actually replayed "
         f"through the tracker/candidate machinery)")
    raw_full = pd.read_parquet(RAW_1S_PATH, columns=["open", "high", "low", "close", "volume"])
    raw_full = raw_full.loc[FULL_YEAR_START:end]

    # RegimeEngine.atr/regime are long-memory IIR/cumulative state (EMA3/EMA9,
    # Wilder ATR) -- starting it cold at the diagnostic window's own start
    # reproduces a DIFFERENT regime timeline than the real live run, which
    # accumulates this state continuously from run_nt.py's own LOAD_START
    # (2025-01-01). Confirmed empirically: a first attempt at this replay,
    # cold-started at REPLAY_START, produced ZERO regime flips over 2+ days,
    # where the real live run flips several times a day over the same
    # calendar window -- proving the missing warmup, not tracker arithmetic,
    # was responsible. Warm up on 1m OHLC alone (cheap, no tracker/candidate
    # machinery needed for this phase) from FULL_YEAR_START up to (not
    # including) `start`, then resume normal per-bar replay from `start`.
    bars_1m_full = build_1m_bars(raw_full)
    warmup_1m = bars_1m_full.loc[:start - pd.Timedelta(nanoseconds=1)]
    replay_1m = bars_1m_full.loc[start:end]
    print(f"[targeted-replay] warming up RegimeEngine on {len(warmup_1m):,} 1m bars "
         f"({FULL_YEAR_START} .. {start})")

    engine = RegimeEngine()
    for h, l, c in zip(warmup_1m["high"].to_numpy(float), warmup_1m["low"].to_numpy(float),
                       warmup_1m["close"].to_numpy(float)):
        engine.update(h, l, c)
    print(f"[targeted-replay] warmup complete: regime={engine.regime}, atr={engine.atr}")

    raw = raw_full.loc[start:end]
    n = len(raw)
    print(f"[targeted-replay] {n:,} 1s bars loaded for replay")

    m1_ts = replay_1m.index.view(np.int64)
    m1_o = replay_1m["open"].to_numpy(float)
    m1_h = replay_1m["high"].to_numpy(float)
    m1_l = replay_1m["low"].to_numpy(float)
    m1_c = replay_1m["close"].to_numpy(float)
    print(f"[targeted-replay] {len(replay_1m):,} 1m bars built for replay")

    offline_ref = None
    if OFFLINE_REF_PATH.exists():
        offline_ref = pd.read_parquet(OFFLINE_REF_PATH).set_index(["regime_start_ns", "checkpoint_index"])

    ts_arr = raw.index.view(np.int64)
    if args.simulate_ts_init_1s:
        # HYPOTHESIS TEST ONLY: raw parquet's index is NT catalog ts_event
        # (open-stamped) for 1s bars; NT's ts_init = ts_event + 1s (confirmed
        # empirically against the live catalog). strategy.py's _on_1s uses
        # `int(bar.ts_init)`, NOT ts_event -- this flag simulates that by
        # shifting every 1s timestamp forward 1s, to test whether THAT is
        # what makes the real NT run diverge from this ts_event-based replay
        # (which otherwise matches the offline reference, itself built from
        # raw ts_event directly per CLAUDE.md's "1s bars need no adjustment").
        ts_arr = ts_arr + NS
    o_arr = raw["open"].to_numpy(float)
    h_arr = raw["high"].to_numpy(float)
    l_arr = raw["low"].to_numpy(float)
    c_arr = raw["close"].to_numpy(float)
    v_arr = raw["volume"].to_numpy(float)

    regime_dir = engine.regime
    was_rth = False
    current_minute = None
    minute_o = minute_h = minute_l = None
    minute_buf: list[tuple[int, float, float, float, float]] = []
    prev_close = None

    feature_engine = ReducedFeatureEngine([])  # no scoring needed for this audit
    shadow = ShadowOHLCVCalculator()

    candidate_rows: list[dict] = []
    per_bar_first_divergence = None
    per_bar_divergence_count = 0
    per_bar_checked = 0
    flip_log: list[dict] = []

    def on_candidate(cdict: dict) -> None:
        if not cdict["established_regime_gate"]:
            return
        fill_ts_ns = cdict["fill_ts_ns"]
        atr = engine.atr
        f_live = feature_engine.ohlcv.calculate(atr=atr if atr else 0.0)
        f_shadow = shadow.calculate(observation_ts=fill_ts_ns, atr=atr if atr else 0.0)
        key = (cdict["regime_start_ns"], cdict["checkpoint_index"])
        offline_row = None
        if offline_ref is not None and key in offline_ref.index:
            offline_row = offline_ref.loc[key].to_dict()
        report = compare(f_live, f_shadow, offline_row, features=FLAGGED_FEATURES, tol=TOL)
        candidate_rows.append({
            "regime_start_ns": key[0], "checkpoint_index": key[1],
            "observation_time_ns": cdict["observation_time_ns"], "fill_ts_ns": fill_ts_ns,
            "obs_ts_matches_last_bar": f_shadow.get("shadow_obs_ts_matches_last_bar"),
            "report": report,
        })

    candidate_tracker = CandidateTracker(on_candidate=on_candidate, is_rth_fn=is_rth_minute_of_day)

    m1_idx = 0
    n_m1 = len(m1_ts)

    for i in range(n):
        ts = int(ts_arr[i])
        o, h, l, c, v = float(o_arr[i]), float(h_arr[i]), float(l_arr[i]), float(c_arr[i]), float(v_arr[i])
        prev_close = c

        b_est = feature_engine.update_1s(ts, o, h, l, c, v)
        shadow.update(ts, o, h, l, c, v)

        mk = _minute_bucket_key(ts)
        if current_minute is None:
            current_minute = mk
            minute_o, minute_h, minute_l = o, h, l
            minute_buf = [(ts, h, l, v, b_est["bar_est_delta"])]
        elif mk == current_minute:
            minute_h = max(minute_h, h)
            minute_l = min(minute_l, l)
            minute_buf.append((ts, h, l, v, b_est["bar_est_delta"]))
        else:
            current_minute = mk
            minute_o, minute_h, minute_l = o, h, l
            minute_buf = [(ts, h, l, v, b_est["bar_est_delta"])]

        # -- per-1s-bar shadow comparison (continuous, not just at candidates) --
        atr_now = engine.atr
        f_live_bar = feature_engine.ohlcv.calculate(atr=atr_now if atr_now else 0.0)
        f_shadow_bar = shadow.calculate(observation_ts=ts, atr=atr_now if atr_now else 0.0)
        per_bar_checked += 1
        for feat in FLAGGED_FEATURES:
            lv, sv = f_live_bar.get(feat), f_shadow_bar.get(feat)
            if lv is None or sv is None:
                continue
            d = abs(float(lv) - float(sv))
            if d > TOL:
                per_bar_divergence_count += 1
                if per_bar_first_divergence is None:
                    per_bar_first_divergence = {
                        "bar_index": i, "ts": ts, "feature": feat,
                        "live_value": lv, "shadow_value": sv, "abs_diff": d,
                        "bar_ohlcv": {"open": o, "high": h, "low": l, "close": c, "volume": v},
                        "live_full": {k: f_live_bar.get(k) for k in FLAGGED_FEATURES},
                        "shadow_full": {k: f_shadow_bar.get(k) for k in FLAGGED_FEATURES},
                        "shadow_window_diag": {
                            k: v2 for k, v2 in f_shadow_bar.items()
                            if k.startswith("shadow_window_") or k.startswith("shadow_")
                        },
                        "live_deque_len": len(feature_engine.ohlcv.ts),
                        "shadow_history_len": len(shadow.ts),
                        "live_deque_oldest_ts": feature_engine.ohlcv.ts[0] if feature_engine.ohlcv.ts else None,
                        "live_deque_newest_ts": feature_engine.ohlcv.ts[-1] if feature_engine.ohlcv.ts else None,
                        "regime_dir": regime_dir, "was_rth": was_rth,
                    }
                    print(f"[targeted-replay] FIRST PER-BAR DIVERGENCE at bar {i} ts={ts} "
                         f"feature={feat} live={lv} shadow={sv} diff={d}")

        # detect minute boundary crossing using the ACTUAL 1m bar stream
        # (mirrors strategy.py's _on_1m firing once per completed minute).
        # HARNESS BUG FOUND AND FIXED here (not a strategy.py bug): an exact
        # `== ts` match silently and PERMANENTLY desyncs m1_idx from the 1s
        # loop the first time the raw feed is missing the exact 1-second bar
        # at a minute boundary (confirmed real, e.g. 2025-03-30 22:06:00 is
        # simply absent from the raw feed -- a routine quiet-second gap,
        # already documented in ohlcv_delta.py/attach_features.py). Once that
        # happens, `m1_ts[m1_idx]` never again equals any later `ts` (ts only
        # increases), so EVERY subsequent minute close, regime update, and
        # candidate declaration silently stops for the rest of the replay --
        # this is why an early full-window run of this script found ZERO
        # flips over 2+ days. Real NT does not have this failure mode: its
        # 1m bar stream is delivered independently via add_data(bars_1m), not
        # derived by matching resampled-1m timestamps against the 1s stream.
        # `<=` with a `while` (catch-up, not a single `if`) fires the 1m
        # close as soon as any 1s bar reaches or passes its boundary,
        # matching what NT's real, independently-computed 1m bar delivery
        # would still do regardless of a missing 1s tick.
        while m1_idx < n_m1 and int(m1_ts[m1_idx]) <= ts:
            m_ts = int(m1_ts[m1_idx])
            bh, bl, bc = float(m1_h[m1_idx]), float(m1_l[m1_idx]), float(m1_c[m1_idx])
            bo = float(m1_o[m1_idx])
            m1_idx += 1

            prev_regime = regime_dir
            new_regime = engine.update(bh, bl, bc)
            regime_dir = new_regime
            now_rth = is_rth_minute_of_day(
                pd.Timestamp(m_ts, unit="ns", tz="UTC").tz_convert("America/Chicago").hour * 60
                + pd.Timestamp(m_ts, unit="ns", tz="UTC").tz_convert("America/Chicago").minute)

            flip = prev_regime != 0 and new_regime != 0 and new_regime != prev_regime
            if os.environ.get("TARGETED_REPLAY_DEBUG"):
                print(f"DEBUG m_ts={m_ts} prev_regime={prev_regime} new_regime={new_regime} flip={flip}")
            anchor = bo if flip else None
            gate_anchor = prev_close if (flip and prev_close is not None) else None
            if flip:
                feature_engine.reset_regime(m_ts, anchor)
                shadow.reset_regime(m_ts, anchor)

            if now_rth and not was_rth:
                feature_engine.reset_rth(m_ts)
                shadow.reset_rth(m_ts)
            elif not now_rth and was_rth:
                feature_engine.end_rth()
                shadow.end_rth()
            was_rth = now_rth

            for bts, bh2, bl2, bv2, bd2 in minute_buf:
                feature_engine.accumulate_regime_rth(bts, bh2, bl2, bv2, bd2)
                shadow.accumulate_regime_rth(bts, bh2, bl2, bv2, bd2)
            m_o, m_h, m_l = minute_o, minute_h, minute_l

            feature_engine.update_1m(m_ts, m_o, m_h, m_l,
                                     prev_close if prev_close is not None else bo, now_rth)
            minute_buf = []

            if flip:
                flip_log.append({"flip_ts": m_ts, "direction": new_regime})
                candidate_tracker.on_regime_flip(m_ts, new_regime, gate_anchor, engine.atr)

        # Candidate declaration -- every 1s bar, matches strategy.py.
        minute_of_day_ts = pd.Timestamp(ts, unit="ns", tz="UTC").tz_convert("America/Chicago")
        minute_of_day = minute_of_day_ts.hour * 60 + minute_of_day_ts.minute
        candidate_tracker.on_1s_bar(ts_ns=ts, high=h, low=l, close=c, minute_of_day=minute_of_day)

        if (i + 1) % 20000 == 0:
            print(f"[targeted-replay] {i+1:,}/{n:,} bars, {len(candidate_rows)} established "
                 f"candidates so far, per-bar divergences={per_bar_divergence_count}")

    # -- summary --
    n_candidates = len(candidate_rows)
    classifications: dict[str, int] = {}
    first_candidate_divergence = None
    mismatches_only = []
    for row in candidate_rows:
        for feat, r in row["report"].items():
            cls = r["classification"]
            classifications[cls] = classifications.get(cls, 0) + 1
            if cls not in ("all_agree", "no_offline_reference"):
                if first_candidate_divergence is None:
                    first_candidate_divergence = {**row, "feature": feat, "detail": r}
                mismatches_only.append({
                    "regime_start_ns": row["regime_start_ns"], "checkpoint_index": row["checkpoint_index"],
                    "observation_time_ns": row["observation_time_ns"], "fill_ts_ns": row["fill_ts_ns"],
                    "feature": feat, **r,
                })
    (OUT_DIR / "candidate_mismatches.json").write_text(json.dumps(mismatches_only, indent=2, default=str))
    all_rows_out = [
        {"regime_start_ns": row["regime_start_ns"], "checkpoint_index": row["checkpoint_index"],
         "observation_time_ns": row["observation_time_ns"], "fill_ts_ns": row["fill_ts_ns"],
         **{f"{feat}__{k}": v for feat, r in row["report"].items() for k, v in r.items()}}
        for row in candidate_rows
    ]
    pd.DataFrame(all_rows_out).to_parquet(OUT_DIR / "all_candidate_comparisons.parquet", index=False)

    summary = {
        "n_bars": n, "n_1m_bars": len(replay_1m), "n_candidates_established": n_candidates,
        "per_bar_checked": per_bar_checked, "per_bar_divergence_count": per_bar_divergence_count,
        "per_bar_first_divergence": per_bar_first_divergence,
        "candidate_classification_counts": classifications,
        "first_candidate_level_divergence": first_candidate_divergence,
        "duplicate_update_ts_count": sum(1 for v in shadow.update_count_by_ts.values() if v > 1),
        "out_of_order_update_count": shadow.out_of_order_count,
        "n_flips": len(flip_log),
    }
    out_path = OUT_DIR / "first_divergence_report.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[targeted-replay] wrote {out_path}")
    print(json.dumps({k: v for k, v in summary.items() if k not in
                      ("per_bar_first_divergence", "first_candidate_level_divergence")}, indent=2, default=str))
    if per_bar_first_divergence:
        print("PER-BAR FIRST DIVERGENCE:")
        print(json.dumps(per_bar_first_divergence, indent=2, default=str))
    if first_candidate_divergence:
        print("CANDIDATE-LEVEL FIRST DIVERGENCE:")
        print(json.dumps(first_candidate_divergence, indent=2, default=str))


if __name__ == "__main__":
    main()
