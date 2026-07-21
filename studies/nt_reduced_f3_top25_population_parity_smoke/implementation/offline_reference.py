"""Phase 1 -- fresh offline March 2025 reference: candidate population
(every established+RTH+valid-fill checkpoint from `prepared_2025.parquet`,
which IS this exact funnel's output -- confirmed against
`short_rth_entry_surface_backfill/entry_surface.py`), scored fresh with the
persisted `F3_top25_gbt_v1` model, frozen R5/R2.5 thresholds applied.

Not a filtered old trigger schedule: this re-derives candidate keys, scores,
and trigger flags directly from the frozen model + frozen thresholds against
the causally-lineaged feature population, per SPEC.md Phase 1.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import common as C

_ROOT = str(C.ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if str(C.POC) not in sys.path:
    sys.path.insert(0, str(C.POC))
from trade_state import FlipTradeState, favorable_adverse_points  # noqa: E402

EXTRA_COLS = ["regime_start_ns", "observation_time", "entry_ts", "entry_px",
             "atr_at_entry", "entry_direction", "confirm_flip_ns",
             "regime_age_s", "running_mfe_atr", "running_mae_atr",
             "new_progress_windows", "retained_mfe_ratio"]


def is_rth(ts_ns: int) -> bool:
    t = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
    minute = t.hour * 60 + t.minute
    return C.RTH_START_MIN <= minute < C.RTH_END_MIN


def build_candidates() -> pd.DataFrame:
    verified = C.verify_frozen_model_inputs()
    feat_list = verified["feature_list"]
    model = joblib.load(C.MODEL_PATH)

    thresholds = json.loads((C.CONFIG / "frozen_thresholds.json").read_text())
    top5, top2_5 = thresholds["top_5pct_threshold"], thresholds["top_2_5pct_threshold"]

    df = pd.read_parquet(C.PREPARED_2025_PATH, columns=feat_list + EXTRA_COLS)
    obs_dt = pd.to_datetime(df["observation_time"], unit="ns", utc=True)
    month_mask = obs_dt.dt.strftime("%Y-%m") == C.SELECTED_MONTH
    df = df.loc[month_mask].sort_values(["regime_start_ns", "observation_time"]).reset_index(drop=True)
    assert (df["entry_direction"] == -1).all()

    scores = model.predict_proba(df[feat_list])[:, 1]
    df["score"] = scores
    df["r5_trigger"] = scores >= top5
    df["r2_5_trigger"] = scores >= top2_5

    df["checkpoint_index"] = np.round(
        (df["observation_time"] - df["regime_start_ns"]) / (C.CANDIDATE_STEP_S * 1_000_000_000)
    ).astype(np.int64) - 1
    df["regime_direction"] = 1  # established-bullish prevailing regime, entry_direction=-1 (short)

    df["fill_ts"] = df["entry_ts"]
    df["fill_px"] = df["entry_px"]
    df["decision_rth"] = df["observation_time"].apply(is_rth)
    df["fill_rth"] = df["fill_ts"].apply(is_rth)
    df["suppression_reason"] = None

    for variant, col in (("r5", "r5_trigger"), ("r2_5", "r2_5_trigger")):
        df[f"{variant}_is_first_trigger_in_regime"] = False
        for regime_start, idx in df.groupby("regime_start_ns", sort=False).groups.items():
            sub = df.loc[idx]
            triggered = sub[sub[col]]
            if len(triggered):
                first_idx = triggered.index[0]
                df.loc[first_idx, f"{variant}_is_first_trigger_in_regime"] = True

    null_mask_cols = {f"{f}__is_null": df[f].isna() for f in feat_list}
    for k, v in null_mask_cols.items():
        df[k] = v

    ordered_cols = (
        ["regime_start_ns", "regime_direction", "checkpoint_index", "observation_time",
         "confirm_flip_ns", "fill_ts", "fill_px", "atr_at_entry", "decision_rth", "fill_rth",
         "regime_age_s", "running_mfe_atr", "running_mae_atr", "new_progress_windows",
         "retained_mfe_ratio",
         "score", "r5_trigger", "r2_5_trigger",
         "r5_is_first_trigger_in_regime", "r2_5_is_first_trigger_in_regime", "suppression_reason"]
        + feat_list + list(null_mask_cols.keys())
    )
    return df[ordered_cols]


def _load_timeline():
    for p in (C.ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
             C.ROOT / "studies" / "regime_sequence_chop_context"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from CODEX_5_X_run_established_fade import canonical_regime_timeline
    from CODEX_5_X_common import RAW_1S
    raw = pd.read_parquet(RAW_1S[2025], columns=["open", "high", "low", "close", "volume"])
    timeline = canonical_regime_timeline(2025, raw).sort_values("regime_start_ns").reset_index(drop=True)
    return timeline


def build_trades(candidates: pd.DataFrame, variant: str, trigger_col: str, first_flag_col: str,
                 timeline: pd.DataFrame) -> pd.DataFrame:
    """Secondary offline trade reference: replays the SAME fixed 1.25xATR
    stop / opposing-flip-exit policy as the NT POC (trade_state.FlipTradeState),
    using raw 1s bars for exit detection and the canonical regime timeline for
    the opposing (bullish) flip that ends the bearish-thesis-confirmed leg.
    One trade per regime, dispatched at the first {variant} trigger."""
    entries = candidates[candidates[first_flag_col]].copy()
    if entries.empty:
        return pd.DataFrame()

    raw = pd.read_parquet(C.ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet",
                          columns=["open", "high", "low", "close"])
    ts = raw.index.view("int64")
    opens = raw["open"].to_numpy(float)
    highs, lows, closes = raw["high"].to_numpy(float), raw["low"].to_numpy(float), raw["close"].to_numpy(float)
    tl_starts = timeline["regime_start_ns"].to_numpy(np.int64)

    trades = []
    for row in entries.itertuples(index=False):
        entry_fill_i = int(np.searchsorted(ts, row.fill_ts, side="left"))
        if entry_fill_i >= len(ts) or int(ts[entry_fill_i]) != int(row.fill_ts):
            continue
        entry_px = float(row.fill_px)
        atr = float(row.atr_at_entry)
        st = FlipTradeState(entry_direction=-1, entry_px=entry_px, atr=atr, stop_atr_mult=C.STOP_ATR_MULT)
        bearish_flip_ts = int(row.confirm_flip_ns)  # established-bullish regime's own end == the bearish flip confirming this short thesis

        # The opposing (bullish) flip that ends the bearish leg: the NEXT
        # regime_start_ns strictly after bearish_flip_ts in the canonical
        # timeline (that timeline alternates direction by construction).
        nxt = int(np.searchsorted(tl_starts, bearish_flip_ts, side="right"))
        opposing_flip_ts = int(tl_starts[nxt]) if nxt < len(tl_starts) else None

        exit_reason, exit_px, exit_ts = None, None, None
        i = entry_fill_i
        n = len(ts)
        while i < n:
            bar_ts = int(ts[i])
            h, l = highs[i], lows[i]
            if st.stop_would_touch(h, l):
                # CRITICAL FIX (pre-execution audit, H4 anti-pattern):
                # crediting exit_px=st.stop_px (the exact trigger level) is
                # the documented systematic-overstatement bug this project's
                # own lookahead-auditor checklist explicitly flags. NT's
                # bar_execution=True stop_market fills at the NEXT bar's
                # open once triggered, not at the trigger price itself --
                # this offline reference now matches that, rather than
                # crediting an optimistic fill this secondary artifact
                # cannot actually achieve.
                if i + 1 >= n:
                    break  # no next bar available to fill at -- excluded, not fabricated
                exit_reason = st.on_stop_touch()
                exit_px = float(opens[i + 1])
                exit_ts = int(ts[i + 1])
                break
            if not st.bearish_flip_confirmed and bar_ts >= bearish_flip_ts:
                st.bearish_flip_confirmed = True
                st.bearish_flip_ts = bearish_flip_ts
            elif (st.bearish_flip_confirmed and opposing_flip_ts is not None
                  and bar_ts >= opposing_flip_ts):
                exit_reason = "opposing_flip_exit"
                exit_px = float(opens[i])  # next available open at/after the flip, matching entry convention
                exit_ts = bar_ts
                break
            i += 1
        if exit_reason is None:
            continue  # neither stop nor opposing flip found in remaining data -- excluded, not fabricated
        gross = (exit_px - entry_px) * (-1) * C.NQ_MULT
        trades.append({
            "variant": variant, "regime_start_ns": row.regime_start_ns,
            "checkpoint_index": row.checkpoint_index, "observation_time": row.observation_time,
            "entry_fill_time": row.fill_ts, "entry_price": entry_px, "atr_entry": atr,
            "exit_reason": exit_reason, "exit_price": exit_px, "exit_fill_time": exit_ts,
            "gross_pnl": gross, "net_pnl": gross - C.COST_RT,
        })
    return pd.DataFrame(trades)


def main() -> None:
    t0 = time.time()
    candidates = build_candidates()
    candidates.to_parquet(C.RESULTS / "offline_candidates_march_2025.parquet", index=False)
    print(f"candidates: {len(candidates)} rows, "
          f"r5_triggers={int(candidates['r5_trigger'].sum())} "
          f"r2_5_triggers={int(candidates['r2_5_trigger'].sum())} "
          f"r5_first_per_regime={int(candidates['r5_is_first_trigger_in_regime'].sum())} "
          f"r2_5_first_per_regime={int(candidates['r2_5_is_first_trigger_in_regime'].sum())}")

    timeline = _load_timeline()
    trades_r5 = build_trades(candidates, "R5", "r5_trigger", "r5_is_first_trigger_in_regime", timeline)
    trades_r2_5 = build_trades(candidates, "R2.5", "r2_5_trigger", "r2_5_is_first_trigger_in_regime", timeline)
    trades = pd.concat([trades_r5, trades_r2_5], ignore_index=True) if len(trades_r5) or len(trades_r2_5) else pd.DataFrame()
    trades.to_parquet(C.RESULTS / "offline_trades_march_2025.parquet", index=False)
    print(f"trades: R5={len(trades_r5)} R2.5={len(trades_r2_5)}")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
