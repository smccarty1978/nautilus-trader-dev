"""
Contextual Runner Exit v3 — shared infrastructure.

Reuses the v2 execution stack verbatim (non-negotiable per spec):
  * sim_v2 (repaired terminal resolution, truncation, next-1s-open fills,
    1s stop monitoring) from exit_optimal_stopping/repair/sim_v2.py
  * the v2 causal MTF context cache (full_context_features.parquet) — already
    audited for causality in v2 (feature_provenance_audit.json); rebuilding it
    would reproduce identical numbers at ~10min extra cost, so v3 loads the
    cached parquet directly. This is a documented conservative assumption.
  * the v2 raw checkpoint regime-state assignment (build_regime_state_machine)
    as the RAW input to v3's own smoothing layer (Phase 1). v3 does NOT
    redefine the raw state formula; it fixes the flicker/tautology problem by
    adding dwell + confirmation smoothing on top (see smooth_regime_states.py).

Splits (frozen, from the atlas `period` column):
    train = 2024-01-01 .. 2024-12-31
    val   = 2025-01-01 .. 2025-02-28
    test  = 2025-03-01 .. 2025-05-31   (DEVELOPMENT TEST — previously inspected)
"""

from __future__ import annotations
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

# Windows console default codepage (cp1252) can't encode Delta/arrows used in
# report text; force utf-8 stdout/stderr so print() never crashes mid-report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Paths ───────────────────────────────────────────────────────────────────
REPO = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader")
EOS = REPO / "studies/rl_regime_feasibility/exit_optimal_stopping"
EOS_RESULTS = EOS / "results"
V2 = REPO / "studies/rl_regime_feasibility/contextual_runner_exit_v2"
V2_RESULTS = V2 / "results"
V3 = REPO / "studies/rl_regime_feasibility/contextual_runner_exit_v3"
RESULTS = V3 / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
CACHE = V3 / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

ATLAS_CHK = EOS_RESULTS / "exit_atlas_checkpoints.parquet"
ATLAS_TRADES = EOS_RESULTS / "exit_atlas_trades.parquet"
V2_CONTEXT_CACHE = V2 / "cache" / "full_context_features.parquet"

# reuse the repaired execution stack + v2 modules
sys.path.insert(0, str(EOS / "repair"))
sys.path.insert(0, str(V2))
import sim_v2  # noqa: E402
import build_regime_state_machine as BS  # noqa: E402  (raw state assignment)

# ── Constants (mirror sim_v2 / v2) ──────────────────────────────────────────
NQ_MULT = 20.0
COMMISSION = 5.0
STOP_ATR = 1.5
MIN_ELIG_S = 30
NQ_TICK = 0.25

STATES = ["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED", "ORDINARY", "WEAKENING", "TERMINAL"]

# compact local feature set (mirrors v2 LOCAL_CANDIDATES; used for fitted-Q P1a/P1b)
LOCAL_CANDIDATES = [
    "current_progress_atr", "max_progress_atr", "max_adverse_atr",
    "pullback_from_peak_atr", "seconds_since_peak", "progress_efficiency",
    "aligned_return_5s_atr", "aligned_return_15s_atr", "aligned_return_30s_atr",
    "aligned_return_60s_atr", "realized_vol_60s_atr", "range_5s_atr",
    "volume_5s_zscore", "volume_30s_vs_5m", "kalman_velocity_atr_per_s",
    "kalman_acceleration_atr_per_s2", "kalman_innovation_zscore",
    "ema3_ema9_spread_30s_atr", "regime_5s_aligned", "regime_30s_aligned",
    "regime_5m_aligned", "regime_age_1m_bars", "adx14_1m",
    "position_in_trailing_1m_range", "knn_hA", "knn_hB", "knn_hC",
    "knn_composite", "unrealized_pnl_atr", "seconds_since_entry",
    "trade_mfe_atr", "trade_mae_atr", "giveback_from_mfe_atr", "giveback_fraction",
]

# compact structural-confirmation MTF columns needed (subset of v2's 133-col context)
NEEDED_CTX_COLS = [
    "aligned_return_30s", "aligned_return_180s", "aligned_return_300s",
    "aligned_slope_180s", "aligned_slope_300s", "directional_efficiency_180s",
    "structure_intact_5m", "structure_break_against_5m",
    "structure_intact_3m", "structure_break_against_3m",
    "ema_slope_3m", "ema_slope_5m",
]

NEEDED_ATLAS = [
    "current_progress_atr", "max_progress_atr", "max_adverse_atr",
    "pullback_from_peak_atr", "seconds_since_peak", "progress_efficiency",
    "aligned_return_5s_atr", "aligned_return_15s_atr", "aligned_return_30s_atr",
    "aligned_return_60s_atr", "realized_vol_60s_atr", "range_5s_atr",
    "volume_5s_zscore", "volume_30s_vs_5m", "kalman_velocity_atr_per_s",
    "kalman_acceleration_atr_per_s2", "kalman_innovation_zscore",
    "ema3_ema9_spread_30s_atr", "regime_5s_aligned", "regime_30s_aligned",
    "regime_5m_aligned", "regime_age_1m_bars", "adx14_1m",
    "position_in_trailing_1m_range", "knn_hA", "knn_hB", "knn_hC",
    "knn_composite", "unrealized_pnl_atr", "trade_mfe_atr", "trade_mae_atr",
    "giveback_from_mfe_atr", "giveback_fraction",
    "entry_px_y", "stop_px_y", "exit_now_pnl", "atr_at_flip",
    "minutes_since_rth_open",
]


def is_rth_from_minutes(m: np.ndarray) -> np.ndarray:
    return ((m >= 0) & (m <= 390)).astype(int)


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


def load_atlas():
    chk = pd.read_parquet(ATLAS_CHK)
    chk = chk.sort_values(["episode_id", "seconds_since_entry"]).reset_index(drop=True)
    trades = pd.read_parquet(ATLAS_TRADES)
    return chk, trades


def make_ep_meta(chk_p):
    epx = "entry_px_y" if "entry_px_y" in chk_p.columns else "entry_px"
    m = chk_p.groupby("episode_id").first()[[epx, "direction"]].rename(columns={epx: "entry_px"})
    return m


def Xmat(df, feats):
    return df[feats].fillna(0).to_numpy(dtype=np.float32)


def elig(df):
    return df["seconds_since_entry"] >= MIN_ELIG_S


def policy_pnl(df, sig, ep_base, ep_meta, bars):
    """Per-episode PnL Series: first-signal exit (next-1s-open fill), else E0.
    Shared execution helper -- identical semantics across every policy script."""
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


def prep_period(df, tt, tag):
    tt_p = tt[tt["period"] == tag]
    ep_base = sim_v2.build_ep_base(df, tt_p)
    ep_meta = make_ep_meta(df)
    return ep_base, ep_meta


# ── Cached base-data preparation (shared by every phase script) ────────────
_PREP_CACHE = CACHE / "prepared_full.parquet"
_PREP_TRADES_CACHE = CACHE / "prepared_trades.parquet"
_BARS_CACHE = {}


_BARS_NPY = CACHE / "bars_1s.npy"


def load_bars():
    """1s bars: in-process cache, backed by an npy file cache across process runs."""
    if "bars" in _BARS_CACHE:
        return _BARS_CACHE["bars"]
    if _BARS_NPY.exists():
        arr = np.load(_BARS_NPY)
        _BARS_CACHE["bars"] = arr
        return arr
    BAR_LO = int(pd.Timestamp("2023-12-30", tz="UTC").value)
    BAR_HI = int(pd.Timestamp("2025-06-05", tz="UTC").value)
    import build_full_mtf_context as BF  # noqa: E402
    arr = BF.C.load_1s_full(BAR_LO, BAR_HI)
    np.save(_BARS_NPY, arr)
    _BARS_CACHE["bars"] = arr
    return arr


def prepare_base(force: bool = False):
    """
    Returns (train, val, test, tt) where train/val/test are truncated,
    hold_advantage-labeled checkpoint frames carrying:
      - LOCAL_CANDIDATES + NEEDED_CTX_COLS + execution cols
      - raw regime `state` (+ transition bookkeeping) from v2's state machine
      - `is_rth`, `local_weak` (raw, causal)
    tt = trades with true_terminal_ts resolved (train+val+test).

    Cached to cache/prepared_full.parquet / prepared_trades.parquet after the
    first call in this environment.
    """
    if not force and _PREP_CACHE.exists() and _PREP_TRADES_CACHE.exists():
        full = pd.read_parquet(_PREP_CACHE)
        tt = pd.read_parquet(_PREP_TRADES_CACHE)
        train = full[full["period"] == "train"].reset_index(drop=True)
        val = full[full["period"] == "val"].reset_index(drop=True)
        test = full[full["period"] == "test"].reset_index(drop=True)
        return train, val, test, tt

    print("[prepare_base] building from scratch (cache miss) ...")
    ctx = pd.read_parquet(V2_CONTEXT_CACHE, columns=[
        "episode_id", "observation_time", "seconds_since_entry", "direction",
        "period"] + [c for c in NEEDED_CTX_COLS])
    atlas, trades = load_atlas()
    atlas = atlas[atlas["period"].isin(["train", "val", "test"])].reset_index(drop=True)
    assert (atlas["episode_id"].values == ctx["episode_id"].values).all() and \
        (atlas["observation_time"].values == ctx["observation_time"].values).all(), \
        "context/atlas row alignment mismatch"

    present = [c for c in NEEDED_ATLAS if c in atlas.columns]
    for c in present:
        vals = atlas[c].values
        ctx[c] = vals.astype(np.float32) if atlas[c].dtype == np.float64 and c not in (
            "entry_px_y", "stop_px_y", "exit_now_pnl", "atr_at_flip") else vals
    ctx["is_rth"] = is_rth_from_minutes(ctx["minutes_since_rth_open"].values)

    # local_weak (raw, causal) — same definition v2 used to drive both the
    # raw state machine AND the P2 policy trigger (documented coupling; v3
    # smoothing (Phase 1) is what decouples state-at-decision from this flag).
    ar30 = ctx.get("aligned_return_30s", pd.Series(np.zeros(len(ctx)))).fillna(0)
    gb = ctx["giveback_fraction"].fillna(0)
    ctx["local_weak"] = ((ar30 < 0) | (gb > 0.25)).astype(bool)

    del atlas
    import gc
    gc.collect()

    # raw regime state machine (v2, unmodified formula)
    full = BS.build(ctx)

    # terminal resolution + truncation + hold_advantage (sim_v2, unmodified)
    bars = load_bars()
    tt = trades[trades["period"].isin(["train", "val", "test"])].copy()
    tt = sim_v2.resolve_terminal_events(tt, bars)
    full = sim_v2.truncate_checkpoints(full, tt)
    full = sim_v2.compute_hold_advantage(full)

    # ghost-row invariants
    term_map = tt.set_index("episode_id")["true_terminal_ts"]
    obs_vs_term = full["observation_time"].values - full["episode_id"].map(term_map).values
    post_terminal = int((obs_vs_term > 0).sum())
    assert post_terminal == 0, f"{post_terminal} post-terminal ghost rows remain"
    dup_rows = int(full.duplicated(["episode_id", "observation_time"]).sum())
    assert dup_rows == 0, "duplicate checkpoint rows"

    full.to_parquet(_PREP_CACHE, index=False)
    tt.to_parquet(_PREP_TRADES_CACHE, index=False)

    train = full[full["period"] == "train"].reset_index(drop=True)
    val = full[full["period"] == "val"].reset_index(drop=True)
    test = full[full["period"] == "test"].reset_index(drop=True)
    return train, val, test, tt
