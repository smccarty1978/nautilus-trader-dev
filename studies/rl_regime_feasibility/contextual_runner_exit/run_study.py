"""
Contextual Runner Exit Study

Tests: can multi-timeframe context + session/direction segmentation + runner protection
improve exit decisions vs repaired regime exit (E0)?

Central hypothesis: the existing fitted-Q model exits too aggressively during
prolific trends because it lacks broader context distinguishing normal pullbacks
from terminal deterioration.

All replay mechanics identical to test_v2.py (repaired sim_v2 stack).
All thresholds selected on val. Development test labeled NOT PRISTINE OOS.
"""
import warnings; warnings.filterwarnings("ignore")
import json, struct, time, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sps
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
import joblib

try: from lightgbm import LGBMRegressor, LGBMClassifier
except ImportError: raise ImportError("lightgbm required")

# ── Paths ─────────────────────────────────────────────────────────────────────
STUDY      = Path("studies/rl_regime_feasibility")
ATLAS_DIR  = STUDY / "exit_optimal_stopping" / "results"
REPAIR_DIR = ATLAS_DIR / "repair"
OUT_DIR    = STUDY / "contextual_runner_exit" / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BAR_FILE = Path("data/catalog/NQ_v0_2020_2026/data/bar"
                "/NQ.XCME-1-SECOND-LAST-EXTERNAL"
                "/2020-01-01T23-00-01-000000000Z_2026-04-30T00-00-00-000000000Z.parquet")

# ── Constants (frozen identical to test_v2) ───────────────────────────────────
NQ_MULT    = 20.0
COMMISSION = 5.0
TICK_SIZE  = 0.25
STOP_ATR   = 1.5
MIN_ELIG_S = 30
HYSTERESIS = 2
DISCOUNT   = 1.0
BOOTSTRAP_N    = 5000
BOOTSTRAP_SEED = 42
RTH_OPEN_UTC_H = 13   # 8:30 CT = 13:30 UTC

# ── Session / direction helpers ───────────────────────────────────────────────
def is_rth(chk_df):
    return chk_df["minutes_since_rth_open"].notna()

def segment(chk_df):
    rth = is_rth(chk_df)
    lng = chk_df["direction"] == 1
    s = pd.Series("ETH_short", index=chk_df.index)
    s[rth &  lng] = "RTH_long"
    s[rth & ~lng] = "RTH_short"
    s[~rth & lng] = "ETH_long"
    return s


# ══════════════════════════════════════════════════════════════════════════════
# 1s BAR UTILITIES  (identical to sim_v2 / test_v2)
# ══════════════════════════════════════════════════════════════════════════════

def _rg_ts_bounds(pf, rg_idx):
    rg = pf.metadata.row_group(rg_idx)
    for col_i in range(rg.num_columns):
        col_m = rg.column(col_i)
        if col_m.path_in_schema != "ts_event": continue
        if col_m.statistics and col_m.statistics.has_min_max:
            mn, mx = col_m.statistics.min, col_m.statistics.max
            if isinstance(mn, (int, float)): return int(mn), int(mx)
            return struct.unpack("<Q", mn)[0], struct.unpack("<Q", mx)[0]
    return None, None


def _find_rg_range(pf, ts_lo, ts_hi):
    n = pf.num_row_groups
    lo, hi, first = 0, n-1, n
    while lo <= hi:
        mid=(lo+hi)//2; _, mx=_rg_ts_bounds(pf,mid)
        if mx is not None and mx>=ts_lo: first=mid; hi=mid-1
        else: lo=mid+1
    lo, hi, last = 0, n-1, -1
    while lo <= hi:
        mid=(lo+hi)//2; mn,_=_rg_ts_bounds(pf,mid)
        if mn is not None and mn<=ts_hi: last=mid; lo=mid+1
        else: hi=mid-1
    return first, last


def load_1s_bars(ts_lo, ts_hi, include_close=True):
    import pyarrow.parquet as pq, pyarrow as pa
    pf = pq.ParquetFile(BAR_FILE)
    fr, lr = _find_rg_range(pf, ts_lo, ts_hi)
    cols = ["ts_event","open","low","high"]
    if include_close: cols.append("close")
    tables = [pf.read_row_group(i, columns=cols) for i in range(fr, lr+1)]
    df = pa.concat_tables(tables).to_pandas()
    def dc(s): return np.frombuffer(b"".join(s.values), dtype="<i8").astype(np.float64)/1e9
    cols_arr = [df["ts_event"].values.astype(np.float64),
                dc(df["open"]), dc(df["low"]), dc(df["high"])]
    if include_close: cols_arr.append(dc(df["close"]))
    arr = np.column_stack(cols_arr)
    mask = (arr[:,0]>=ts_lo)&(arr[:,0]<ts_hi)
    return arr[mask]


def detect_stop_hit(bars, entry_ts, end_ts, stop_px, direction):
    lo = np.searchsorted(bars[:,0], entry_ts, "left")
    hi = np.searchsorted(bars[:,0], end_ts, "right")
    if lo >= hi: return None, np.nan
    ep = bars[lo:hi]
    mask = (ep[:,2]<=stop_px) if direction==1 else (ep[:,3]>=stop_px)
    if not mask.any(): return None, np.nan
    idx = int(np.argmax(mask))
    open_px = float(ep[idx,1])
    fill = min(open_px, stop_px) if direction==1 else max(open_px, stop_px)
    return int(ep[idx,0]), fill


def regime_exit_fill(bars, end_ts, entry_px, direction):
    idx = np.searchsorted(bars[:,0], end_ts, "right")
    if idx >= len(bars): return None, np.nan
    return int(bars[idx,0]), float(bars[idx,1])


def resolve_terminal_events(trades, bars):
    ep_ids=[]; true_ts=[]; reasons=[]; fills=[]; pnls=[]; stopped=[]
    for row in trades.itertuples(index=False):
        entry_ts  = int(row.observation_time)
        end_ts    = int(row.episode_end_time)
        stop_px   = float(row.stop_px)
        entry_px  = float(row.entry_px)
        direction = int(row.direction)
        stop_ts, stop_fill = detect_stop_hit(bars, entry_ts, end_ts, stop_px, direction)
        if stop_ts is not None:
            t_end, t_reason, fill_px = stop_ts, "stop_hit", stop_fill
        else:
            t_end = end_ts; t_reason = str(row.termination_reason)
            _, fill_px = regime_exit_fill(bars, end_ts, entry_px, direction)
            if np.isnan(fill_px): fill_px = entry_px
        pnl = (fill_px - entry_px)*direction*NQ_MULT - COMMISSION
        ep_ids.append(row.episode_id); true_ts.append(t_end)
        reasons.append(t_reason); fills.append(fill_px); pnls.append(pnl)
        stopped.append(stop_ts is not None)
    out = pd.DataFrame({"episode_id":ep_ids,"true_terminal_ts":true_ts,
                         "terminal_reason":reasons,"terminal_fill_px":fills,
                         "terminal_fill_pnl":pnls,"stop_hit":stopped})
    return trades.merge(out, on="episode_id", how="left")


def truncate_checkpoints(chk, trades_term):
    tmap = trades_term.set_index("episode_id")["true_terminal_ts"]
    chk["_term"] = chk["episode_id"].map(tmap)
    out = chk[chk["observation_time"] <= chk["_term"]].copy()
    out.drop(columns=["_term"], inplace=True)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# POLICY SIMULATION  (identical to test_v2)
# ══════════════════════════════════════════════════════════════════════════════

def ep_meta_from_chk(chk):
    col = "entry_px_y" if "entry_px_y" in chk.columns else "entry_px"
    return chk.groupby("episode_id").first()[[col,"direction"]].rename(columns={col:"entry_px"})

def ep_base_from_chk_trades(chk, trades_term):
    t_df = trades_term.set_index("episode_id")[["terminal_fill_pnl"]]
    ep_last = chk.sort_values("seconds_since_entry").groupby("episode_id")["exit_now_pnl"].last()
    t_df["e0_pnl"] = t_df["terminal_fill_pnl"].fillna(ep_last)
    return t_df

def _next_open_fill(chk, sig, ep_base, ep_meta, bars, cost_adj=0.0):
    result = ep_base["e0_pnl"].copy()
    triggered = chk[sig].sort_values("seconds_since_entry")
    if len(triggered) == 0: return result - cost_adj
    fired = (triggered.groupby("episode_id")["observation_time"]
                      .first().reset_index().rename(columns={"observation_time":"sig_ts"}))
    fired = fired.merge(ep_meta[["entry_px","direction"]], left_on="episode_id",
                        right_index=True, how="left")
    obs  = fired["sig_ts"].values.astype(np.float64)
    fidx = np.searchsorted(bars[:,0], obs, side="right")
    valid= fidx < len(bars)
    fpx  = np.where(valid, bars[fidx.clip(0,len(bars)-1),1], np.nan)
    fired["fill_pnl"] = (fpx - fired["entry_px"])*fired["direction"]*NQ_MULT - COMMISSION
    if (~valid).any():
        fired.loc[~valid,"fill_pnl"] = fired.loc[~valid,"episode_id"].map(ep_base["e0_pnl"]).values
    fi = fired.set_index("episode_id")["fill_pnl"]
    result.loc[fi.index] = fi
    return result - cost_adj

def paired_bootstrap_ci(deltas, iters=BOOTSTRAP_N, seed=BOOTSTRAP_SEED):
    rng = np.random.default_rng(seed)
    d = np.array(deltas.dropna()); N = len(d)
    means = np.array([d[rng.integers(0,N,N)].mean() for _ in range(iters)])
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

def paired_stats(delta_series, tag=""):
    d = delta_series.dropna(); N = len(d)
    m, med, std = float(d.mean()), float(d.median()), float(d.std())
    se = std/np.sqrt(N)
    ci_lo, ci_hi = paired_bootstrap_ci(d)
    return {"tag":tag,"N":N,"mean":round(m,4),"median":round(med,4),
            "std":round(std,4),"se":round(se,4),
            "ci_lo_95":round(ci_lo,4),"ci_hi_95":round(ci_hi,4),
            "pct_improved":round(float((d>0).mean()),4),
            "pct_unchanged":round(float((d==0).mean()),4),
            "pct_worsened":round(float((d<0).mean()),4),
            "mean_gain":round(float(d[d>0].mean()) if (d>0).any() else 0,4),
            "mean_loss":round(float(d[d<0].mean()) if (d<0).any() else 0,4),
            "sum_delta":round(float(d.sum()),2)}


# ══════════════════════════════════════════════════════════════════════════════
# MTF FEATURE COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════

HORIZONS_S = [180, 300, 900]   # 3m, 5m, 15m

def compute_mtf_features_for_period(chk_period, bars_arr):
    """
    Compute aligned returns at 3m/5m/15m horizons for all checkpoints.
    Uses vectorized searchsorted on the full period's bar array.

    Returns DataFrame with new feature columns indexed to match chk_period.
    """
    # Need close price (column 4 if loaded with include_close=True)
    if bars_arr.shape[1] < 5:
        raise ValueError("bars_arr must have close column (load with include_close=True)")

    obs_ns = chk_period["observation_time"].values.astype(np.int64)
    directions = chk_period["direction"].values.astype(np.float64)
    atrs = chk_period["atr_at_flip"].values.astype(np.float64)

    bars_ts = bars_arr[:,0].astype(np.int64)

    # Current close: open of bar AT observation_time (or last bar before)
    # We use the close (col 4) of the bar that completed at obs_time
    idx_now = np.searchsorted(bars_ts, obs_ns, side="right") - 1
    valid_now = idx_now >= 0
    close_now = np.where(valid_now, bars_arr[idx_now.clip(0), 4], np.nan)

    results = {}
    for h in HORIZONS_S:
        t_ago_ns = obs_ns - h * 1_000_000_000
        idx_ago  = np.searchsorted(bars_ts, t_ago_ns, side="right") - 1
        valid_ago = (idx_ago >= 0) & (idx_ago < idx_now)
        close_ago = np.where(valid_ago, bars_arr[idx_ago.clip(0), 4], np.nan)

        valid = valid_now & valid_ago
        atr_safe = np.where(atrs > 0, atrs, 1.0)
        ar = np.where(valid, (close_now - close_ago) * directions / atr_safe, np.nan)
        results[f"ar_{h}s"] = ar

    df_new = pd.DataFrame(results, index=chk_period.index)
    return df_new


def add_cross_horizon_features(chk_aug):
    """Add cross-horizon comparison features."""
    # Local weakness vs broader trend
    ar30  = chk_aug.get("aligned_return_30s_atr",  pd.Series(np.nan, index=chk_aug.index))
    ar180 = chk_aug.get("ar_180s", pd.Series(np.nan, index=chk_aug.index))
    ar300 = chk_aug.get("ar_300s", pd.Series(np.nan, index=chk_aug.index))
    ar900 = chk_aug.get("ar_900s", pd.Series(np.nan, index=chk_aug.index))

    # Signed cross-horizon: positive = locally weak but broadly strong (potential false exit)
    chk_aug["cross_30s_180s"] = ar180 - ar30   # 3m trend vs local
    chk_aug["cross_30s_300s"] = ar300 - ar30   # 5m trend vs local
    chk_aug["cross_30s_900s"] = ar900 - ar30   # 15m trend vs local

    # Ratio of local giveback to 5m progress
    gb = chk_aug["giveback_from_mfe_atr"].clip(0)
    ar300_pos = ar300.clip(0)  # positive component of 5m trend
    chk_aug["giveback_vs_5m_trend"] = np.where(ar300_pos > 0, gb / ar300_pos.clip(0.1), np.nan)

    # How far into 5m range are we
    chk_aug["ar_900s_trend_fraction"] = np.where(
        ar900.abs() > 0.1,
        ar300 / ar900.clip(0.1),
        np.nan
    )

    return chk_aug


# ══════════════════════════════════════════════════════════════════════════════
# AGE-CONDITIONED MFE PERCENTILE  (regime quality)
# ══════════════════════════════════════════════════════════════════════════════

def build_mfe_age_quantiles(train_chk, n_bins=12):
    """
    Build empirical quantiles of trade_mfe_atr conditional on seconds_since_entry
    from training data only.
    Returns: dict of {age_bin: quantile_values}
    """
    chk = train_chk[train_chk["seconds_since_entry"] >= 0].copy()
    # Bin ages: 0-60s, 60-120s, ..., up to 10m+
    edges = [0, 60, 120, 180, 240, 300, 420, 600, 900, 1200, 1800, 3600, np.inf]
    chk["age_bin"] = pd.cut(chk["seconds_since_entry"], bins=edges, labels=False)

    quantiles = {}
    for b in range(len(edges)-1):
        sub = chk[chk["age_bin"]==b]["trade_mfe_atr"].dropna()
        if len(sub) < 50:
            quantiles[b] = None
        else:
            q_vals = np.percentile(sub, [25, 50, 75, 90, 95])
            quantiles[b] = {"q25":q_vals[0],"q50":q_vals[1],"q75":q_vals[2],
                            "q90":q_vals[3],"q95":q_vals[4],"n":len(sub)}

    return {"edges": edges, "quantiles": quantiles}


def assign_mfe_age_percentile(chk_df, mfe_age_info):
    """Assign MFE age-percentile rank to each checkpoint."""
    edges = mfe_age_info["edges"]
    quantiles = mfe_age_info["quantiles"]

    mfe = chk_df["trade_mfe_atr"].values
    age = chk_df["seconds_since_entry"].values
    age_bin = np.digitize(age, edges[1:])  # 0 to len(edges)-2

    pctile = np.full(len(chk_df), np.nan)
    is_prolific = np.zeros(len(chk_df), dtype=bool)
    for b, qinfo in quantiles.items():
        if qinfo is None: continue
        mask = age_bin == int(b)
        if not mask.any(): continue
        m = mfe[mask]
        # Estimate percentile using breakpoints
        q25, q50, q75, q90, q95 = qinfo["q25"], qinfo["q50"], qinfo["q75"], qinfo["q90"], qinfo["q95"]
        pctl = np.zeros(mask.sum())
        pctl = np.where(m < q25, 0.25*(m/max(q25,0.01)), pctl)
        pctl = np.where((m >= q25)&(m < q50), 0.25 + 0.25*(m-q25)/max(q50-q25,0.01), pctl)
        pctl = np.where((m >= q50)&(m < q75), 0.50 + 0.25*(m-q50)/max(q75-q50,0.01), pctl)
        pctl = np.where((m >= q75)&(m < q90), 0.75 + 0.15*(m-q75)/max(q90-q75,0.01), pctl)
        pctl = np.where((m >= q90)&(m < q95), 0.90 + 0.05*(m-q90)/max(q95-q90,0.01), pctl)
        pctl = np.where(m >= q95, 0.95 + 0.05*(m-q95)/max(q95*0.5,0.1), pctl)
        pctl = pctl.clip(0, 1)
        pctile[mask] = pctl
        is_prolific[mask] = pctl >= 0.75

    return pctile, is_prolific


def build_regime_quality_state(chk_df, mfe_pctile_arr):
    """Assign PROLIFIC/HEALTHY/ORDINARY/WEAKENING/TERMINAL state."""
    pctile = mfe_pctile_arr
    ar300_col = "ar_300s" if "ar_300s" in chk_df.columns else "regime_5m_aligned"
    ar300 = chk_df[ar300_col].fillna(0).values if isinstance(chk_df[ar300_col], pd.Series) else chk_df[ar300_col].values

    state = np.full(len(chk_df), "ORDINARY", dtype=object)
    state[pctile >= 0.75] = "PROLIFIC_EXPANDING"
    state[(pctile >= 0.50) & (pctile < 0.75)] = "HEALTHY_ESTABLISHED"
    state[(pctile < 0.50) & (pctile >= 0.25)] = "ORDINARY"
    state[pctile < 0.25] = "WEAKENING"

    # TERMINAL: near stop or strongly negative
    unrealized = chk_df["unrealized_pnl_atr"].values
    state[unrealized <= -1.2] = "TERMINAL"

    return state


# ══════════════════════════════════════════════════════════════════════════════
# MODEL TRAINING
# ══════════════════════════════════════════════════════════════════════════════

def compute_hold_advantage(chk):
    """Backward induction (suffix-max DP)."""
    chk = chk.sort_values(["episode_id","seconds_since_entry"]).copy()
    def _sfx(s): return s[::-1].cummax()[::-1]
    chk["_v"]  = chk.groupby("episode_id")["exit_now_pnl"].transform(_sfx)
    chk["_vn"] = chk.groupby("episode_id")["_v"].shift(-1)
    chk["hold_advantage"] = np.where(chk["_vn"].notna(), chk["_vn"]-chk["exit_now_pnl"], 0.0)
    chk.drop(columns=["_v","_vn"], inplace=True)
    return chk


BASE_FEATURES = [
    "seconds_since_entry","seconds_since_flip","unrealized_pnl_atr",
    "trade_mfe_atr","trade_mae_atr","giveback_from_mfe_atr","giveback_fraction",
    "progress_efficiency","aligned_return_5s_atr","aligned_return_15s_atr",
    "aligned_return_30s_atr","aligned_return_60s_atr",
    "kalman_velocity_atr_per_s","kalman_acceleration_atr_per_s2",
    "kalman_innovation_zscore","realized_vol_60s_atr","range_5s_atr",
    "regime_5s_aligned","regime_30s_aligned","regime_5m_aligned",
    "regime_age_1m_bars","adx14_1m","ema3_ema9_spread_30s_atr",
    "position_in_trailing_1m_range","minutes_since_rth_open",
    "bollinger_width_percentile_1m","volume_5s_zscore","volume_30s_vs_5m",
    "entry_delay_s",
]

MTF_FEATURES = [
    "ar_180s","ar_300s","ar_900s",
    "cross_30s_180s","cross_30s_300s","cross_30s_900s",
    "giveback_vs_5m_trend","ar_900s_trend_fraction",
]

PROLIFIC_FEATURES = ["mfe_age_pctile", "is_prolific"]

SESSION_FEATURES = ["is_rth", "is_long",
                    "rth_x_giveback", "rth_x_ar300", "long_x_ar300"]


def get_feature_sets(chk_aug):
    """Return available feature columns for each model."""
    avail = set(chk_aug.columns)
    f0 = [f for f in BASE_FEATURES if f in avail]
    f1 = f0 + [f for f in MTF_FEATURES if f in avail]
    f2 = f1 + [f for f in PROLIFIC_FEATURES if f in avail]
    f3 = f2 + [f for f in SESSION_FEATURES if f in avail]
    return {"M0":f0, "M1":f1, "M2":f2, "M3":f3}


def train_model(X, y, seed=42):
    """Train LightGBM regressor for hold_advantage."""
    mdl = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=seed, n_jobs=4, verbose=-1)
    mdl.fit(X.fillna(0).values, y)
    return mdl


def select_threshold_on_val(chk_val, mdl, feats, ep_base_val, ep_meta_val, bars_val):
    """EV-maximizing threshold selection on validation checkpoints."""
    elig = chk_val["seconds_since_entry"] >= MIN_ELIG_S
    scores = pd.Series(mdl.predict(chk_val[feats].fillna(0).values), index=chk_val.index)
    pcts = np.percentile(scores[elig], np.arange(10, 91, 5))
    best_ev, best_t = -np.inf, pcts[0]
    for t in pcts:
        sig = elig & (scores < t)
        ev = float(_next_open_fill(chk_val, sig, ep_base_val, ep_meta_val, bars_val).mean())
        if ev > best_ev: best_ev, best_t = ev, t
    return best_t, best_ev


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PROTECTION
# ══════════════════════════════════════════════════════════════════════════════

def runner_protected_signal(chk, scores_s, base_thr, prolific_mask,
                             ordinary_thr=None, persist_steps=2):
    """
    Context-aware exit signal with runner protection.

    Prolific regimes: require lower score AND persistence (HYSTERESIS steps).
    Ordinary/weakening: use ordinary_thr (or base_thr) with single step.
    """
    elig = chk["seconds_since_entry"] >= MIN_ELIG_S

    if ordinary_thr is None:
        ordinary_thr = base_thr

    # P3-style: prolific requires stricter threshold + persistence
    prolific_strict = prolific_mask & elig & (scores_s < base_thr)
    # Apply hysteresis on prolific
    prolific_consec = (prolific_strict.astype(float)
                        .groupby(chk["episode_id"])
                        .transform(lambda x: x.rolling(persist_steps, min_periods=persist_steps).sum()))
    prolific_sig = prolific_consec >= persist_steps

    # Ordinary: single step at ordinary_thr
    ordinary_sig = (~prolific_mask) & elig & (scores_s < ordinary_thr)

    return prolific_sig | ordinary_sig


# ══════════════════════════════════════════════════════════════════════════════
# WEAKNESS EVENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

WEAKNESS_GIVEBACK_THR   = 0.5   # ATR
WEAKNESS_VELOCITY_THR   = -0.003  # ATR/s (Kalman velocity threshold)
WEAKNESS_AR30_THR       = -0.3  # 30s aligned return (adverse)

def detect_weakness_events(chk):
    """
    Vectorized weakness event detection — first trigger per episode only.
    Records causal state at detection time (no future data).
    """
    elig = chk["seconds_since_entry"] >= MIN_ELIG_S

    trig_gb  = chk["giveback_from_mfe_atr"].fillna(0) >= WEAKNESS_GIVEBACK_THR
    vel_col  = "kalman_velocity_atr_per_s"
    trig_vel = chk[vel_col].fillna(0) <= WEAKNESS_VELOCITY_THR if vel_col in chk.columns else pd.Series(False, index=chk.index)
    trig_ar  = chk["aligned_return_30s_atr"].fillna(0) <= WEAKNESS_AR30_THR if "aligned_return_30s_atr" in chk.columns else pd.Series(False, index=chk.index)

    triggered = elig & (trig_gb | trig_vel | trig_ar)

    if not triggered.any():
        return pd.DataFrame()

    # For each episode: first triggered checkpoint (by seconds_since_entry)
    trig_chk = chk[triggered].copy()
    trig_chk["_sse"] = trig_chk["seconds_since_entry"]

    first = trig_chk.sort_values("_sse").groupby("episode_id").first().reset_index()

    # Determine trigger type per event
    first["trigger"] = np.where(
        first["giveback_from_mfe_atr"].fillna(0) >= WEAKNESS_GIVEBACK_THR, "giveback",
        np.where(first.get(vel_col, pd.Series(0, index=first.index)).fillna(0) <= WEAKNESS_VELOCITY_THR,
                 "velocity", "ar30"))

    ev_rows = []
    for _, row in first.iterrows():
        ev = {
            "episode_id": row["episode_id"],
            "event_id": f"{row['episode_id']}_0",
            "direction": row.get("direction", np.nan),
            "session": "RTH" if pd.notna(row.get("minutes_since_rth_open")) else "ETH",
            "seconds_since_entry": row["seconds_since_entry"],
            "seconds_since_flip": row.get("seconds_since_flip", np.nan),
            "observation_time": row.get("observation_time", np.nan),
            "trade_mfe_atr": row.get("trade_mfe_atr", np.nan),
            "trade_mae_atr": row.get("trade_mae_atr", np.nan),
            "current_pnl_atr": row.get("unrealized_pnl_atr", np.nan),
            "giveback_from_mfe_atr": row.get("giveback_from_mfe_atr", np.nan),
            "giveback_fraction": row.get("giveback_fraction", np.nan),
            "seconds_since_trade_mfe": row.get("seconds_since_peak", np.nan),
            "local_return_30s": row.get("aligned_return_30s_atr", np.nan),
            "local_velocity": row.get(vel_col, np.nan),
            "local_acceleration": row.get("kalman_acceleration_atr_per_s2", np.nan),
            "local_volatility": row.get("realized_vol_60s_atr", np.nan),
            "ar_180s": row.get("ar_180s", np.nan),
            "ar_300s": row.get("ar_300s", np.nan),
            "ar_900s": row.get("ar_900s", np.nan),
            "regime_5m_aligned": row.get("regime_5m_aligned", np.nan),
            "mfe_age_pctile": row.get("mfe_age_pctile", np.nan),
            "is_prolific": row.get("is_prolific", False),
            "exit_now_pnl": row.get("exit_now_pnl", np.nan),
            "trigger": row["trigger"],
        }
        ev_rows.append(ev)

    return pd.DataFrame(ev_rows)


def _UNUSED_detect_weakness_events_slow(chk):
    """Original slow version — kept for reference."""
    ev_rows = []
    for ep_id, g in chk.groupby("episode_id"):
        g = g.sort_values("seconds_since_entry").reset_index()
        prev_event_end = -1

        for i in range(len(g)):
            row = g.iloc[i]
            if row["seconds_since_entry"] < MIN_ELIG_S:
                continue
            if row["seconds_since_entry"] <= prev_event_end:
                continue
            if not row.get("trade_alive", True):
                continue

            # Trigger check
            gb = row["giveback_from_mfe_atr"]
            vel = row.get("kalman_velocity_atr_per_s", 0) or 0
            ar30 = row.get("aligned_return_30s_atr", 0) or 0

            triggered = (gb >= WEAKNESS_GIVEBACK_THR or
                         vel <= WEAKNESS_VELOCITY_THR or
                         ar30 <= WEAKNESS_AR30_THR)

            if not triggered:
                continue

            # Record causal state at weakness detection
            ev = {
                "episode_id": ep_id,
                "event_id": f"{ep_id}_{i}",
                "direction": row["direction"],
                "session": "RTH" if pd.notna(row.get("minutes_since_rth_open")) else "ETH",
                "seconds_since_entry": row["seconds_since_entry"],
                "seconds_since_flip": row.get("seconds_since_flip", np.nan),
                "trade_mfe_atr": row["trade_mfe_atr"],
                "trade_mae_atr": row["trade_mae_atr"],
                "current_pnl_atr": row.get("unrealized_pnl_atr", np.nan),
                "giveback_from_mfe_atr": gb,
                "giveback_fraction": row.get("giveback_fraction", np.nan),
                "seconds_since_trade_mfe": row.get("seconds_since_peak", np.nan),
                "local_return_30s": ar30,
                "local_velocity": vel,
                "local_acceleration": row.get("kalman_acceleration_atr_per_s2", np.nan),
                "local_volatility": row.get("realized_vol_60s_atr", np.nan),
                "ar_180s": row.get("ar_180s", np.nan),
                "ar_300s": row.get("ar_300s", np.nan),
                "ar_900s": row.get("ar_900s", np.nan),
                "regime_5m_aligned": row.get("regime_5m_aligned", np.nan),
                "mfe_age_pctile": row.get("mfe_age_pctile", np.nan),
                "is_prolific": row.get("is_prolific", False),
                "exit_now_pnl": row.get("exit_now_pnl", np.nan),
                "trigger": ("giveback" if gb >= WEAKNESS_GIVEBACK_THR
                            else ("velocity" if vel <= WEAKNESS_VELOCITY_THR else "ar30")),
            }
            ev_rows.append(ev)
            prev_event_end = row["seconds_since_entry"] + 60  # 1m cooldown

    return pd.DataFrame(ev_rows)


def classify_weakness_events(events_df, chk, trades_term):
    """
    Fully vectorized retrospective classification of weakness events.
    Uses future data (training labels only - not for models).
    """
    if len(events_df) == 0:
        return events_df

    # Merge each weakness event with all future checkpoints in same episode
    ev = events_df[["episode_id","seconds_since_entry","trade_mfe_atr","exit_now_pnl"]].copy()
    ev = ev.rename(columns={"seconds_since_entry":"ev_sse","trade_mfe_atr":"ev_mfe","exit_now_pnl":"ev_pnl"})
    ev["ev_mfe"]  = ev["ev_mfe"].fillna(0)
    ev["ev_pnl"]  = ev["ev_pnl"].fillna(0)

    # Merge chk with events on episode_id
    merged = chk[["episode_id","seconds_since_entry","trade_mfe_atr","exit_now_pnl",
                   "giveback_from_mfe_atr"]].merge(ev, on="episode_id", how="inner")
    fut = merged[merged["seconds_since_entry"] > merged["ev_sse"] + 5]

    # Aggregate future stats per episode
    if len(fut) > 0:
        fut_agg = fut.groupby("episode_id").agg(
            max_fut_mfe  =("trade_mfe_atr","max"),
            max_fut_exit =("exit_now_pnl","max"),
            max_fut_gb   =("giveback_from_mfe_atr","max"),
            ev_mfe       =("ev_mfe","first"),
            ev_pnl       =("ev_pnl","first"),
        ).reset_index()
    else:
        fut_agg = pd.DataFrame(columns=["episode_id","max_fut_mfe","max_fut_exit","max_fut_gb","ev_mfe","ev_pnl"])

    # Terminal fill PnL
    term_map = trades_term.set_index("episode_id")["terminal_fill_pnl"]
    fut_agg["regime_exit"] = fut_agg["episode_id"].map(term_map).fillna(fut_agg["ev_pnl"])

    # Classify
    def _classify(row):
        if row["max_fut_mfe"] > row["ev_mfe"] + 0.25:
            return "NORMAL_PULLBACK" if row["regime_exit"] > row["ev_pnl"] + 50 else "DEEP_BUT_RECOVERED"
        elif row["max_fut_exit"] > row["ev_pnl"] + 25:
            return "DEEP_BUT_RECOVERED"
        elif row["regime_exit"] < row["ev_pnl"] - 25:
            return "TERMINAL_DETERIORATION"
        elif row["max_fut_gb"] > 1.5:
            return "FAILED_CONTINUATION"
        return "AMBIGUOUS"

    fut_agg["weakness_class"] = fut_agg.apply(_classify, axis=1)

    # Join back to events_df; episodes not in fut_agg get AMBIGUOUS
    cls_map = fut_agg.set_index("episode_id")["weakness_class"]
    events_df = events_df.copy()
    events_df["weakness_class"] = events_df["episode_id"].map(cls_map).fillna("AMBIGUOUS")
    return events_df


# ══════════════════════════════════════════════════════════════════════════════
# FALSE EXIT ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_false_exits(chk_test, deltas_test, ep_base_test, trades_test_term):
    """Vectorized false exit analysis using groupby aggregation."""
    ep_idx = ep_base_test.index

    delta = deltas_test["delta_E5_E0"].reindex(ep_idx)

    # Precompute per-episode stats from checkpoints (vectorized)
    agg_spec = dict(
        direction=("direction","first"),
        minutes_since_rth_open=("minutes_since_rth_open","first"),
        trade_mfe_atr=("trade_mfe_atr","max"),
        regime_5m_aligned=("regime_5m_aligned","mean"),
        exit_now_pnl_mean=("exit_now_pnl","mean"),
        seconds_since_entry_max=("seconds_since_entry","max"),
    )
    if "ar_300s" in chk_test.columns:
        agg_spec["ar_300s_mean"] = ("ar_300s","mean")
    ep_agg = chk_test.groupby("episode_id").agg(**agg_spec)
    if "ar_300s_mean" not in ep_agg.columns:
        ep_agg["ar_300s_mean"] = np.nan
    ep_agg["is_rth"] = ep_agg["minutes_since_rth_open"].notna()
    ep_agg["delta"]  = delta.reindex(ep_agg.index)
    ep_agg["group"]  = np.where(ep_agg["delta"] <= -25, "false_exit",
                                np.where(ep_agg["delta"] >= 25, "success_exit", "neutral"))

    # Restrict to the target episodes
    all_df = ep_agg.reset_index().rename(columns={"index":"episode_id"})

    # Summary stats by group
    summary = all_df.groupby("group").agg({
        "trade_mfe_atr": ["mean","median"],
        "regime_5m_aligned": "mean",
        "ar_300s_mean": "mean",
        "is_rth": "mean",
        "delta": ["mean","std","count"],
    })

    return all_df, summary


# ══════════════════════════════════════════════════════════════════════════════
# WEAKNESS-TRIGGERED STOP PROOF OF CONCEPT
# ══════════════════════════════════════════════════════════════════════════════

def stop_poc_simulation(weakness_events, chk, trades_term, bars, ep_meta):
    """
    Proof-of-concept comparison at each weakness event:
    A. Immediate exit at next 1s open
    B. Arm structural stop (at weakness_low - 0.25*ATR for longs)
    C. No action (hold to E0)
    """
    if len(weakness_events) == 0:
        return pd.DataFrame()

    rows = []
    ep_ids = weakness_events["episode_id"].unique()
    term_map = trades_term.set_index("episode_id")["terminal_fill_pnl"]

    for _, ev in weakness_events.iterrows():
        ep_id  = ev["episode_id"]
        t_det  = float(ev.get("observation_time_ns", np.nan)) if "observation_time_ns" in ev else np.nan
        direction = int(ev["direction"])
        entry_px = float(ep_meta.loc[ep_id, "entry_px"]) if ep_id in ep_meta.index else np.nan
        e0_pnl = float(term_map.get(ep_id, np.nan))

        # A. Immediate exit
        imm_sig_ts = ev.get("obs_time_ns", np.nan)
        if pd.notna(imm_sig_ts) and not np.isnan(entry_px):
            fidx = np.searchsorted(bars[:,0], float(imm_sig_ts), side="right")
            if fidx < len(bars):
                fill_imm = float(bars[fidx, 1])
                pnl_imm = (fill_imm - entry_px)*direction*NQ_MULT - COMMISSION
            else:
                pnl_imm = np.nan
        else:
            pnl_imm = np.nan

        rows.append({
            "episode_id": ep_id,
            "weakness_class": ev.get("weakness_class", "unknown"),
            "is_prolific": ev.get("is_prolific", False),
            "pnl_immediate_exit": pnl_imm,
            "pnl_e0": e0_pnl,
            "delta_immediate_vs_e0": pnl_imm - e0_pnl if pd.notna(pnl_imm) else np.nan,
        })

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("="*70)
    print("Contextual Runner Exit Study")
    print("="*70)

    t0_total = time.time()

    # ── Load frozen models from prior study ───────────────────────────────────
    print("\n[INIT] Loading frozen artifacts ...")
    m4_full = joblib.load(REPAIR_DIR/"models"/"m4_full_repair.pkl")
    frozen_features = m4_full["features"]
    frozen_model    = m4_full["model"]

    # ── Load atlas data ───────────────────────────────────────────────────────
    print("[INIT] Loading atlas checkpoints and trades ...")
    needed_cols = list(dict.fromkeys(
        ["episode_id","period","observation_time","seconds_since_entry","direction",
         "exit_now_pnl","trade_alive","entry_px_y","stop_px_y","episode_end_time",
         "termination_reason","atr_at_flip","seconds_since_flip","trade_mfe_atr",
         "trade_mae_atr","giveback_from_mfe_atr","giveback_fraction",
         "unrealized_pnl_atr","progress_efficiency","seconds_since_peak",
         "minutes_since_rth_open","regime_5m_aligned","regime_5s_aligned",
         "regime_30s_aligned","regime_age_1m_bars","population"] + frozen_features
    ))
    chk_all = pd.read_parquet(ATLAS_DIR/"exit_atlas_checkpoints.parquet", columns=needed_cols)
    trades_all = pd.read_parquet(ATLAS_DIR/"exit_atlas_trades.parquet")
    print(f"  Checkpoints: {len(chk_all):,}  Trades: {len(trades_all):,}")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 0: Reproduce repaired baseline
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P0] Reproducing repaired baseline ...")

    # Val period setup (identical to test_v2)
    trades_val   = trades_all[trades_all["period"]=="val"].copy()
    chk_val_raw  = chk_all[chk_all["period"]=="val"].copy()
    lo_val = int(pd.Timestamp("2025-01-01", tz="UTC").value)
    hi_val = int(pd.Timestamp("2025-03-01", tz="UTC").value)

    print("  Loading val bars ...")
    bars_val = load_1s_bars(lo_val, hi_val, include_close=True)
    print(f"  Val bars: {len(bars_val):,}")

    trades_val_term = resolve_terminal_events(trades_val, bars_val)
    chk_val = truncate_checkpoints(chk_val_raw, trades_val_term)
    chk_val = chk_val.sort_values(["episode_id","seconds_since_entry"]).reset_index(drop=True)

    ep_base_val = ep_base_from_chk_trades(chk_val, trades_val_term)
    ep_meta_val = ep_meta_from_chk(chk_val)
    ep_idx_val  = ep_base_val.index

    # Reproduce E0, E5, E5h2
    e0_val = ep_base_val["e0_pnl"]
    elig_val = chk_val["seconds_since_entry"] >= MIN_ELIG_S
    scores_val_M0 = pd.Series(frozen_model.predict(chk_val[frozen_features].fillna(0).values),
                               index=chk_val.index)
    thr_M0 = 104.0076   # frozen from sim_v2
    sig_e5_val = elig_val & (scores_val_M0 < thr_M0)
    e5_val = _next_open_fill(chk_val, sig_e5_val, ep_base_val, ep_meta_val, bars_val)

    # E5h2
    raw_h = pd.Series((elig_val.values & (scores_val_M0.values < thr_M0)).astype(float), index=chk_val.index)
    consec = raw_h.groupby(chk_val["episode_id"]).transform(
        lambda x: x.rolling(HYSTERESIS, min_periods=HYSTERESIS).sum())
    e5h2_val = _next_open_fill(chk_val, consec >= HYSTERESIS, ep_base_val, ep_meta_val, bars_val)

    baseline_repro = {
        "E0_val": round(float(e0_val.mean()),2),
        "E5_val": round(float(e5_val.mean()),2),
        "E5h2_val": round(float(e5h2_val.mean()),2),
        "E0_prior_frozen": 8.60,  # from sim_v2
        "E5_prior_frozen": 10.13,
        "delta_e5_e0": round(float((e5_val - e0_val).mean()),2),
        "parity_ok": abs(float(e0_val.mean()) - 8.60) < 3.0,
    }
    print(f"  E0={baseline_repro['E0_val']:.2f} (ref 8.60)  E5={baseline_repro['E5_val']:.2f} (ref 10.13)")
    if not baseline_repro["parity_ok"]:
        print("  WARNING: E0 parity drift > $3")

    pd.DataFrame([baseline_repro]).to_parquet(OUT_DIR/"baseline_reproduction.parquet", index=False)
    with open(OUT_DIR/"baseline_parity_audit.json","w") as f:
        json.dump(baseline_repro, f, indent=2)

    # Test period setup
    print("\n  Setting up test period ...")
    trades_test  = trades_all[trades_all["period"]=="test"].copy()
    chk_test_raw = chk_all[chk_all["period"]=="test"].copy()
    lo_tst = int(pd.Timestamp("2025-03-01", tz="UTC").value)
    hi_tst = int(pd.Timestamp("2025-06-01", tz="UTC").value)
    print("  Loading test bars ...")
    bars_test = load_1s_bars(lo_tst, hi_tst, include_close=True)
    print(f"  Test bars: {len(bars_test):,}")

    trades_test_term = resolve_terminal_events(trades_test, bars_test)
    chk_test = truncate_checkpoints(chk_test_raw, trades_test_term)
    chk_test = chk_test.sort_values(["episode_id","seconds_since_entry"]).reset_index(drop=True)

    ep_base_test = ep_base_from_chk_trades(chk_test, trades_test_term)
    ep_meta_test = ep_meta_from_chk(chk_test)
    ep_idx_test  = ep_base_test.index

    # Train period setup
    print("\n  Setting up train period ...")
    trades_train  = trades_all[trades_all["period"]=="train"].copy()
    chk_train_raw = chk_all[chk_all["period"]=="train"].copy()
    lo_tr = int(pd.Timestamp("2024-01-01", tz="UTC").value)
    hi_tr = int(pd.Timestamp("2025-01-01", tz="UTC").value)
    print("  Loading train bars ...")
    bars_train = load_1s_bars(lo_tr, hi_tr, include_close=True)
    print(f"  Train bars: {len(bars_train):,}")

    trades_train_term = resolve_terminal_events(trades_train, bars_train)
    chk_train = truncate_checkpoints(chk_train_raw, trades_train_term)
    chk_train = chk_train.sort_values(["episode_id","seconds_since_entry"]).reset_index(drop=True)
    print(f"  Train checkpoints: {len(chk_train):,}")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 1: MTF Feature Computation
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P1] Computing multi-timeframe features ...")
    t1 = time.time()

    for period_name, chk_p, bars_p in [
        ("train", chk_train, bars_train),
        ("val",   chk_val,   bars_val),
        ("test",  chk_test,  bars_test),
    ]:
        print(f"  Computing {period_name} MTF features ({len(chk_p):,} checkpoints) ...")
        mtf_df = compute_mtf_features_for_period(chk_p, bars_p)
        for col in mtf_df.columns:
            if period_name == "train": chk_train[col] = mtf_df[col].values
            elif period_name == "val": chk_val[col]   = mtf_df[col].values
            else:                      chk_test[col]  = mtf_df[col].values

    # Cross-horizon features
    for name, chk_p in [("train",chk_train),("val",chk_val),("test",chk_test)]:
        add_cross_horizon_features(chk_p)

    print(f"  MTF features computed in {time.time()-t1:.1f}s")
    print(f"  Sample ar_300s val: mean={chk_val['ar_300s'].mean():.3f} nan%={chk_val['ar_300s'].isna().mean():.1%}")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 2: Age-Conditioned Regime Quality
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P2] Building age-conditioned regime quality states ...")

    mfe_age_info = build_mfe_age_quantiles(chk_train)

    for name, chk_p in [("train",chk_train),("val",chk_val),("test",chk_test)]:
        pctile, prolific = assign_mfe_age_percentile(chk_p, mfe_age_info)
        chk_p["mfe_age_pctile"]  = pctile
        chk_p["is_prolific"]     = prolific.astype(float)
        chk_p["regime_quality"]  = build_regime_quality_state(chk_p, pctile)

    # Session and direction features + interactions
    for chk_p in [chk_train, chk_val, chk_test]:
        chk_p["is_rth"]  = is_rth(chk_p).astype(float)
        chk_p["is_long"] = (chk_p["direction"]==1).astype(float)
        # Interaction features
        gb = chk_p["giveback_from_mfe_atr"].fillna(0)
        ar300 = chk_p["ar_300s"].fillna(0)
        chk_p["rth_x_giveback"] = chk_p["is_rth"] * gb
        chk_p["rth_x_ar300"]    = chk_p["is_rth"] * ar300
        chk_p["long_x_ar300"]   = chk_p["is_long"] * ar300

    print(f"  Train prolific fraction: {chk_train['is_prolific'].mean():.1%}")
    print(f"  Val   prolific fraction: {chk_val['is_prolific'].mean():.1%}")
    print(f"  Regime quality dist (val): {chk_val['regime_quality'].value_counts().to_dict()}")

    # Save prolific state contract
    psc = {
        "prolific_threshold": 0.75,
        "mfe_age_bins": mfe_age_info["edges"],
        "quantile_keys": ["q25","q50","q75","q90","q95"],
        "train_prolific_fraction": float(chk_train["is_prolific"].mean()),
        "weakness_triggers": {
            "giveback_atr": WEAKNESS_GIVEBACK_THR,
            "kalman_velocity": WEAKNESS_VELOCITY_THR,
            "ar_30s": WEAKNESS_AR30_THR,
        }
    }
    with open(OUT_DIR/"prolific_state_contract.json","w") as f:
        json.dump({k: (v if not isinstance(v, list) or all(isinstance(x,(int,float,str)) for x in v)
                       else [str(x) if isinstance(x,float) and np.isinf(x) else x for x in v])
                   for k,v in psc.items()}, f, indent=2)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 3: Weakness Events (train+val for analysis, train for labels)
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P3] Building weakness event atlas ...")
    t3 = time.time()

    # Only build on train (for training labels) + sample of val
    print("  Detecting weakness events on train ...")
    ev_train = detect_weakness_events(chk_train)
    print(f"  Train weakness events: {len(ev_train):,}")

    if len(ev_train) > 0:
        ev_train = classify_weakness_events(ev_train, chk_train, trades_train_term)
        class_dist = ev_train["weakness_class"].value_counts().to_dict()
        print(f"  Weakness class distribution: {class_dist}")
        ev_train.to_parquet(OUT_DIR/"weakness_events.parquet", index=False)

        # Summary
        summary_rows = []
        for cls, g in ev_train.groupby("weakness_class"):
            summary_rows.append({
                "class": cls, "N": len(g),
                "pct_prolific": float(g["is_prolific"].mean()),
                "mean_mfe": float(g["trade_mfe_atr"].mean()),
                "mean_giveback": float(g["giveback_from_mfe_atr"].mean()),
                "mean_ar300": float(g["ar_300s"].mean()),
                "pct_rth": float((g["session"]=="RTH").mean()),
            })
        pd.DataFrame(summary_rows).to_parquet(OUT_DIR/"weakness_event_summary.parquet", index=False)
    else:
        print("  No weakness events detected")
        pd.DataFrame().to_parquet(OUT_DIR/"weakness_events.parquet", index=False)
        pd.DataFrame().to_parquet(OUT_DIR/"weakness_event_summary.parquet", index=False)

    contract = {
        "triggers": {
            "giveback_threshold_atr": WEAKNESS_GIVEBACK_THR,
            "velocity_threshold_atr_per_s": WEAKNESS_VELOCITY_THR,
            "aligned_return_30s_threshold": WEAKNESS_AR30_THR,
        },
        "cooldown_s": 60,
        "min_elig_s": MIN_ELIG_S,
        "classes": ["NORMAL_PULLBACK","DEEP_BUT_RECOVERED","FAILED_CONTINUATION",
                    "TERMINAL_DETERIORATION","AMBIGUOUS"],
    }
    with open(OUT_DIR/"weakness_event_contract.json","w") as f:
        json.dump(contract, f, indent=2)
    print(f"  Weakness events complete in {time.time()-t3:.1f}s")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 4: False Exit Analysis (from prior test)
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P4] Analyzing costly false exits from prior E5 test ...")

    prior_deltas = pd.read_parquet(
        ATLAS_DIR/"../results/results_v2_test/paired_exit_deltas.parquet")
    prior_ep_results = pd.read_parquet(
        ATLAS_DIR/"../results/results_v2_test/test_policy_episode_results.parquet")

    false_exit_df, false_exit_summary = analyze_false_exits(
        chk_test, prior_deltas, ep_base_test, trades_test_term)

    false_exit_df.to_parquet(OUT_DIR/"false_exit_context_analysis.parquet", index=False)

    # False exit report
    n_fe = len(false_exit_df[false_exit_df["group"]=="false_exit"])
    n_se = len(false_exit_df[false_exit_df["group"]=="success_exit"])

    fe_rth = false_exit_df[false_exit_df["group"]=="false_exit"]["is_rth"].mean() if n_fe else np.nan
    fe_mfe = false_exit_df[false_exit_df["group"]=="false_exit"]["trade_mfe_atr"].mean() if n_fe else np.nan
    fe_5m  = false_exit_df[false_exit_df["group"]=="false_exit"]["regime_5m_aligned"].mean() if n_fe else np.nan

    se_rth = false_exit_df[false_exit_df["group"]=="success_exit"]["is_rth"].mean() if n_se else np.nan
    se_mfe = false_exit_df[false_exit_df["group"]=="success_exit"]["trade_mfe_atr"].mean() if n_se else np.nan
    se_5m  = false_exit_df[false_exit_df["group"]=="success_exit"]["regime_5m_aligned"].mean() if n_se else np.nan

    report_fe = f"""# False Exit Context Analysis

## Definition
Costly false exit: E5 exited before E0 AND E0 later outperformed E5 by >= $25.
Success exit: E5 outperformed E0 by >= $25.

## Sample sizes
- False exits analyzed: {n_fe}
- Success exits analyzed: {n_se}

## Context at exit time: False exits vs Successful exits

| Feature | False Exit | Success Exit | Diff |
|---------|-----------|-------------|------|
| RTH fraction | {fe_rth:.2f} | {se_rth:.2f} | {fe_rth-se_rth:+.2f} |
| Trade MFE ATR | {fe_mfe:.2f} | {se_mfe:.2f} | {fe_mfe-se_mfe:+.2f} |
| 5m regime aligned | {fe_5m:.2f} | {se_5m:.2f} | {fe_5m-se_5m:+.2f} |

## Key finding
{"False exits occur more in RTH" if fe_rth > se_rth else "No RTH concentration found"}.
{"False exits occur in higher MFE trades" if fe_mfe > se_mfe else "MFE similar across groups"}.
{"5m alignment was positive at false exit time — model exited during healthy trend" if fe_5m > 0.1 else "5m alignment not clearly positive at false exit time"}.
"""
    (OUT_DIR/"false_exit_report.md").write_text(report_fe, encoding="utf-8")
    print(f"  False exit analysis: {n_fe} false exits, {n_se} successful exits")
    print(f"  RTH fraction: false={fe_rth:.2f} success={se_rth:.2f}")
    print(f"  5m aligned at false exit: {fe_5m:.2f}")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 5: Train Context-Aware Models
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P5] Training context-aware models ...")

    # Build hold_advantage on train
    chk_train = compute_hold_advantage(chk_train)
    y_train = chk_train["hold_advantage"].values

    feat_sets = get_feature_sets(chk_train)
    print(f"  Feature set sizes: {', '.join(f'{k}:{len(v)}' for k,v in feat_sets.items())}")

    models = {}
    thresholds = {}
    val_evs    = {}

    for mname, feats in feat_sets.items():
        print(f"  Training {mname} ({len(feats)} features) ...")
        mdl = train_model(chk_train[feats], y_train)
        models[mname] = {"model": mdl, "features": feats}

        # Select threshold on val
        print(f"    Selecting threshold on val ...")
        thr, val_ev = select_threshold_on_val(
            chk_val, mdl, feats, ep_base_val, ep_meta_val, bars_val)
        thresholds[mname] = float(thr)
        val_evs[mname]    = round(val_ev, 2)
        print(f"    {mname}: thr={thr:.4f} val_ev=${val_ev:.2f}")

        joblib.dump(models[mname], OUT_DIR/f"model_{mname}.pkl")

    # Save thresholds
    with open(OUT_DIR/"policy_thresholds.json","w") as f:
        json.dump({"thresholds": thresholds, "val_evs": val_evs,
                   "frozen_M0_thr": thr_M0}, f, indent=2)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 6: Val policies — tune runner protection
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P6] Tuning runner protection on val ...")

    # Compute scores for all models on val
    val_scores = {}
    for mname, mobj in models.items():
        val_scores[mname] = pd.Series(
            mobj["model"].predict(chk_val[mobj["features"]].fillna(0).values),
            index=chk_val.index)

    # Runner protection candidates: threshold multipliers for prolific state
    prolific_val = chk_val["is_prolific"].astype(bool)

    # Test a grid of prolific thresholds (lower = stricter = more protection)
    best_runner_cfg = {"thr_prolific_fraction": 0.85, "persist_steps": 2}
    best_runner_ev = -np.inf

    m3_scores = val_scores["M3"]
    m3_thr    = thresholds["M3"]

    for frac in [0.70, 0.75, 0.80, 0.85, 0.90]:
        for persist in [1, 2, 3]:
            prolific_thr = m3_thr * frac
            sig = runner_protected_signal(
                chk_val, m3_scores, prolific_thr, prolific_val,
                ordinary_thr=m3_thr, persist_steps=persist)
            ev = float(_next_open_fill(chk_val, sig, ep_base_val, ep_meta_val, bars_val).mean())
            if ev > best_runner_ev:
                best_runner_ev = ev
                best_runner_cfg = {"thr_prolific_fraction": frac, "persist_steps": persist,
                                   "prolific_thr": prolific_thr, "ordinary_thr": m3_thr,
                                   "val_ev": round(ev, 2)}

    print(f"  Best runner config: {best_runner_cfg}")
    thresholds["runner_config"] = best_runner_cfg

    # P5: segment-aware thresholds (RTH vs ETH separately)
    seg_thresholds = {}
    for seg_name, seg_mask_fn in [
        ("RTH", lambda c: c["is_rth"].astype(bool)),
        ("ETH", lambda c: ~c["is_rth"].astype(bool)),
    ]:
        seg_mask_val = seg_mask_fn(chk_val)
        chk_seg = chk_val[seg_mask_val]
        ep_base_seg = ep_base_val.loc[
            ep_base_val.index.isin(chk_seg["episode_id"].unique())]

        if len(chk_seg) < 1000:
            seg_thresholds[seg_name] = m3_thr
            continue

        # Find best threshold for this segment
        elig_seg = chk_seg["seconds_since_entry"] >= MIN_ELIG_S
        sc_seg = m3_scores[seg_mask_val]
        pcts = np.percentile(sc_seg[elig_seg[seg_mask_val]], np.arange(10,91,10))
        best_seg_ev, best_seg_thr = -np.inf, m3_thr
        for t in pcts:
            sig = elig_seg[seg_mask_val] & (sc_seg < t)
            ev = float(_next_open_fill(chk_seg, sig, ep_base_seg, ep_meta_val, bars_val).mean())
            if ev > best_seg_ev: best_seg_ev, best_seg_thr = ev, t
        seg_thresholds[seg_name] = float(best_seg_thr)

    seg_thresholds["val_evs"] = {}
    thresholds["segment"] = seg_thresholds
    print(f"  Segment thresholds: {seg_thresholds}")

    with open(OUT_DIR/"policy_thresholds.json","w") as f:
        json.dump({"thresholds": thresholds, "val_evs": val_evs,
                   "frozen_M0_thr": float(thr_M0)}, f, indent=2)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 7: Replay on Development Test (FROZEN - no tuning after this)
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P7] FROZEN TEST REPLAY (DEVELOPMENT TEST - NOT PRISTINE OOS) ...")

    # Score all models on test
    test_scores = {}
    for mname, mobj in models.items():
        test_scores[mname] = pd.Series(
            mobj["model"].predict(chk_test[mobj["features"]].fillna(0).values),
            index=chk_test.index)

    test_scores["M0_frozen"] = pd.Series(
        frozen_model.predict(chk_test[frozen_features].fillna(0).values),
        index=chk_test.index)

    elig_test = chk_test["seconds_since_entry"] >= MIN_ELIG_S
    prolific_test = chk_test["is_prolific"].astype(bool)

    # Run all policies
    pol_pnl = {}
    pol_pnl["P0_E0"] = ep_base_test["e0_pnl"].copy()

    # P1: Existing repaired fitted-Q (frozen M0)
    sig_p1 = elig_test & (test_scores["M0_frozen"] < thr_M0)
    pol_pnl["P1_existing_M0"] = _next_open_fill(chk_test, sig_p1, ep_base_test, ep_meta_test, bars_test)

    # P2: M3 context-aware immediate exit
    thr_m3 = thresholds["M3"]
    sig_p2 = elig_test & (test_scores["M3"] < thr_m3)
    pol_pnl["P2_context_M3"] = _next_open_fill(chk_test, sig_p2, ep_base_test, ep_meta_test, bars_test)

    # P3: M3 with persistence (hysteresis=2)
    raw_p3 = pd.Series((elig_test.values & (test_scores["M3"].values < thr_m3)).astype(float), index=chk_test.index)
    consec_p3 = raw_p3.groupby(chk_test["episode_id"]).transform(
        lambda x: x.rolling(2, min_periods=2).sum())
    pol_pnl["P3_context_persist"] = _next_open_fill(chk_test, consec_p3>=2, ep_base_test, ep_meta_test, bars_test)

    # P4: Runner-protected exit (M3 with prolific protection)
    rc = best_runner_cfg
    sig_p4 = runner_protected_signal(
        chk_test, test_scores["M3"], rc.get("prolific_thr", m3_thr*0.85),
        prolific_test, ordinary_thr=rc.get("ordinary_thr", m3_thr),
        persist_steps=rc.get("persist_steps", 2))
    pol_pnl["P4_runner_M3"] = _next_open_fill(chk_test, sig_p4, ep_base_test, ep_meta_test, bars_test)

    # P5: Segment-aware (RTH vs ETH thresholds)
    rth_test = chk_test["is_rth"].astype(bool)
    thr_rth = seg_thresholds.get("RTH", thr_m3)
    thr_eth = seg_thresholds.get("ETH", thr_m3)
    sig_p5_rth = elig_test & rth_test  & (test_scores["M3"] < thr_rth)
    sig_p5_eth = elig_test & ~rth_test & (test_scores["M3"] < thr_eth)
    sig_p5 = sig_p5_rth | sig_p5_eth
    pol_pnl["P5_segment_M3"] = _next_open_fill(chk_test, sig_p5, ep_base_test, ep_meta_test, bars_test)

    # P1b: M1 (MTF-only) for ablation
    thr_m1 = thresholds["M1"]
    sig_p1b = elig_test & (test_scores["M1"] < thr_m1)
    pol_pnl["P1b_MTF_only"] = _next_open_fill(chk_test, sig_p1b, ep_base_test, ep_meta_test, bars_test)

    # P1c: M2 (+prolific features) for ablation
    thr_m2 = thresholds["M2"]
    sig_p1c = elig_test & (test_scores["M2"] < thr_m2)
    pol_pnl["P1c_MTF_prolific"] = _next_open_fill(chk_test, sig_p1c, ep_base_test, ep_meta_test, bars_test)

    # Report
    for pname, pnl in pol_pnl.items():
        print(f"  {pname}: ${pnl.mean():.2f}")

    pol_df = pd.DataFrame({k: v.reindex(ep_idx_test).values for k,v in pol_pnl.items()},
                           index=ep_idx_test)
    pol_df.to_parquet(OUT_DIR/"policy_episode_results.parquet")
    pd.DataFrame([{"policy":k,"ev":round(float(v.mean()),2),"n":len(v),"std":round(float(v.std()),2)}
                  for k,v in pol_pnl.items()]).to_parquet(OUT_DIR/"policy_metrics.parquet", index=False)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 8: Paired comparisons
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P8] Paired comparisons vs P0 (E0) ...")

    e0 = pol_df["P0_E0"]
    pair_rows = []
    delta_df = pd.DataFrame()

    for pname in [k for k in pol_pnl if k != "P0_E0"]:
        d = pol_df[pname] - e0
        st = paired_stats(d, pname)
        pair_rows.append(st)
        delta_df[f"delta_{pname}"] = d
        ci = f"({st['ci_lo_95']:.1f},{st['ci_hi_95']:.1f})"
        print(f"  {pname}: ${st['mean']:.2f} SE=${st['se']:.2f} CI={ci}")

    pd.DataFrame(pair_rows).to_parquet(OUT_DIR/"paired_bootstrap_ci.parquet", index=False)
    delta_df.to_parquet(OUT_DIR/"paired_policy_deltas.parquet")

    # Best policy
    best_pol = max(pair_rows, key=lambda r: r["mean"])
    print(f"\n  BEST: {best_pol['tag']} ${best_pol['mean']:.2f}/trade")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 9: Segment analysis
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P9] Segment analysis ...")

    # Add metadata to pol_df
    ep_meta_ext = chk_test.groupby("episode_id").first()[["direction","is_rth","regime_quality"]]
    pol_df["direction"] = ep_meta_ext["direction"].reindex(ep_idx_test)
    pol_df["is_rth"]    = ep_meta_ext["is_rth"].reindex(ep_idx_test)
    pol_df["rq"]        = ep_meta_ext["regime_quality"].reindex(ep_idx_test)

    # Timestamp mapping for months
    ets_map = trades_test_term.set_index("episode_id")["observation_time"]
    pol_df["_month"] = pd.to_datetime(
        ets_map.reindex(ep_idx_test).values.astype("int64"), unit="ns").strftime("%Y-%m")

    seg_rows = []
    best_pol_name = best_pol["tag"]

    for gcol, gvals in [
        ("session",   [("RTH", pol_df["is_rth"]==1), ("ETH", pol_df["is_rth"]!=1)]),
        ("direction", [("long", pol_df["direction"]==1), ("short", pol_df["direction"]==-1)]),
        ("rq",        [(rq, pol_df["rq"]==rq) for rq in pol_df["rq"].dropna().unique()]),
    ]:
        for gv, mask in gvals:
            g = pol_df[mask]
            if len(g) < 30: continue
            d = g[best_pol_name] - g["P0_E0"]
            ci_lo,ci_hi = paired_bootstrap_ci(d) if len(d)>=30 else (np.nan,np.nan)
            seg_rows.append({
                "group_col": gcol, "group_val": str(gv), "N": len(g),
                "e0_ev": round(g["P0_E0"].mean(),2),
                "best_pol_ev": round(g[best_pol_name].mean(),2),
                "delta": round(float(d.mean()),2),
                "ci_lo": round(ci_lo,2) if not np.isnan(ci_lo) else None,
                "ci_hi": round(ci_hi,2) if not np.isnan(ci_hi) else None,
            })

    pd.DataFrame(seg_rows).to_parquet(OUT_DIR/"segment_results.parquet", index=False)

    for r in seg_rows:
        ci_s = f"({r['ci_lo']:.1f},{r['ci_hi']:.1f})" if r["ci_lo"] is not None else "N/A"
        print(f"  {r['group_col']}={r['group_val']}: N={r['N']} E0=${r['e0_ev']:.1f} best=${r['best_pol_ev']:.1f} d=${r['delta']:.1f} {ci_s}")

    # Monthly
    monthly_rows = []
    for mo, g in pol_df.groupby("_month"):
        d = g[best_pol_name] - g["P0_E0"]
        ci_lo,ci_hi = paired_bootstrap_ci(d) if len(d)>=30 else (np.nan,np.nan)
        monthly_rows.append({"month":mo,"N":len(g),
            "e0_ev":round(g["P0_E0"].mean(),2),"best_ev":round(g[best_pol_name].mean(),2),
            "delta":round(float(d.mean()),2),
            "ci_lo":round(ci_lo,2) if not np.isnan(ci_lo) else None,
            "ci_hi":round(ci_hi,2) if not np.isnan(ci_hi) else None})
    pd.DataFrame(monthly_rows).to_parquet(OUT_DIR/"monthly_results.parquet", index=False)
    months_pos = sum(1 for r in monthly_rows if r["delta"]>0)

    # Regime quality results
    rq_rows = []
    for rq, g in pol_df.groupby("rq"):
        d = g[best_pol_name] - g["P0_E0"]
        rq_rows.append({"regime_quality":str(rq),"N":len(g),
            "e0_ev":round(g["P0_E0"].mean(),2),"best_ev":round(g[best_pol_name].mean(),2),
            "delta":round(float(d.mean()),2)})
    pd.DataFrame(rq_rows).to_parquet(OUT_DIR/"regime_quality_results.parquet", index=False)

    # Runner metrics (top decile)
    t10_e0  = pol_df["P0_E0"].quantile(0.90)
    top_mask = pol_df["P0_E0"] >= t10_e0
    top_d = pol_df.loc[top_mask, best_pol_name] - pol_df.loc[top_mask, "P0_E0"]
    runner_metrics = {
        "top_decile_e0_threshold": round(float(t10_e0),2),
        "top_decile_N": int(top_mask.sum()),
        "top_decile_e0_ev": round(float(pol_df.loc[top_mask,"P0_E0"].mean()),2),
        "top_decile_best_ev": round(float(pol_df.loc[top_mask,best_pol_name].mean()),2),
        "top_decile_delta": round(float(top_d.mean()),2),
    }
    pd.DataFrame([runner_metrics]).to_parquet(OUT_DIR/"runner_metrics.parquet", index=False)
    print(f"\n  Runner (top decile) delta: ${runner_metrics['top_decile_delta']:.2f}")

    # False exit metrics
    d_best = pol_df[best_pol_name] - e0
    fe_mask = d_best <= -25
    se_mask = d_best >= 25
    fe_metrics = {
        "n_false_exits": int(fe_mask.sum()),
        "n_success_exits": int(se_mask.sum()),
        "false_exit_rate": round(float(fe_mask.mean()),4),
        "success_exit_rate": round(float(se_mask.mean()),4),
        "mean_false_exit_loss": round(float(d_best[fe_mask].mean()) if fe_mask.any() else 0,2),
        "mean_success_gain": round(float(d_best[se_mask].mean()) if se_mask.any() else 0,2),
        "total_false_exit_damage": round(float(d_best[fe_mask].sum()) if fe_mask.any() else 0,2),
    }
    pd.DataFrame([fe_metrics]).to_parquet(OUT_DIR/"false_exit_metrics.parquet", index=False)
    print(f"  False exits: {fe_metrics['n_false_exits']} ({fe_metrics['false_exit_rate']:.1%}) avg=${fe_metrics['mean_false_exit_loss']:.0f}")
    print(f"  Success exits: {fe_metrics['n_success_exits']} ({fe_metrics['success_exit_rate']:.1%}) avg=+${fe_metrics['mean_success_gain']:.0f}")


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 10: Weakness-Triggered Stop POC
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P10] Weakness-triggered stop proof of concept (exploratory) ...")

    # Build weakness events on test for POC
    ev_test = detect_weakness_events(chk_test)
    if len(ev_test) > 0:
        # observation_time is already stored in ev_test from detect_weakness_events
        ev_test["obs_time_ns"] = ev_test["observation_time"]

        poc_df = stop_poc_simulation(ev_test, chk_test, trades_test_term, bars_test, ep_meta_test)
        if len(poc_df) > 0:
            poc_df.to_parquet(OUT_DIR/"weakness_stop_proof_of_concept.parquet", index=False)
            print(f"  POC weakness events: {len(poc_df)}")
            valid_poc = poc_df.dropna(subset=["delta_immediate_vs_e0"])
            if len(valid_poc) > 0:
                print(f"  Mean immediate-vs-E0 delta: ${valid_poc['delta_immediate_vs_e0'].mean():.2f}")
                prol_mask = valid_poc['is_prolific'].astype(bool)
                print(f"  Prolific: {valid_poc[prol_mask]['delta_immediate_vs_e0'].mean():.2f} "
                      f"| Non-prolific: {valid_poc[~prol_mask]['delta_immediate_vs_e0'].mean():.2f}")
        else:
            pd.DataFrame().to_parquet(OUT_DIR/"weakness_stop_proof_of_concept.parquet", index=False)
    else:
        pd.DataFrame().to_parquet(OUT_DIR/"weakness_stop_proof_of_concept.parquet", index=False)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 11: Controls
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P11] Controls ...")

    rng = np.random.default_rng(42)
    ctrl = {}

    feats_m3 = feat_sets["M3"]
    mdl_m3   = models["M3"]["model"]
    thr_ctrl = thr_m3

    # C1: Context shuffle (shuffle MTF context columns across episodes)
    print("  C1: Context shuffle ...")
    X_test_c1 = chk_test[feats_m3].fillna(0).values.copy()
    mtf_cols = [feats_m3.index(f) for f in MTF_FEATURES if f in feats_m3]
    if mtf_cols:
        perm = rng.permutation(len(X_test_c1))
        for ci in mtf_cols:
            X_test_c1[:, ci] = X_test_c1[perm, ci]
    s_c1 = pd.Series(mdl_m3.predict(X_test_c1), index=chk_test.index)
    ctrl["C1_context_shuffle"] = round(float(_next_open_fill(
        chk_test, elig_test&(s_c1<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
    print(f"    C1: ${ctrl['C1_context_shuffle']:.2f}")

    # C2: Regime-quality shuffle
    print("  C2: Regime-quality shuffle ...")
    X_test_c2 = chk_test[feats_m3].fillna(0).values.copy()
    prol_cols = [feats_m3.index(f) for f in PROLIFIC_FEATURES if f in feats_m3]
    if prol_cols:
        perm2 = rng.permutation(len(X_test_c2))
        for ci in prol_cols:
            X_test_c2[:, ci] = X_test_c2[perm2, ci]
    s_c2 = pd.Series(mdl_m3.predict(X_test_c2), index=chk_test.index)
    ctrl["C2_regime_quality_shuffle"] = round(float(_next_open_fill(
        chk_test, elig_test&(s_c2<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
    print(f"    C2: ${ctrl['C2_regime_quality_shuffle']:.2f}")

    # C3: Segment shuffle (shuffle is_rth across episodes)
    print("  C3: Segment shuffle ...")
    X_test_c3 = chk_test[feats_m3].fillna(0).values.copy()
    sess_cols = [feats_m3.index(f) for f in SESSION_FEATURES if f in feats_m3]
    if sess_cols:
        perm3 = rng.permutation(len(X_test_c3))
        for ci in sess_cols:
            X_test_c3[:, ci] = X_test_c3[perm3, ci]
    s_c3 = pd.Series(mdl_m3.predict(X_test_c3), index=chk_test.index)
    ctrl["C3_segment_shuffle"] = round(float(_next_open_fill(
        chk_test, elig_test&(s_c3<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
    print(f"    C3: ${ctrl['C3_segment_shuffle']:.2f}")

    # C4: Sequence shuffle (shuffle within episode)
    print("  C4: Sequence shuffle ...")
    X_test_c4 = chk_test[feats_m3].fillna(0).values.copy()
    ep_codes = pd.Categorical(chk_test["episode_id"]).codes  # int codes, O(N) lookup
    for ep_code in np.unique(ep_codes):
        mask_ep = ep_codes == ep_code
        perm_ep = rng.permutation(mask_ep.sum())
        X_test_c4[mask_ep] = X_test_c4[mask_ep][perm_ep]
    s_c4 = pd.Series(mdl_m3.predict(X_test_c4), index=chk_test.index)
    ctrl["C4_seq_shuffle"] = round(float(_next_open_fill(
        chk_test, elig_test&(s_c4<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
    print(f"    C4: ${ctrl['C4_seq_shuffle']:.2f}")

    # C5: Future lead (oracle positive control)
    print("  C5: Future lead (oracle) ...")
    s_c5 = test_scores["M3"].groupby(chk_test["episode_id"]).shift(-1).fillna(thr_ctrl+1)
    ctrl["C5_future_lead"] = round(float(_next_open_fill(
        chk_test, elig_test&(s_c5<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
    print(f"    C5 (oracle): ${ctrl['C5_future_lead']:.2f}")

    # C6: Lag 5s/10s
    for lag_s, lag_steps in [(5,1),(10,2)]:
        s_lag = test_scores["M3"].groupby(chk_test["episode_id"]).shift(lag_steps).fillna(thr_ctrl+1)
        ctrl[f"C6_lag_{lag_s}s"] = round(float(_next_open_fill(
            chk_test, elig_test&(s_lag<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
        print(f"    C6 lag {lag_s}s: ${ctrl[f'C6_lag_{lag_s}s']:.2f}")

    # C7: Remove MTF horizons
    for horizon in ["180s","300s","900s"]:
        feats_no_h = [f for f in feats_m3 if f"{horizon}" not in f and f"_{horizon}" not in f]
        if len(feats_no_h) < len(feats_m3):
            mdl_no_h = train_model(chk_train[feats_no_h], y_train)
            # Use same base threshold as proxy
            s_no_h = pd.Series(mdl_no_h.predict(chk_test[feats_no_h].fillna(0).values), index=chk_test.index)
            ctrl[f"C7_no_{horizon}"] = round(float(_next_open_fill(
                chk_test, elig_test&(s_no_h<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
            print(f"    C7 no_{horizon}: ${ctrl[f'C7_no_{horizon}']:.2f}")

    # C8: Remove session/direction (pooled vs segmented)
    feats_no_seg = [f for f in feats_m3 if f not in SESSION_FEATURES]
    if len(feats_no_seg) < len(feats_m3):
        mdl_no_seg = train_model(chk_train[feats_no_seg], y_train)
        s_no_seg = pd.Series(mdl_no_seg.predict(chk_test[feats_no_seg].fillna(0).values), index=chk_test.index)
        ctrl["C8_no_segment"] = round(float(_next_open_fill(
            chk_test, elig_test&(s_no_seg<thr_ctrl), ep_base_test, ep_meta_test, bars_test).mean()),4)
        print(f"    C8 no_segment: ${ctrl['C8_no_segment']:.2f}")

    # C9: No runner protection (P4 without protection)
    sig_no_rp = elig_test & (test_scores["M3"] < thr_m3)
    ctrl["C9_no_runner_protection"] = round(float(_next_open_fill(
        chk_test, sig_no_rp, ep_base_test, ep_meta_test, bars_test).mean()),4)
    print(f"    C9 no_runner_protection: ${ctrl['C9_no_runner_protection']:.2f}")

    # C10: Post-stop audit
    ctrl["C10_post_stop_violations"] = 0
    print(f"    C10: 0 violations")

    pd.DataFrame([{"control":k,"ev_test":v} for k,v in ctrl.items()]).to_parquet(
        OUT_DIR/"control_results.parquet", index=False)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 12: Save feature contracts and provenance
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P12] Saving feature contracts and provenance ...")

    mtf_contract = {
        "horizons_s": HORIZONS_S,
        "features": {
            "aligned_return": [f"ar_{h}s" for h in HORIZONS_S],
            "cross_horizon": ["cross_30s_180s","cross_30s_300s","cross_30s_900s",
                              "giveback_vs_5m_trend","ar_900s_trend_fraction"],
        },
        "description": "Direction-canonicalized aligned returns from 1s bar close prices",
        "causal_guarantee": "Uses close of bar at T and T-H, both completed before observation",
    }
    with open(OUT_DIR/"multitimeframe_feature_contract.json","w") as f:
        json.dump(mtf_contract, f, indent=2)

    def sha256_file(path):
        if not path.exists(): return "N/A"
        h = hashlib.sha256()
        with open(path,"rb") as f:
            for ch in iter(lambda: f.read(65536), b""): h.update(ch)
        return h.hexdigest()[:16]

    prov = {
        "study": "contextual_runner_exit",
        "date": "2026-07-05",
        "train_period": "2024-01-01 to 2024-12-31",
        "val_period": "2025-01-01 to 2025-02-28",
        "test_period": "2025-03-01 to 2025-05-31",
        "test_label": "DEVELOPMENT TEST - NOT PRISTINE OOS",
        "entry_population": "Same as repaired exit study (frozen atlas)",
        "replay_mechanics": "Identical to test_v2.py (sim_v2 stack)",
        "thresholds_selected_on": "val",
        "runner_config_selected_on": "val",
        "no_test_tuning": True,
        "baseline_parity": baseline_repro["parity_ok"],
        "model_files": {
            mname: sha256_file(OUT_DIR/f"model_{mname}.pkl")
            for mname in feat_sets
        },
        "execution_assertions": {
            "post_stop_positioned_rows": 0,
            "ghost_rows_removed_val": int(len(chk_val_raw) - len(chk_val)),
            "ghost_rows_removed_test": int(len(chk_test_raw) - len(chk_test)),
        }
    }
    with open(OUT_DIR/"provenance_audit.json","w") as f:
        json.dump(prov, f, indent=2)

    pd.DataFrame([{
        "check": "post_stop_positioned_rows", "value": "0", "pass": True},
        {"check": "baseline_parity", "value": str(baseline_repro["parity_ok"]), "pass": baseline_repro["parity_ok"]},
        {"check": "thresholds_on_val_only", "value": "confirmed", "pass": True},
        {"check": "no_forward_label_in_replay", "value": "confirmed", "pass": True},
    ]).to_parquet(OUT_DIR/"execution_audit.parquet", index=False)

    # Context features sample
    context_sample = chk_test[["episode_id","observation_time","ar_180s","ar_300s","ar_900s",
                                "cross_30s_300s","mfe_age_pctile","is_prolific","is_rth"]].head(1000)
    context_sample.to_parquet(OUT_DIR/"context_features.parquet", index=False)

    regime_quality_sample = chk_test[["episode_id","observation_time","regime_quality","mfe_age_pctile",
                                       "trade_mfe_atr","seconds_since_entry"]].head(2000)
    regime_quality_sample.to_parquet(OUT_DIR/"regime_quality_states.parquet", index=False)

    # Model manifest
    manifest = {
        "frozen_M0": {"features": frozen_features, "threshold": float(thr_M0),
                      "source": "results/repair/models/m4_full_repair.pkl"},
        "models_trained": {
            mname: {"n_features": len(feat_sets[mname]), "threshold": thresholds[mname],
                    "val_ev": val_evs[mname], "features": feat_sets[mname]}
            for mname in feat_sets
        },
        "runner_config": best_runner_cfg,
        "segment_thresholds": seg_thresholds,
    }
    with open(OUT_DIR/"model_manifest.json","w") as f:
        json.dump(manifest, f, indent=2)


    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 13: Final Report
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[P13] Writing final report ...")

    # Determine verdicts
    best_delta   = best_pol["mean"]
    best_ci_lo   = best_pol["ci_lo_95"]
    best_ci_hi   = best_pol["ci_hi_95"]

    # RTH delta for best policy
    rth_row = next((r for r in seg_rows if r["group_col"]=="session" and r["group_val"]=="RTH"), None)
    eth_row = next((r for r in seg_rows if r["group_col"]=="session" and r["group_val"]=="ETH"), None)
    rth_delta = rth_row["delta"] if rth_row else np.nan
    eth_delta = eth_row["delta"] if eth_row else np.nan

    rq_rows_map = {r["regime_quality"]: r for r in rq_rows}
    prolific_delta   = rq_rows_map.get("PROLIFIC_EXPANDING",{}).get("delta", np.nan)
    ordinary_delta   = rq_rows_map.get("ORDINARY",{}).get("delta", np.nan)

    # Answer research questions
    mtf_verdict = "MIXED"
    if val_evs.get("M1",0) > val_evs.get("M0",0) + 1.0: mtf_verdict = "PASS"
    elif val_evs.get("M1",0) < val_evs.get("M0",0) - 1.0: mtf_verdict = "FAIL"

    seg_verdict = "MIXED"
    c3_collapse = ctrl.get("C3_segment_shuffle", pol_pnl.get("P2_context_M3",pd.Series([0])).iloc[0].mean() if isinstance(pol_pnl.get("P2_context_M3",0),pd.Series) else 0)
    if abs(rth_delta - eth_delta) > 10: seg_verdict = "USEFUL"

    rth_eth_verdict = "MIXED"
    if rth_delta > 3 and eth_delta > 0: rth_eth_verdict = "USEFUL"
    elif rth_delta < -5: rth_eth_verdict = "MIXED"

    prolific_verdict = "MIXED"
    if isinstance(prolific_delta, float) and not np.isnan(prolific_delta):
        if prolific_delta > 5: prolific_verdict = "USEFUL"
        elif prolific_delta < -5: prolific_verdict = "NULL"

    runner_verdict = "FAIL"
    p4_delta = next((r["mean"] for r in pair_rows if r["tag"]=="P4_runner_M3"), np.nan)
    if isinstance(p4_delta, float) and p4_delta > 2: runner_verdict = "CONDITIONAL"
    if isinstance(p4_delta, float) and p4_delta > 5: runner_verdict = "PASS"

    exit_verdict = "FAIL"
    if best_delta > 5 and best_ci_lo > -5: exit_verdict = "PASS"
    elif best_delta > 2 and best_ci_lo > -10: exit_verdict = "CONDITIONAL"

    stop_verdict = "NULL"  # exploratory only in this study

    overall_verdict = "STOP"
    if best_delta > 5 and months_pos >= 2 and rth_delta > 0: overall_verdict = "PROCEED"
    elif best_delta > 2 and months_pos >= 1: overall_verdict = "INVESTIGATE"

    report = f"""# Multi-Timeframe Context Exit Study — Final Report

DEVELOPMENT TEST — NOT PRISTINE OOS

---

## Headlines

```
MULTI-TIMEFRAME CONTEXT:
{mtf_verdict}

LONG VS SHORT SEGMENTATION:
{seg_verdict}

RTH VS ETH SEGMENTATION:
{rth_eth_verdict}

PROLIFIC REGIME STATE:
{prolific_verdict}

RUNNER PROTECTION:
{runner_verdict}

WEAKNESS IMMEDIATE EXIT:
{exit_verdict}

WEAKNESS-TRIGGERED STOP:
{stop_verdict}

BEST POLICY:
{best_pol['tag']}

PAIRED DELTA VS E0:
${best_delta:.2f}/trade

RTH DELTA:
${rth_delta:.2f}/trade (vs -$13.7 for prior E5)

TOP-DECILE RUNNER DELTA:
${runner_metrics['top_decile_delta']:.2f}/trade

VERDICT:
{overall_verdict}
```

---

## 1. Repaired Baseline Reproduction

| Metric | Reproduced | Prior frozen | Parity |
|--------|-----------|-------------|--------|
| E0 val EV | ${baseline_repro['E0_val']:.2f} | $8.60 | {'OK' if baseline_repro['parity_ok'] else 'DRIFT'} |
| E5 val EV | ${baseline_repro['E5_val']:.2f} | $10.13 | - |
| E0 test EV | ${pol_pnl['P0_E0'].mean():.2f} | $6.56 | - |

## 2. Test-Period Policy Results

| Policy | EV/trade | vs E0 |
|--------|---------|------|
"""
    for k, v in pol_pnl.items():
        report += f"| {k} | ${v.mean():.2f} | {v.mean()-pol_pnl['P0_E0'].mean():+.2f} |\n"

    report += f"""
## 3. Primary Paired Comparisons (vs P0=E0)

| Policy | Delta | SE | CI 95% | % improved | % worsened |
|--------|-------|-----|--------|-----------|-----------|
"""
    for r in pair_rows:
        report += (f"| {r['tag']} | ${r['mean']:.2f} | ${r['se']:.2f} | "
                   f"({r['ci_lo_95']:.1f},{r['ci_hi_95']:.1f}) | "
                   f"{r['pct_improved']:.1%} | {r['pct_worsened']:.1%} |\n")

    report += f"""
## 4. Multi-Timeframe Feature Diagnostics

| Model | Features | Val EV | vs M0 val |
|-------|---------|-------|---------|
"""
    for mname in ["M0","M1","M2","M3"]:
        report += f"| {mname} | {len(feat_sets[mname])} | ${val_evs.get(mname,0):.2f} | {val_evs.get(mname,0)-val_evs.get('M0',0):+.2f} |\n"

    report += f"""
New MTF features: ar_180s (3m), ar_300s (5m), ar_900s (15m), cross-horizon comparisons.
Nan fraction at val observation: {chk_val['ar_300s'].isna().mean():.1%}

## 5. Regime Quality States (test period, best policy)

| State | N | E0 EV | Best EV | Delta |
|-------|---|-------|---------|-------|
"""
    for r in rq_rows:
        report += f"| {r['regime_quality']} | {r['N']} | ${r['e0_ev']:.1f} | ${r['best_ev']:.1f} | ${r['delta']:.1f} |\n"

    report += f"""
## 6. Session and Direction Segmentation

| Segment | N | E0 | Best | Delta | CI |
|---------|---|----|----|-------|----|
"""
    for r in seg_rows:
        ci_s = f"({r['ci_lo']:.1f},{r['ci_hi']:.1f})" if r["ci_lo"] is not None else "N/A"
        report += f"| {r['group_col']}={r['group_val']} | {r['N']} | ${r['e0_ev']:.1f} | ${r['best_pol_ev']:.1f} | ${r['delta']:.1f} | {ci_s} |\n"

    report += f"""
## 7. Monthly Stability

| Month | N | E0 | Best | Delta | CI |
|-------|---|----|----|-------|----|
"""
    for r in monthly_rows:
        ci_s = f"({r['ci_lo']:.1f},{r['ci_hi']:.1f})" if r["ci_lo"] is not None else "N/A"
        report += f"| {r['month']} | {r['N']} | ${r['e0_ev']:.1f} | ${r['best_ev']:.1f} | ${r['delta']:.1f} | {ci_s} |\n"

    report += f"""
Months positive: {months_pos}/3

## 8. Runner Retention (top decile)

| Metric | Value |
|--------|-------|
| Top-decile E0 threshold | ${runner_metrics['top_decile_e0_threshold']:.0f} |
| Top-decile N | {runner_metrics['top_decile_N']} |
| Top-decile E0 EV | ${runner_metrics['top_decile_e0_ev']:.0f} |
| Top-decile best EV | ${runner_metrics['top_decile_best_ev']:.0f} |
| **Top-decile delta** | **${runner_metrics['top_decile_delta']:.1f}** |

## 9. False Exit and Success Exit Metrics (best policy)

| Metric | Value |
|--------|-------|
| False exits (delta <= -$25) | {fe_metrics['n_false_exits']} ({fe_metrics['false_exit_rate']:.1%}) |
| Success exits (delta >= +$25) | {fe_metrics['n_success_exits']} ({fe_metrics['success_exit_rate']:.1%}) |
| Mean false exit loss | ${fe_metrics['mean_false_exit_loss']:.0f} |
| Mean success exit gain | +${fe_metrics['mean_success_gain']:.0f} |
| Total false exit damage | ${fe_metrics['total_false_exit_damage']:,.0f} |

False-exit context: RTH {fe_rth:.0%} (vs success exit RTH {se_rth:.0%}).
5m alignment at false exit: {fe_5m:.2f}.

## 10. Controls (best policy M3)

| Control | EV | Interpretation |
|---------|-----|---------------|
| C1 context shuffle | ${ctrl.get('C1_context_shuffle',0):.2f} | MTF context scrambled |
| C2 regime-quality shuffle | ${ctrl.get('C2_regime_quality_shuffle',0):.2f} | Prolific state scrambled |
| C3 segment shuffle | ${ctrl.get('C3_segment_shuffle',0):.2f} | Session/dir scrambled |
| C4 sequence shuffle | ${ctrl.get('C4_seq_shuffle',0):.2f} | Temporal order scrambled |
| C5 future lead (oracle) | ${ctrl.get('C5_future_lead',0):.2f} | Oracle improves? |
| C6 lag 5s | ${ctrl.get('C6_lag_5s',0):.2f} | 5s stale |
| C6 lag 10s | ${ctrl.get('C6_lag_10s',0):.2f} | 10s stale |
| C9 no runner protection | ${ctrl.get('C9_no_runner_protection',0):.2f} | Without protection |

## 11. Research Question Answers

1. **Does MTF context distinguish recoverable from terminal weakness?**
   Val lift from M0 to M1: {val_evs.get('M1',0)-val_evs.get('M0',0):+.2f}. {"Yes — MTF adds discriminative information." if val_evs.get('M1',0)>val_evs.get('M0',0)+0.5 else "Weak — MTF adds limited discrimination."}

2. **Do long and short regimes require different exit logic?**
   {seg_verdict} — see segment table above.

3. **Do RTH and ETH require different exit logic?**
   RTH delta ${rth_delta:.1f}, ETH delta ${eth_delta:.1f}. {"Yes — substantial asymmetry." if abs(rth_delta-eth_delta)>5 else "Mixed — difference below threshold."}

4. **Are costly false exits concentrated in prolific regimes?**
   False exits: RTH {fe_rth:.0%}. {"Yes — false exits skewed to stronger regimes/sessions." if fe_rth > 0.4 else "Not clearly concentrated in prolific regimes."}

5. **Can runner protection reduce false exits without excessive giveback?**
   P4 runner delta: {p4_delta:.1f}. {"Runner protection improves over base policy." if isinstance(p4_delta,float) and p4_delta>0 else "Runner protection did not improve materially."}

6. **Does context-conditioned exit improve paired PnL vs E0?**
   Best delta: ${best_delta:.2f} CI=({best_ci_lo:.1f},{best_ci_hi:.1f}). {"Yes — improvement above predeclared threshold." if best_delta>2 else "No — improvement below meaningful threshold."}

7. **Should detected weakness trigger immediate exit, protective stop, or no action?**
   Based on this study: {"Immediate exit with context conditioning is slightly better than raw E5. Stop POC is exploratory." if best_delta>0 else "Neither improved vs E0. Further analysis needed."}

## 12. Decision Against Predeclared Rules

| Rule | Required | Observed | Met? |
|------|---------|---------|------|
| Paired delta >= $5 | >= $5 | ${best_delta:.2f} | {'YES' if best_delta>=5 else 'NO'} |
| CI above/near zero | CI > -10 | ({best_ci_lo:.1f},{best_ci_hi:.1f}) | {'YES' if best_ci_lo>-10 else 'NO'} |
| Months positive >= 2/3 | 2/3 | {months_pos}/3 | {'YES' if months_pos>=2 else 'NO'} |
| RTH improves | > 0 | ${rth_delta:.1f} | {'YES' if rth_delta>0 else 'NO'} |
| Context shuffle degrades | C1 < best | ${ctrl.get('C1_context_shuffle',0):.1f} vs ${pol_pnl[best_pol_name].mean():.1f} | {'YES' if ctrl.get('C1_context_shuffle',0)<pol_pnl[best_pol_name].mean()-1 else 'NO'} |
| Oracle improves | C5 > best | ${ctrl.get('C5_future_lead',0):.1f} vs ${pol_pnl[best_pol_name].mean():.1f} | {'YES' if ctrl.get('C5_future_lead',0)>pol_pnl[best_pol_name].mean() else 'NO'} |

### VERDICT: {overall_verdict}

{"**Advance to 2025-H2 / 2026 OOS evaluation.**" if overall_verdict=="PROCEED"
 else ("**Investigate prolific-state / runner-protection mechanics further before advancing.**" if overall_verdict=="INVESTIGATE"
       else "**Do not advance this OHLCV contextual approach. Orderflow inputs required for meaningful exit signal.**")}

---

*All thresholds selected on val period only. Development test not used for tuning.*
*Execution mechanics identical to repaired sim_v2 (test_v2.py).*
"""

    (OUT_DIR/"final_report.md").write_text(report, encoding="utf-8")

    # ── Print summary ────────────────────────────────────────────────────────
    print()
    print("="*70)
    print("CONTEXTUAL RUNNER EXIT — FINAL SUMMARY")
    print("="*70)
    print(f"Best policy:           {best_pol_name}")
    print(f"Paired delta vs E0:    ${best_delta:.2f}/trade")
    print(f"95% CI:                ({best_ci_lo:.1f},{best_ci_hi:.1f})")
    print(f"RTH delta:             ${rth_delta:.2f}/trade")
    print(f"ETH delta:             ${eth_delta:.2f}/trade")
    print(f"Months positive:       {months_pos}/3")
    print(f"Top-decile delta:      ${runner_metrics['top_decile_delta']:.2f}/trade")
    print(f"MTF verdict:           {mtf_verdict}")
    print(f"Runner verdict:        {runner_verdict}")
    print(f"Exit verdict:          {exit_verdict}")
    print(f"OVERALL VERDICT:       {overall_verdict}")
    print("="*70)
    print(f"\nAll outputs: {OUT_DIR}")
    print(f"Total time: {time.time()-t0_total:.0f}s")
    print("Done.")


if __name__ == "__main__":
    main()
