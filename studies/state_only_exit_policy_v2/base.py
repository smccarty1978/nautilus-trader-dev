"""
State-Only Exit Policy v2 -- shared infrastructure.

ISOLATED from contextual_runner_exit_v3/ and regime_sequence_chop_context/:
this study reads their frozen artifacts as READ-ONLY canonical inputs and
never writes into their directories.

Canonical inputs reused verbatim (per spec, non-negotiable):
  * v3's cache/prepared_full.parquet -- truncated, hold_advantage-labeled
    checkpoints from the REPAIRED sim_v2 stack (post stop-fill-price fix).
  * v3's cache/prepared_trades.parquet -- trades with true_terminal_ts
    resolved by the same repaired sim_v2.resolve_terminal_events.
  * v3's results/smoothed_state_checkpoints.parquet -- the FROZEN smoothed
    state stream (dwell30_c3 config, results/frozen_state_smoothing.json).
  * v3's cache/bars_1s.npy -- the same 1s bar array.
  * exit_optimal_stopping/repair/sim_v2.py -- the repaired execution stack
    (next-1s-open fills, 1s stop monitoring, truncation). Same module v3
    uses; already audited and fixed (phantom-fill bug) in the v3 session.

This study does NOT use fitted-Q scores in any primary policy. LOCAL_CANDIDATES
/ model training code from v3 is intentionally NOT imported here.

Splits (frozen):
    train = 2024-01-01 .. 2024-12-31
    val   = 2025-01-01 .. 2025-02-28
    test  = 2025-03-01 .. 2025-05-31   (DEVELOPMENT TEST -- previously inspected)
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Paths ───────────────────────────────────────────────────────────────────
REPO = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader")
EOS = REPO / "studies/rl_regime_feasibility/exit_optimal_stopping"
V3 = REPO / "studies/rl_regime_feasibility/contextual_runner_exit_v3"
V3_RESULTS = V3 / "results"
V3_CACHE = V3 / "cache"
V2 = REPO / "studies/rl_regime_feasibility/contextual_runner_exit_v2"
V2_CONTEXT_CACHE = V2 / "cache" / "full_context_features.parquet"  # pb_max_depth (Family-G), read-only

STUDY = REPO / "studies/state_only_exit_policy_v2"
RESULTS = STUDY / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
CACHE = STUDY / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

# canonical read-only v3 artifacts
V3_PREPARED_FULL = V3_CACHE / "prepared_full.parquet"
V3_PREPARED_TRADES = V3_CACHE / "prepared_trades.parquet"
V3_BARS_NPY = V3_CACHE / "bars_1s.npy"
V3_SMOOTHED_STATE = V3_RESULTS / "smoothed_state_checkpoints.parquet"
V3_FROZEN_SMOOTHING = V3_RESULTS / "frozen_state_smoothing.json"

sys.path.insert(0, str(EOS / "repair"))
import sim_v2  # noqa: E402  (repaired: next_1s_open, detect_stop_hit, resolve_terminal_events, ...)

# ── Constants (mirror sim_v2 / v3) ──────────────────────────────────────────
NQ_MULT = 20.0
COMMISSION = 5.0
STOP_ATR = 1.5
MIN_ELIG_S = 30
NQ_TICK = 0.25
CHECKPOINT_S = 5  # decision-spine spacing

STATES = ["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED", "ORDINARY", "WEAKENING", "TERMINAL"]


def s_to_ck(seconds: float) -> int:
    return int(round(seconds / CHECKPOINT_S))


def elig(df):
    return df["seconds_since_entry"] >= MIN_ELIG_S


def paired_bootstrap_ci(deltas: np.ndarray, n_boot: int = 5000, seed: int = 42):
    d = np.asarray(deltas, dtype=np.float64)
    d = d[~np.isnan(d)]
    if len(d) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    n = len(d)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = d[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def savej(obj, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"  wrote {path.name}")


def consecutive_run(mask: np.ndarray, codes: np.ndarray) -> np.ndarray:
    """Consecutive-True run length ending at each row, reset at episode
    boundaries and at any False. O(n) single pass."""
    n = len(mask)
    run = np.zeros(n, dtype=np.int32)
    for i in range(n):
        if mask[i]:
            run[i] = run[i - 1] + 1 if (i > 0 and codes[i] == codes[i - 1] and mask[i - 1]) else 1
        else:
            run[i] = 0
    return run


def make_ep_meta(chk_p):
    epx = "entry_px_y" if "entry_px_y" in chk_p.columns else "entry_px"
    m = chk_p.groupby("episode_id").first()[[epx, "direction"]].rename(columns={epx: "entry_px"})
    return m


def prep_period(df, tt, tag):
    tt_p = tt[tt["period"] == tag]
    ep_base = sim_v2.build_ep_base(df, tt_p)
    ep_meta = make_ep_meta(df)
    return ep_base, ep_meta


def policy_pnl(df, sig, ep_base, ep_meta, bars):
    """Per-episode PnL Series: first-signal exit (next-1s-open fill), else E0."""
    result = ep_base["e0_pnl"].copy()
    sig_bool = sig.values if hasattr(sig, "values") else sig
    trig = df[sig_bool]
    if len(trig):
        trig = trig.sort_values("seconds_since_entry")
        fired = (trig.groupby("episode_id")["observation_time"].first()
                 .reset_index().rename(columns={"observation_time": "sig_ts"}))
        fired = fired.merge(ep_meta[["entry_px", "direction"]],
                             left_on="episode_id", right_index=True, how="left")
        obs = fired["sig_ts"].values.astype(np.float64)
        fi = np.searchsorted(bars[:, 0], obs, side="right")
        valid = fi < len(bars)
        fic = fi.clip(0, len(bars) - 1)
        fpx = np.where(valid, bars[fic, 1], np.nan)
        pnl = (fpx - fired["entry_px"].values) * fired["direction"].values * NQ_MULT - COMMISSION
        fired["pnl"] = pnl
        bad = ~valid
        if bad.any():
            fired.loc[bad, "pnl"] = fired.loc[bad, "episode_id"].map(ep_base["e0_pnl"]).values
        result.loc[fired["episode_id"].values] = fired["pnl"].values
    return result


def policy_exit_info(df, sig, ep_base, ep_meta, bars):
    """Like policy_pnl but ALSO returns, per episode, the actual decision_ts
    and fill_ts this SPECIFIC policy used (or NaN if it never fired, i.e.
    resolved by E0/regime-terminal). This is the input required for
    Phase-10 policy-specific state attribution -- every policy must derive
    its own exit timestamps, never reuse another policy's."""
    n = len(ep_base)
    decision_ts = pd.Series(np.full(n, np.nan), index=ep_base.index)
    fill_ts = pd.Series(np.full(n, np.nan), index=ep_base.index)
    pnl = ep_base["e0_pnl"].copy()

    sig_bool = sig.values if hasattr(sig, "values") else sig
    trig = df[sig_bool]
    if len(trig):
        trig = trig.sort_values("seconds_since_entry")
        fired = (trig.groupby("episode_id")["observation_time"].first()
                 .reset_index().rename(columns={"observation_time": "sig_ts"}))
        fired = fired.merge(ep_meta[["entry_px", "direction"]],
                             left_on="episode_id", right_index=True, how="left")
        obs = fired["sig_ts"].values.astype(np.float64)
        fi = np.searchsorted(bars[:, 0], obs, side="right")
        valid = fi < len(bars)
        fic = fi.clip(0, len(bars) - 1)
        fill_ts_arr = np.where(valid, bars[fic, 0], np.nan)
        fpx = np.where(valid, bars[fic, 1], np.nan)
        pnl_arr = (fpx - fired["entry_px"].values) * fired["direction"].values * NQ_MULT - COMMISSION
        fired["pnl"] = pnl_arr
        fired["fill_ts"] = fill_ts_arr
        bad = ~valid
        if bad.any():
            fired.loc[bad, "pnl"] = fired.loc[bad, "episode_id"].map(ep_base["e0_pnl"]).values
            fired.loc[bad, "fill_ts"] = np.nan
        decision_ts.loc[fired["episode_id"].values] = fired["sig_ts"].values
        fill_ts.loc[fired["episode_id"].values] = fired["fill_ts"].values
        pnl.loc[fired["episode_id"].values] = fired["pnl"].values
    return pnl, decision_ts, fill_ts


# ── Cached base-data loading (read-only from v3) ────────────────────────────
_BARS_CACHE = {}


def load_bars():
    if "bars" in _BARS_CACHE:
        return _BARS_CACHE["bars"]
    assert V3_BARS_NPY.exists(), f"missing canonical bars cache: {V3_BARS_NPY}"
    arr = np.load(V3_BARS_NPY)
    _BARS_CACHE["bars"] = arr
    return arr


def load_base(force: bool = False):
    """Returns (train, val, test, tt) -- v3's repaired, truncated,
    hold_advantage-labeled checkpoints (READ-ONLY reuse), with the FROZEN
    smoothed_state stream merged on. No fitted-Q features included."""
    assert V3_PREPARED_FULL.exists(), (
        f"missing canonical prepared data: {V3_PREPARED_FULL}. "
        "Run contextual_runner_exit_v3/base.prepare_base() first (read-only reuse, "
        "do not regenerate here).")
    assert V3_SMOOTHED_STATE.exists(), f"missing frozen smoothed-state stream: {V3_SMOOTHED_STATE}"

    keep_cols = ["episode_id", "observation_time", "seconds_since_entry", "period",
                 "direction", "is_rth", "atr_at_flip", "entry_px_y", "stop_px_y",
                 "current_progress_atr", "max_progress_atr", "max_adverse_atr",
                 "pullback_from_peak_atr", "seconds_since_peak", "trade_mfe_atr",
                 "trade_mae_atr", "giveback_from_mfe_atr", "giveback_fraction",
                 "unrealized_pnl_atr", "minutes_since_rth_open", "exit_now_pnl"]
    full = pd.read_parquet(V3_PREPARED_FULL)
    present = [c for c in keep_cols if c in full.columns]
    full = full[present].copy()

    sm = pd.read_parquet(V3_SMOOTHED_STATE, columns=[
        "episode_id", "observation_time", "smoothed_state", "previous_smoothed_state",
        "seconds_in_smoothed_state", "transition_confirmed", "transition_candidate"])
    merged = full.merge(sm, on=["episode_id", "observation_time"], how="left")
    assert len(merged) == len(full), "smoothed-state merge changed row count"
    assert merged["smoothed_state"].notna().all(), "unmatched smoothed-state rows"

    tt = pd.read_parquet(V3_PREPARED_TRADES)

    train = merged[merged["period"] == "train"].reset_index(drop=True)
    val = merged[merged["period"] == "val"].reset_index(drop=True)
    test = merged[merged["period"] == "test"].reset_index(drop=True)
    return train, val, test, tt
