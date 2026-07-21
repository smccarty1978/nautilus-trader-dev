"""Shared loading + repair utilities for the R0/R1/R2/R4 rank-filter OOS
validation study (v2: canonical 30s-delay entry, RTH=09:30-16:00 CT).

Reuses the cached flip_context_atlas.parquet (built by
studies/regime_sequence_chop_context) and the frozen rank-skip config (built
by studies/regime_sequence_signal_audit) -- no retraining, no feature
rebuild. The only raw-data lookup performed here is a small, targeted one:
re-deriving each episode's entry PRICE under the canonical ~29-30s decision
delay (the atlas's cached entry_price/pnl_base assume immediate next-1s-open
fill with no delay -- confirmed against collectors/collector_v2's *_nodelay*
vs the legacy delayed v_a_v0_2025 dataset). This does not touch feature
computation or exit logic, so it is not a "raw 1s feature pipeline rerun."
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ATLAS_PATH = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet"
FROZEN_CONFIG_PATH = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results/rank_skip_frozen_config.json"
VA_DELAYED_FILE = PROJECT_ROOT / "collectors/collector_v2/results/v_a_v0_2025/trades.parquet"
RAW_DIR = PROJECT_ROOT / "data/raw"
OUT = PROJECT_ROOT / "studies/rank_filter_oos_validation/results"
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULTIPLIER = 20.0
CANONICAL_DELAY_NS = 29_000_000_000  # empirically calibrated against v_a_v0_2025
# (legacy delayed collector): entry_ts - decision_ts = 29s in 3,158/3,313
# (95.3%) of its 2025 trades; described in the task brief as "~30 seconds."
VAL_START, VAL_END = "2025-01-01", "2025-02-28"
PRIMARY_START, PRIMARY_END = "2025-06-01", "2025-12-31"


def load_atlas() -> pd.DataFrame:
    return pd.read_parquet(ATLAS_PATH)


def load_frozen_config() -> dict:
    with open(FROZEN_CONFIG_PATH) as f:
        return json.load(f)


def get_session(ts_ns_series: pd.Series) -> pd.Series:
    """CORRECTED session definition (this task's Phase 1 fix), matching the
    general project convention (CLAUDE.md): RTH = 08:30 <= Chicago local
    time < 15:00, Monday-Friday; ETH = all other times. This supersedes the
    prior run's incorrect 09:30-16:00 override."""
    ts = pd.to_datetime(ts_ns_series, unit="ns", utc=True)
    ct = ts.dt.tz_convert("America/Chicago")
    tod = ct.dt.hour * 3600 + ct.dt.minute * 60 + ct.dt.second
    is_weekday = ct.dt.dayofweek < 5
    is_rth = is_weekday & (tod >= 8 * 3600 + 30 * 60) & (tod < 15 * 3600)
    return pd.Series(np.where(is_rth, "RTH", "ETH"), index=ts_ns_series.index)


def detect_terminal_violations(df_atlas: pd.DataFrame) -> pd.DataFrame:
    """Same pre-existing defect found in the sibling studies: F2 confirmation
    decided after its own episode's terminal time, from 1m-bar-array gaps."""
    viol = df_atlas[df_atlas["observation_time"] > df_atlas["ep_end_time"]].copy()
    rows = []
    for i, r in viol.iterrows():
        rows.append({
            "episode_id": i, "population": r["population"],
            "violation_type": "decision_after_terminal_time",
            "gap_seconds": float((r["observation_time"] - r["ep_end_time"]) / 1e9),
        })
    return pd.DataFrame(rows)


_year_cache: dict[int, pd.DataFrame] = {}


def _year_file(year: int) -> Path:
    p = RAW_DIR / f"NQ_v0_1s_{year}.parquet"
    if not p.exists() and year == 2026:
        p = RAW_DIR / "NQ_v0_1s_2026_ytd.parquet"
    return p


def _get_year_df(year: int) -> pd.DataFrame | None:
    if year not in _year_cache:
        p = _year_file(year)
        if not p.exists():
            _year_cache[year] = None
        else:
            _year_cache[year] = pd.read_parquet(p, columns=["open"])
    return _year_cache[year]


def audit_delayed_entry(f2: pd.DataFrame) -> pd.DataFrame:
    """For every confirmed F2 signal, audit the exact delayed-entry mechanics:

        confirmation_ts -> decision_ts -> expected_fill_ts (+30s exactly)
        -> actual_fill_ts (next available 1s-open at/after expected_fill_ts)

    Classifies every signal by mismatch type and, separately, flags signals
    where the opposite regime flip occurs before the delayed entry would
    activate (pending_entry_canceled -- handled explicitly by the caller,
    never silently dropped or given a fabricated $0 PnL).
    """
    f2 = f2.copy()
    direction = f2["direction"].astype(int)
    opp_close = f2["close"] + (f2["E0_regime_exit_pnl"] + 5.0) / (NQ_MULTIPLIER * direction)

    confirmation_ts = f2["observation_time"]
    decision_ts = confirmation_ts  # decision is made at the confirmation instant itself
    expected_fill_ts = decision_ts + CANONICAL_DELAY_NS  # exact +30s target

    years = pd.to_datetime(confirmation_ts, unit="ns", utc=True).dt.year

    actual_fill_ts = pd.Series(np.nan, index=f2.index)
    actual_fill_price = pd.Series(np.nan, index=f2.index)
    exact_bar_exists = pd.Series(False, index=f2.index)

    for yr in years.unique():
        df_yr = _get_year_df(int(yr))
        if df_yr is None:
            continue
        mask = years == yr
        idx = df_yr.index
        targets = expected_fill_ts[mask].values
        target_dt = pd.to_datetime(targets, unit="ns", utc=True)
        i_fill = idx.get_indexer(target_dt, method="backfill")   # next bar at/after target
        i_exact = idx.get_indexer(target_dt)                     # exact match only (-1 if none)
        valid = i_fill >= 0
        sel = f2.index[mask][valid]
        actual_fill_ts.loc[sel] = idx[i_fill[valid]].view(np.int64)
        actual_fill_price.loc[sel] = df_yr["open"].values[i_fill[valid]]
        exact_sel = f2.index[mask][i_exact >= 0]
        exact_bar_exists.loc[exact_sel] = True

    f2["confirmation_ts"] = confirmation_ts
    f2["decision_ts"] = decision_ts
    f2["expected_fill_ts"] = expected_fill_ts
    f2["actual_fill_ts"] = actual_fill_ts
    f2["expected_fill_price"] = np.where(exact_bar_exists, actual_fill_price, np.nan)
    f2["actual_fill_price"] = actual_fill_price
    f2["timestamp_match"] = exact_bar_exists
    f2["price_match"] = exact_bar_exists  # identical bar => price matches by construction when ts matches
    f2["lookup_failed"] = actual_fill_ts.isna()

    fill_gap_s = (actual_fill_ts - expected_fill_ts) / 1e9
    f2["fill_gap_seconds"] = fill_gap_s

    conditions = [
        f2["lookup_failed"],
        f2["timestamp_match"],
        (~f2["lookup_failed"]) & (fill_gap_s <= 5),
        (~f2["lookup_failed"]) & (fill_gap_s > 5),
    ]
    choices = ["missing_replay_bar", "exact_match", "sparse_data_forward_fill", "large_gap_anomaly"]
    f2["mismatch_class"] = np.select(conditions, choices, default="unknown")

    f2["opposite_flip_before_activation"] = (~f2["lookup_failed"]) & (f2["actual_fill_ts"] >= f2["ep_end_time"])

    f2["baseline_pnl_if_filled"] = direction * (opp_close - f2["actual_fill_price"]) * NQ_MULTIPLIER - 5.0
    return f2


def repair_f2_window(df_atlas: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Full repair pipeline restricted to [start, end] (inclusive date
    range). Returns (all confirmed signals with trade_status classification,
    terminal_violations for that window). `all_confirmed_signals` includes
    pending-entry-canceled rows (kept, not dropped, PnL = NaN, never a
    fabricated $0) -- callers must filter on trade_status themselves.

    trade_status values:
      'filled'                 - normal delayed entry, real PnL
      'pending_entry_canceled' - opposite flip occurred before the delayed
                                  entry could activate; no trade, no PnL
      'missing_replay_bar'     - raw-data lookup ran off the end of the
                                  available year file; no trade, no PnL
    Signals with 'decision_after_terminal_time' (the confirmation bar itself
    closes after its own regime's terminal time -- a defect in confirmation,
    not in the delay) are not valid signals at all and are excluded from the
    returned frame entirely (reported separately by the execution audit).
    """
    f2 = df_atlas[df_atlas["population"] == "F2"].copy()
    f2["episode_id"] = f2.index
    f2["direction"] = f2["regime"].astype(int)
    f2["session"] = get_session(f2["observation_time"])

    ts_ct = pd.to_datetime(f2["observation_time"], unit="ns", utc=True).dt.tz_convert("America/Chicago")
    f2["month"] = ts_ct.dt.strftime("%Y-%m")
    f2["chicago_local_ts"] = ts_ct.astype(str)

    ts_utc = pd.to_datetime(f2["observation_time"], unit="ns", utc=True)
    in_window = (ts_utc >= pd.Timestamp(start, tz="UTC")) & (ts_utc <= pd.Timestamp(end + " 23:59:59.999999999", tz="UTC"))
    f2 = f2[in_window].copy()

    terminal_viol = detect_terminal_violations(df_atlas)
    terminal_viol_ids = set(terminal_viol.loc[terminal_viol["population"] == "F2", "episode_id"]) & set(f2["episode_id"])
    f2 = f2[~f2["episode_id"].isin(terminal_viol_ids)].copy()  # not valid signals; excluded upstream of delay logic

    f2 = audit_delayed_entry(f2)

    f2["trade_status"] = np.select(
        [f2["lookup_failed"], f2["opposite_flip_before_activation"]],
        ["missing_replay_bar", "pending_entry_canceled"],
        default="filled",
    )

    f2["baseline_pnl"] = np.where(f2["trade_status"] == "filled", f2["baseline_pnl_if_filled"], np.nan)
    f2["entry_price"] = np.where(f2["trade_status"] == "filled", f2["actual_fill_price"], np.nan)

    window_terminal_viol = terminal_viol[terminal_viol["episode_id"].isin(terminal_viol_ids)]
    return f2, window_terminal_viol
