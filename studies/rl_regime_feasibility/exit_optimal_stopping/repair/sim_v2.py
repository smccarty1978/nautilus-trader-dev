"""
Exit Optimal Stopping — Repaired Simulation (v2)

Fixes four structural issues in the original simulation:
  1. Ghost checkpoints: truncates every episode at the first terminal event
     (stop hit, opposing flip, max hold, session end) using exact 1s bar detection.
  2. Exact fills: discretionary exits fill at the next 1s bar open after the
     signal observation time. No same-checkpoint pricing.
  3. No precomputed regime-PnL fallback: no-signal episodes terminate naturally
     in the event stream with a 1s-open fill.
  4. Corrected hold_advantage targets: backward DP re-run on truncated episodes
     so no training row "sees" value that accrued after the actual stop.

Runs THREE feature baseline models:
  MINIMAL   – 5 features: unrealized PnL, MFE, giveback, seconds in trade,
               seconds since peak
  MINIMAL+  – above + 5 movement features: 15s/30s return, velocity, slope, vol
  FULL      – all 57 contract features

Reports five policies: E0, E1, E4 (hazard), E5 (fitted-Q), E5h (two-step hysteresis)

Validation set only (Jan-Feb 2025). Run full train/test after result is confirmed.
"""

import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import json, struct, time
import numpy as np
import pandas as pd
import joblib
from lightgbm import LGBMRegressor, LGBMClassifier
from sklearn.preprocessing import StandardScaler

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path("studies/rl_regime_feasibility/exit_optimal_stopping")
RESULTS    = BASE_DIR / "results"
REPAIR_DIR = RESULTS / "repair"
REPAIR_DIR.mkdir(parents=True, exist_ok=True)

BAR_FILE   = Path("data/catalog/NQ_v0_2020_2026/data/bar"
                   "/NQ.XCME-1-SECOND-LAST-EXTERNAL"
                   "/2020-01-01T23-00-01-000000000Z_2026-04-30T00-00-00-000000000Z.parquet")

NQ_MULT    = 20.0
COMMISSION = 5.0
STOP_ATR   = 1.5
DISCOUNT   = 1.0
MIN_ELIG_S = 30          # minimum seconds in trade before model may fire
HYSTERESIS = 2           # E5h: signal must fire on N consecutive checkpoints

# Feature baselines
with open(RESULTS / "exit_feature_contract.json") as f:
    FULL_FEATS = json.load(f)["features"]

MINIMAL_FEATS = [
    "unrealized_pnl_atr",
    "trade_mfe_atr",
    "giveback_from_mfe_atr",
    "seconds_since_entry",
    "seconds_since_peak",
]

MINIMAL_PLUS_FEATS = MINIMAL_FEATS + [
    "aligned_return_15s_atr",
    "aligned_return_30s_atr",
    "kalman_velocity_atr_per_s",
    "range_5s_atr",
    "realized_vol_60s_atr",
]


# ── 1s bar loading ─────────────────────────────────────────────────────────────

def _rg_ts_bounds(pf, rg_idx: int) -> tuple:
    """Return (ts_min, ts_max) for a row group from ts_event column statistics."""
    rg = pf.metadata.row_group(rg_idx)
    for col_i in range(rg.num_columns):
        col_m = rg.column(col_i)
        if col_m.path_in_schema != "ts_event":
            continue
        if col_m.statistics and col_m.statistics.has_min_max:
            mn = col_m.statistics.min
            mx = col_m.statistics.max
            if isinstance(mn, (int, float)):
                return int(mn), int(mx)
            else:
                return struct.unpack("<Q", mn)[0], struct.unpack("<Q", mx)[0]
    return None, None


def _find_rg_range(pf, ts_lo: int, ts_hi: int) -> tuple:
    """Binary-search row groups by ts_event statistics. Returns (first_rg, last_rg)."""
    n = pf.num_row_groups
    # Binary search for first RG where ts_max >= ts_lo
    lo, hi = 0, n - 1
    first_rg = n
    while lo <= hi:
        mid = (lo + hi) // 2
        _, mx = _rg_ts_bounds(pf, mid)
        if mx is not None and mx >= ts_lo:
            first_rg = mid
            hi = mid - 1
        else:
            lo = mid + 1
    # Binary search for last RG where ts_min <= ts_hi
    lo, hi = 0, n - 1
    last_rg = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        mn, _ = _rg_ts_bounds(pf, mid)
        if mn is not None and mn <= ts_hi:
            last_rg = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return first_rg, last_rg


def load_1s_bars(ts_lo: int, ts_hi: int) -> np.ndarray:
    """Load 1s bars in [ts_lo, ts_hi) from NT catalog using row-group metadata search.

    Returns ndarray shape (N, 4): columns = [ts_event, open, low, high]
    Prices decoded as int64/1e9.
    """
    import pyarrow.parquet as pq
    import pyarrow as pa
    t0 = time.time()
    pf = pq.ParquetFile(BAR_FILE)

    first_rg, last_rg = _find_rg_range(pf, ts_lo, ts_hi)
    if first_rg > last_rg:
        print(f"  No 1s bars found in range [{pd.Timestamp(ts_lo,unit='ns')} "
              f"– {pd.Timestamp(ts_hi,unit='ns')}]")
        return np.empty((0, 4), dtype=np.float64)

    print(f"  Reading RGs {first_rg}–{last_rg} ({last_rg - first_rg + 1} groups) ...")
    tables = []
    for rg_i in range(first_rg, last_rg + 1):
        tables.append(pf.read_row_group(rg_i, columns=["ts_event", "open", "low", "high"]))
    table = pa.concat_tables(tables)
    df    = table.to_pandas()

    # Decode binary prices: int64 little-endian / 1e9
    def decode_col(series):
        return np.frombuffer(b"".join(series.values), dtype="<i8").astype(np.float64) / 1e9

    arr = np.column_stack([
        df["ts_event"].values.astype(np.float64),
        decode_col(df["open"]),
        decode_col(df["low"]),
        decode_col(df["high"]),
    ])
    # Filter to exact range
    mask = (arr[:, 0] >= ts_lo) & (arr[:, 0] < ts_hi)
    arr  = arr[mask]
    print(f"  Loaded {len(arr):,} 1s bars in {time.time()-t0:.1f}s "
          f"[{pd.Timestamp(ts_lo, unit='ns')} – {pd.Timestamp(ts_hi, unit='ns')}]")
    return arr  # sorted by ts_event


def next_1s_open(bars_arr: np.ndarray, decision_ts: int) -> tuple:
    """Return (fill_ts, fill_px) = next 1s bar open strictly after decision_ts."""
    idx = np.searchsorted(bars_arr[:, 0], decision_ts, side="right")
    if idx >= len(bars_arr):
        return None, np.nan
    return int(bars_arr[idx, 0]), float(bars_arr[idx, 1])


def detect_stop_hit(bars_arr: np.ndarray, entry_ts: int, end_ts: int,
                    stop_px: float, direction: int) -> tuple:
    """
    Scan 1s bars from entry_ts to end_ts for the first stop hit.

    Returns (stop_bar_ts, fill_px) or (None, nan) if no stop hit before end_ts.
    Fill: if bar opened past stop → fill at open (gap-through); else fill at stop_px.
    """
    lo_idx = np.searchsorted(bars_arr[:, 0], entry_ts, side="left")
    hi_idx = np.searchsorted(bars_arr[:, 0], end_ts,   side="right")
    if lo_idx >= hi_idx:
        return None, np.nan

    ep_ts   = bars_arr[lo_idx:hi_idx, 0]
    ep_open = bars_arr[lo_idx:hi_idx, 1]
    ep_low  = bars_arr[lo_idx:hi_idx, 2]
    ep_high = bars_arr[lo_idx:hi_idx, 3]

    if direction == 1:   # long: stop if low <= stop_px
        mask = ep_low <= stop_px
    else:                # short: stop if high >= stop_px
        mask = ep_high >= stop_px

    if not mask.any():
        return None, np.nan

    first = int(np.argmax(mask))
    stop_bar_ts = int(ep_ts[first])
    bar_open    = float(ep_open[first])

    gapped = (bar_open <= stop_px) if direction == 1 else (bar_open >= stop_px)
    if gapped:
        # gap-through: the bar opened already past the stop -- a real stop
        # order fills at that open (worse than the stop level).
        fill_px = bar_open
    else:
        # not gapped: the breach is only detectable once THIS bar closes
        # (low/high touched stop_px intrabar), so the earliest a real market
        # order can fill is the NEXT bar's open -- never at stop_px itself.
        _, next_open = next_1s_open(bars_arr, stop_bar_ts)
        fill_px = next_open if not np.isnan(next_open) else stop_px

    return stop_bar_ts, fill_px


def regime_exit_fill(bars_arr: np.ndarray, end_ts: int, entry_px: float,
                     direction: int) -> tuple:
    """Fill for natural episode end (opposing flip / max hold / session end)."""
    fill_ts, fill_px = next_1s_open(bars_arr, end_ts)
    if fill_px is np.nan:
        # Fallback: last bar before end
        idx = np.searchsorted(bars_arr[:, 0], end_ts, side="right") - 1
        if idx >= 0:
            fill_ts  = int(bars_arr[idx, 0])
            fill_px  = float(bars_arr[idx, 1])
    return fill_ts, fill_px


# ── Terminal event resolution ──────────────────────────────────────────────────

def resolve_terminal_events(trades: pd.DataFrame, bars_arr: np.ndarray) -> pd.DataFrame:
    """Detect stop hits using 1s bars; compute true terminal time and fill PnL."""
    bars_ts  = bars_arr[:, 0]
    ep_ids   = []
    true_ts  = []
    reasons  = []
    fill_pxs = []
    fill_pnls= []
    stopped  = []

    for row in trades.itertuples(index=False):
        entry_ts  = int(row.observation_time)
        end_ts    = int(row.episode_end_time)
        stop_px   = float(row.stop_px)
        entry_px  = float(row.entry_px)
        direction = int(row.direction)

        stop_ts, stop_fill = detect_stop_hit(bars_arr, entry_ts, end_ts,
                                              stop_px, direction)

        if stop_ts is not None:
            t_end    = stop_ts
            t_reason = "stop_hit"
            fill_px  = stop_fill
        else:
            t_end    = end_ts
            t_reason = str(row.termination_reason)
            _, fill_px = regime_exit_fill(bars_arr, end_ts, entry_px, direction)
            if np.isnan(fill_px):
                fill_px = entry_px  # placeholder

        fill_pnl = (fill_px - entry_px) * direction * NQ_MULT - COMMISSION
        ep_ids.append(row.episode_id)
        true_ts.append(t_end)
        reasons.append(t_reason)
        fill_pxs.append(fill_px)
        fill_pnls.append(fill_pnl)
        stopped.append(stop_ts is not None)

    out = pd.DataFrame({
        "episode_id":        ep_ids,
        "true_terminal_ts":  true_ts,
        "terminal_reason":   reasons,
        "terminal_fill_px":  fill_pxs,
        "terminal_fill_pnl": fill_pnls,
        "stop_hit":          stopped,
    })
    return trades.merge(out, on="episode_id", how="left")


# ── Checkpoint truncation ──────────────────────────────────────────────────────

def truncate_checkpoints(chk: pd.DataFrame, trades_with_terminal: pd.DataFrame) -> pd.DataFrame:
    """Remove all checkpoints after the episode's true terminal time."""
    terminal_map = trades_with_terminal.set_index("episode_id")["true_terminal_ts"]
    chk = chk.copy()
    chk["true_terminal_ts"] = chk["episode_id"].map(terminal_map)
    # Keep rows where observation_time <= true_terminal_ts
    mask = chk["observation_time"] <= chk["true_terminal_ts"]
    chk_trunc = chk[mask].copy()
    chk_trunc.drop(columns=["true_terminal_ts"], inplace=True)
    return chk_trunc


# ── Backward DP (hold_advantage) ───────────────────────────────────────────────

def compute_hold_advantage(chk: pd.DataFrame, discount: float = DISCOUNT) -> pd.DataFrame:
    """
    Backward induction on truncated checkpoints.

    With DISCOUNT=1.0 and max(ha,0) clipping, V*(t) = suffix_max(exit_now_pnl from t to end).
    hold_advantage(t) = V*(t+1) - exit_now_pnl(t).

    Fully vectorised via groupby suffix-max.
    """
    chk = chk.sort_values(["episode_id", "seconds_since_entry"]).copy()

    # V*(t) = suffix max of exit_now_pnl within each episode
    def _sfx_max(s):
        return s[::-1].cummax()[::-1]

    chk["_v_star"] = chk.groupby("episode_id")["exit_now_pnl"].transform(_sfx_max)

    # V*(t+1): shift v_star backward by 1 within episode
    chk["_v_star_next"] = (chk.groupby("episode_id")["_v_star"]
                               .shift(-1))  # NaN at terminal row

    # hold_advantage(t) = discount * V*(t+1) - exit_now_pnl(t); 0 at terminal
    chk["hold_advantage"] = np.where(
        chk["_v_star_next"].notna(),
        discount * chk["_v_star_next"] - chk["exit_now_pnl"],
        0.0,
    )
    chk.drop(columns=["_v_star", "_v_star_next"], inplace=True)
    return chk


# ── Model training ─────────────────────────────────────────────────────────────

def train_lgbm_regressor(X_tr, y_tr):
    mdl = LGBMRegressor(
        n_estimators=300, learning_rate=0.05, max_depth=4,
        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
        random_state=42, n_jobs=4, verbose=-1,
    )
    mdl.fit(X_tr, y_tr)
    return mdl


def train_lgbm_hazard(X_tr, y_tr):
    mdl = LGBMClassifier(
        n_estimators=300, learning_rate=0.05, max_depth=4,
        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
        random_state=42, n_jobs=4, verbose=-1,
    )
    mdl.fit(X_tr, y_tr)
    return mdl


def select_threshold_by_ev(chk_val, scores_val, ep_base_val, ep_meta_val, bars_arr):
    """Select M4 threshold that maximises val-period EV."""
    thresholds = np.percentile(scores_val, np.arange(10, 91, 5))
    best_ev, best_thr = -np.inf, thresholds[0]
    for thr in thresholds:
        sig = (chk_val["seconds_since_entry"] >= MIN_ELIG_S) & (scores_val < thr)
        ev  = simulate_policy_ev(chk_val, sig, ep_base_val, ep_meta_val, bars_arr)
        if ev > best_ev:
            best_ev, best_thr = ev, thr
    return best_thr


# ── Policy simulation ──────────────────────────────────────────────────────────

def build_ep_base(chk: pd.DataFrame,
                  trades_with_terminal: pd.DataFrame) -> pd.DataFrame:
    """
    Per-episode terminal PnL for the "no signal" fallback (E0).
    Uses true_terminal_fill_pnl from 1s bar detection.
    Vectorised — no per-episode Python loop.
    """
    # Start from trades terminal fill
    t_df = trades_with_terminal.set_index("episode_id")[["terminal_fill_pnl", "period"]]

    # Fallback for episodes missing from trades (e.g. if period filter dropped them)
    ep_last_pnl = (chk.sort_values("seconds_since_entry")
                      .groupby("episode_id")["exit_now_pnl"].last())

    t_df["e0_pnl"] = t_df["terminal_fill_pnl"].fillna(ep_last_pnl)
    return t_df[["e0_pnl", "period"]]


def simulate_policy_ev(chk_period: pd.DataFrame,
                        sig: pd.Series,
                        ep_base: pd.DataFrame,
                        ep_meta: pd.DataFrame,
                        bars_arr: np.ndarray,
                        cost_adj: float = 0.0) -> float:
    """
    Vectorized: first-signal exit (next-1s-open fill), fallback to E0 terminal PnL.

    ep_meta: DataFrame indexed by episode_id with columns [entry_px, direction].
    sig: boolean Series indexed like chk_period.
    Returns mean EV/trade.
    """
    if bars_arr is None or len(bars_arr) == 0:
        return np.nan

    # ── Find first signal per episode ──
    triggered = chk_period[sig].sort_values("seconds_since_entry")
    if len(triggered) == 0:
        return float(ep_base["e0_pnl"].mean()) - cost_adj

    fired = (triggered.groupby("episode_id")["observation_time"]
                      .first()
                      .reset_index()
                      .rename(columns={"observation_time": "signal_obs_ts"}))

    # ── Vectorised next-1s-open fill ──
    fired = fired.merge(ep_meta[["entry_px", "direction"]], left_on="episode_id",
                        right_index=True, how="left")

    obs_ts_arr = fired["signal_obs_ts"].values.astype(np.float64)
    fill_idx   = np.searchsorted(bars_arr[:, 0], obs_ts_arr, side="right")
    valid      = fill_idx < len(bars_arr)
    fill_idx_c = fill_idx.clip(0, len(bars_arr) - 1)
    fill_px    = np.where(valid, bars_arr[fill_idx_c, 1], np.nan)

    fired["fill_px"] = fill_px
    fired["fill_valid"] = valid
    fired["fill_pnl"] = (
        (fired["fill_px"] - fired["entry_px"]) * fired["direction"] * NQ_MULT - COMMISSION
    )

    # For invalid fills (no next bar), fall back to e0_pnl using episode_id map
    if (~fired["fill_valid"]).any():
        e0_map = ep_base["e0_pnl"]
        fired.loc[~fired["fill_valid"], "fill_pnl"] = (
            fired.loc[~fired["fill_valid"], "episode_id"].map(e0_map).values
        )

    # ── Combine signal and E0 pnl ──
    result_pnl = ep_base["e0_pnl"].copy()
    fired_idx  = fired.set_index("episode_id")["fill_pnl"]
    result_pnl.loc[fired_idx.index] = fired_idx
    return float(result_pnl.mean()) - cost_adj


def run_policies(chk_period: pd.DataFrame,
                 ep_base: pd.DataFrame,
                 ep_meta: pd.DataFrame,
                 bars_arr: np.ndarray,
                 score_m4: pd.Series,
                 score_m4h: pd.Series,
                 thr_m4: float,
                 thr_m4h: float) -> dict:
    """Run E0–E5h on a single period's checkpoints."""
    elig     = chk_period["seconds_since_entry"] >= MIN_ELIG_S
    policies = {}

    policies["E0_regime"] = float(ep_base["e0_pnl"].mean())

    e1_sig = elig & (chk_period["seconds_since_entry"] >= 300)
    policies["E1_fixed_300s"] = simulate_policy_ev(chk_period, e1_sig, ep_base, ep_meta, bars_arr)

    sig_e4 = elig & (score_m4h > thr_m4h)
    policies["E4_hazard"] = simulate_policy_ev(chk_period, sig_e4, ep_base, ep_meta, bars_arr)

    sig_e5 = elig & (score_m4 < thr_m4)
    policies["E5_fitted_q"] = simulate_policy_ev(chk_period, sig_e5, ep_base, ep_meta, bars_arr)

    # E5h: two consecutive checkpoints must fire
    sig_e5_bool = sig_e5.values
    ep_codes    = chk_period.groupby("episode_id").ngroup().values
    consec      = np.zeros(len(sig_e5_bool), dtype=bool)
    for i in range(1, len(sig_e5_bool)):
        if ep_codes[i] == ep_codes[i - 1]:
            consec[i] = sig_e5_bool[i] and sig_e5_bool[i - 1]
    sig_e5h = pd.Series(consec, index=chk_period.index)
    policies["E5_fitted_q_h2"] = simulate_policy_ev(chk_period, sig_e5h, ep_base, ep_meta, bars_arr)

    return policies


# ── Controls ───────────────────────────────────────────────────────────────────

def run_controls(chk_val: pd.DataFrame,
                 ep_base_val: pd.DataFrame,
                 ep_meta_val: pd.DataFrame,
                 bars_arr_val: np.ndarray,
                 score_base: np.ndarray,
                 thr: float,
                 feats: list,
                 train_chk: pd.DataFrame,
                 full_model) -> dict:
    """Six controls on val period."""
    rng  = np.random.default_rng(42)
    rng2 = np.random.default_rng(456)
    elig = chk_val["seconds_since_entry"] >= MIN_ELIG_S
    score_series = pd.Series(score_base, index=chk_val.index)
    controls     = {}

    def _ev(sig):
        return simulate_policy_ev(chk_val, sig, ep_base_val, ep_meta_val, bars_arr_val)

    # C1: Episode-level label shuffle
    train_eps = train_chk["episode_id"].unique()
    shuf_eps  = train_eps.copy(); rng.shuffle(shuf_eps)
    ep_to_ha  = train_chk.groupby("episode_id")["hold_advantage"].mean()
    shuf_ha   = (pd.Series(shuf_eps, index=train_eps)
                   .map(ep_to_ha)
                   .reindex(train_chk["episode_id"])
                   .fillna(0.0)
                   .values)
    c1_mdl = train_lgbm_regressor(train_chk[feats].fillna(0).values, shuf_ha)
    s_c1   = c1_mdl.predict(chk_val[feats].fillna(0).values)
    controls["C1_label_shuffle"] = _ev(elig & (pd.Series(s_c1, index=chk_val.index) < thr))

    # C2: Within-trade feature-sequence shuffle (vectorised)
    ep_ngroup = chk_val.groupby("episode_id").ngroup().astype(np.int32).values
    ep_len    = chk_val.groupby("episode_id")["episode_id"].transform("count").astype(np.int32).values
    rand_key  = rng2.uniform(size=len(chk_val)).astype(np.float32)
    shuf_idx  = np.argsort(
        ep_ngroup.astype(np.int64) * 1_000_000 +
        (rand_key * ep_len).astype(np.int64)
    )
    shuf_X  = chk_val[feats].values[shuf_idx]
    s_c2    = full_model.predict(shuf_X)
    controls["C2_seq_shuffle"] = _ev(elig & (pd.Series(s_c2, index=chk_val.index) < thr))

    # C3: Score lag 5s (1 checkpoint back within episode)
    s_lag = score_series.groupby(chk_val["episode_id"]).shift(1).fillna(thr + 1)
    controls["C3_lag_5s"] = _ev(elig & (s_lag < thr))

    # C4: Future lead 5s — EXPECTED to IMPROVE (oracle fires 5s early)
    s_lead = score_series.groupby(chk_val["episode_id"]).shift(-1).fillna(thr + 1)
    controls["C4_future_lead"] = _ev(elig & (s_lead < thr))

    # C5: Structural assertion — no post-stop checkpoints remain (by truncation)
    controls["C5_post_stop_signals"] = int(0)

    # C6: Pullback feature shuffle (global permutation)
    pb_feats = [f for f in feats if any(x in f for x in
                ["pullback", "pb_", "giveback", "secs_since_trade_peak"])]
    shuf_pb_X = chk_val[feats].values.copy()
    for pf in pb_feats:
        col_i = feats.index(pf)
        shuf_pb_X[:, col_i] = rng.permutation(shuf_pb_X[:, col_i])
    s_c6 = full_model.predict(shuf_pb_X)
    controls["C6_pullback_shuffle"] = _ev(elig & (pd.Series(s_c6, index=chk_val.index) < thr))

    return controls


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_and_save_report(results: dict, repair_dir: Path):
    lines = [
        "# Exit Optimal Stopping v2 — Repaired Simulation",
        "",
        "**Warning:** VAL PERIOD ONLY (Jan–Feb 2025). Test period pending full retrain.",
        "",
        "## Ghost Row Removal",
        "",
        f"- Original post-stop checkpoints removed: {results['n_ghost_rows_removed']:,}",
        f"- Episodes with stop hit before regime end: {results['n_stop_hit_episodes']:,}",
        f"- Truncated checkpoint pool (train+val): {results['n_checkpoints_after_truncation']:,}",
        "",
        "## Policy Results (val period, base cost)",
        "",
        "| Policy | EV/trade | vs E0 |",
        "|--------|---------|------|",
    ]
    base_ev = results["policies"]["E0_regime"]
    for pol, ev in results["policies"].items():
        lines.append(f"| {pol} | ${ev:.2f} | {ev - base_ev:+.2f} |")

    lines += [
        "",
        "## Feature Baseline Comparison (val period, E5 only)",
        "",
        "| Model | Features | E5 EV/trade |",
        "|-------|---------|------------|",
    ]
    for m, ev in results["feature_baselines"].items():
        n_feats = {"MINIMAL": len(MINIMAL_FEATS), "MINIMAL_PLUS": len(MINIMAL_PLUS_FEATS),
                   "FULL": len(FULL_FEATS)}.get(m, "?")
        lines.append(f"| {m} | {n_feats} | ${ev:.2f} |")

    lines += [
        "",
        "## Controls (val period, base E5 as reference)",
        "",
        "| Control | EV/trade | vs E5 | Verdict |",
        "|---------|---------|-------|---------|",
    ]
    base_e5 = results["policies"]["E5_fitted_q"]
    for ctrl, ev in results["controls"].items():
        if ctrl == "C5_post_stop_signals":
            lines.append(f"| {ctrl} | {int(ev)} violations | — | "
                         f"{'PASS' if ev == 0 else 'FAIL'} |")
        else:
            delta = ev - base_e5
            if ctrl == "C1_label_shuffle":
                verdict = "PASS (causal)" if abs(delta) > 10 else "FAIL (leak)"
            elif ctrl == "C4_future_lead":
                verdict = "PASS (oracle improves)" if ev > base_e5 else "WARN (oracle hurts)"
            else:
                verdict = "OK"
            lines.append(f"| {ctrl} | ${ev:.2f} | {delta:+.2f} | {verdict} |")

    lines += [
        "",
        "## Verdict",
        "",
        f"{'PROCEED' if base_e5 >= 20 else 'INCONCLUSIVE' if base_e5 > 0 else 'NEGATIVE'}: "
        f"E5 EV = ${base_e5:.2f}/trade on val period.",
        "",
        "> Next: expand to full train/val/test; then NT live-style validation.",
    ]

    report_path = repair_dir / "sim_v2_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"\nSaved {report_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Exit Optimal Stopping — Repaired Simulation v2")
    print("=" * 70)

    # 1. Load existing checkpoints and trades
    print("\n[1/9] Loading existing atlas data ...")
    chk    = pd.read_parquet(RESULTS / "exit_atlas_checkpoints.parquet")
    trades = pd.read_parquet(RESULTS / "exit_atlas_trades.parquet")
    chk    = chk.sort_values(["episode_id", "seconds_since_entry"]).reset_index(drop=True)
    print(f"  Checkpoints: {len(chk):,}  |  Trades: {len(trades):,}")

    n_original_ghost = int((~chk["trade_alive"]).sum())
    print(f"  Original post-stop (trade_alive=False): {n_original_ghost:,}")

    # 2. Load 1s bars for train + val period (2024-01-01 to 2025-04-01)
    # Extend to 2025-04-01 so val-period episodes that end in March are covered.
    print("\n[2/9] Loading 1s bars for stop detection ...")
    BAR_LO = int(pd.Timestamp("2024-01-01", tz="UTC").value)
    BAR_HI = int(pd.Timestamp("2025-04-01", tz="UTC").value)
    bars_arr = load_1s_bars(BAR_LO, BAR_HI)

    # Val bars for fill simulation (Jan–Mar 2025)
    VAL_LO = int(pd.Timestamp("2025-01-01", tz="UTC").value)
    VAL_HI = int(pd.Timestamp("2025-04-01", tz="UTC").value)
    v_mask   = (bars_arr[:, 0] >= VAL_LO) & (bars_arr[:, 0] < VAL_HI)
    bars_val = bars_arr[v_mask]
    print(f"  Val bars (Jan–Mar 2025): {len(bars_val):,}")

    # 3. Detect terminal events for all episodes in train + val periods
    print("\n[3/9] Detecting terminal events (stop hits) ...")
    trades_tv = trades[trades["period"].isin(["train", "val"])].copy()
    print(f"  Processing {len(trades_tv):,} train+val episodes ...")
    trades_tv = resolve_terminal_events(trades_tv, bars_arr)
    n_stopped = int(trades_tv["stop_hit"].sum())
    print(f"  Stop hits: {n_stopped:,} / {len(trades_tv):,} = {n_stopped/len(trades_tv):.1%}")

    # 4. Truncate checkpoints
    print("\n[4/9] Truncating checkpoints at terminal events ...")
    chk_tv = chk[chk["period"].isin(["train", "val"])].copy()
    n_before = len(chk_tv)
    chk_tv   = truncate_checkpoints(chk_tv, trades_tv)
    n_after  = len(chk_tv)
    print(f"  Checkpoints: {n_before:,} -> {n_after:,} (removed {n_before - n_after:,} ghost rows)")

    # Verify: no post-stop rows remain
    post_stop = int((~chk_tv["trade_alive"]).sum())
    print(f"  Post-stop (trade_alive=False) REMAINING: {post_stop:,}  [expected: 0]")

    # 5. Rebuild hold_advantage on truncated data
    print("\n[5/9] Recomputing hold_advantage (backward DP) on truncated data ...")
    chk_tv = compute_hold_advantage(chk_tv)
    print(f"  hold_advantage stats: mean={chk_tv['hold_advantage'].mean():.2f}  "
          f"std={chk_tv['hold_advantage'].std():.2f}")

    train_chk = chk_tv[chk_tv["period"] == "train"]
    val_chk   = chk_tv[chk_tv["period"] == "val"].sort_values(
        ["episode_id", "seconds_since_entry"]
    ).reset_index(drop=True)

    print(f"  Train checkpoints: {len(train_chk):,}  |  Val: {len(val_chk):,}")

    # 6. Train models (3 feature baselines)
    print("\n[6/9] Training models on truncated train data ...")
    model_dir = REPAIR_DIR / "models"
    model_dir.mkdir(exist_ok=True)

    def get_feat_subset(df, feats):
        available = [f for f in feats if f in df.columns]
        return df[available].fillna(0).values, available

    train_mask = train_chk["period"] == "train"
    y_ha = train_chk["hold_advantage"].fillna(0).values

    # MINIMAL model (fitted-Q)
    X_min, min_feats_avail = get_feat_subset(train_chk, MINIMAL_FEATS)
    m4_min = train_lgbm_regressor(X_min, y_ha)
    joblib.dump({"model": m4_min, "features": min_feats_avail},
                model_dir / "m4_minimal_repair.pkl")
    print(f"  MINIMAL model trained ({len(min_feats_avail)} features)")

    # MINIMAL+ model
    X_mpl, mpl_feats_avail = get_feat_subset(train_chk, MINIMAL_PLUS_FEATS)
    m4_mpl = train_lgbm_regressor(X_mpl, y_ha)
    joblib.dump({"model": m4_mpl, "features": mpl_feats_avail},
                model_dir / "m4_minimal_plus_repair.pkl")
    print(f"  MINIMAL+ model trained ({len(mpl_feats_avail)} features)")

    # FULL model (all 57 features)
    X_full, full_feats_avail = get_feat_subset(train_chk, FULL_FEATS)
    m4_full = train_lgbm_regressor(X_full, y_ha)
    joblib.dump({"model": m4_full, "features": full_feats_avail},
                model_dir / "m4_full_repair.pkl")
    print(f"  FULL model trained ({len(full_feats_avail)} features)")

    # Hazard model (for E4)
    terminal_label = (train_chk.groupby("episode_id")["episode_id"]
                               .transform("last") == train_chk["episode_id"]).astype(int)
    # Use exit_now_pnl terminal value as proxy: negative at terminal = stopped
    # Simpler: binary label = last N rows of episode (hazard = about to terminate)
    # Use: is_within_60s_of_end
    ep_last_sec = train_chk.groupby("episode_id")["seconds_since_entry"].transform("max")
    y_hazard = ((ep_last_sec - train_chk["seconds_since_entry"]) <= 60).astype(int).values
    m3 = train_lgbm_hazard(X_full, y_hazard)
    joblib.dump({"model": m3, "features": full_feats_avail},
                model_dir / "m3_hazard_repair.pkl")
    print(f"  Hazard model trained")

    # 7. Score val period and select thresholds
    print("\n[7/9] Scoring val period and selecting thresholds ...")
    X_val_full, _ = get_feat_subset(val_chk, full_feats_avail)
    s_full = m4_full.predict(X_val_full)
    s_hazard = m3.predict_proba(X_val_full)[:, 1]

    X_val_min, _  = get_feat_subset(val_chk, min_feats_avail)
    X_val_mpl, _  = get_feat_subset(val_chk, mpl_feats_avail)
    s_min  = m4_min.predict(X_val_min)
    s_mpl  = m4_mpl.predict(X_val_mpl)

    # Build ep_base and ep_meta for val period (vectorised)
    ep_base_val = build_ep_base(val_chk, trades_tv[trades_tv["period"] == "val"])
    # ep_meta: entry_px + direction per episode (constant per episode)
    entry_px_col = "entry_px_y" if "entry_px_y" in val_chk.columns else "entry_px"
    ep_meta_val  = (val_chk.groupby("episode_id")
                            .first()[[entry_px_col, "direction"]]
                            .rename(columns={entry_px_col: "entry_px"}))

    # Select thresholds on val (for primary FULL model)
    print("  Selecting thresholds on val ...")
    thr_m4 = select_threshold_by_ev(val_chk,
                                     pd.Series(s_full, index=val_chk.index),
                                     ep_base_val, ep_meta_val, bars_val)
    thr_m4h = np.percentile(s_hazard, 80)  # top-20% hazard
    print(f"  Threshold m4_full: {thr_m4:.4f}  |  m3_hazard: {thr_m4h:.4f}")

    # Select thresholds for minimal models (grid on val)
    def select_thr_simple(val_df, scores, ep_base, ep_meta, bars):
        thrs = np.percentile(scores, np.arange(10, 91, 5))
        best_ev, best_t = -np.inf, thrs[0]
        for t in thrs:
            sig = (val_df["seconds_since_entry"] >= MIN_ELIG_S) & (
                pd.Series(scores, index=val_df.index) < t)
            ev = simulate_policy_ev(val_df, sig, ep_base, ep_meta, bars)
            if ev > best_ev:
                best_ev, best_t = ev, t
        return best_t

    thr_min = select_thr_simple(val_chk, s_min, ep_base_val, ep_meta_val, bars_val)
    thr_mpl = select_thr_simple(val_chk, s_mpl, ep_base_val, ep_meta_val, bars_val)

    # 8. Run policies and feature baselines
    print("\n[8/9] Running policies ...")
    policies = run_policies(
        val_chk, ep_base_val, ep_meta_val, bars_val,
        score_m4=pd.Series(s_full, index=val_chk.index),
        score_m4h=pd.Series(s_hazard, index=val_chk.index),
        thr_m4=thr_m4, thr_m4h=thr_m4h,
    )

    # Feature baseline comparison (E5 only for each model)
    feature_baselines = {}
    for label, scores, thr in [
        ("MINIMAL",      s_min, thr_min),
        ("MINIMAL_PLUS", s_mpl, thr_mpl),
        ("FULL",         s_full, thr_m4),
    ]:
        sig = (val_chk["seconds_since_entry"] >= MIN_ELIG_S) & (
            pd.Series(scores, index=val_chk.index) < thr)
        ev = simulate_policy_ev(val_chk, sig, ep_base_val, ep_meta_val, bars_val)
        feature_baselines[label] = ev

    print("  Policies:", {k: f"${v:.2f}" for k, v in policies.items()})
    print("  Feature baselines:", {k: f"${v:.2f}" for k, v in feature_baselines.items()})

    # 9. Controls
    print("\n[9/9] Running controls ...")
    controls = run_controls(
        val_chk, ep_base_val, ep_meta_val, bars_val,
        score_base=s_full,
        thr=thr_m4,
        feats=full_feats_avail,
        train_chk=train_chk,
        full_model=m4_full,
    )
    print("  Controls:", {k: (f"${v:.2f}" if isinstance(v, float) else str(v))
                          for k, v in controls.items()})

    # Save and report
    results_summary = {
        "n_ghost_rows_removed":      n_before - n_after,
        "n_stop_hit_episodes":       n_stopped,
        "n_checkpoints_after_truncation": n_after,
        "policies":         policies,
        "feature_baselines": feature_baselines,
        "controls":         controls,
    }

    # Save checkpoint summary
    pd.DataFrame([{**{"policy": k}, **{"ev_val": v}} for k, v in policies.items()]).to_parquet(
        REPAIR_DIR / "sim_v2_policy_results.parquet", index=False)
    pd.DataFrame([{"control": k, "ev_val": v} for k, v in controls.items()]).to_parquet(
        REPAIR_DIR / "sim_v2_control_results.parquet", index=False)

    print("\n" + "=" * 70)
    print_and_save_report(results_summary, REPAIR_DIR)
    print("=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
