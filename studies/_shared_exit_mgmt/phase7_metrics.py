"""Phase 7: required metrics per policy/population, computed
separately for the 2025 dev_test and 2026 reserved_eval periods
(never pooled, per the study spec).

Population-agnostic: operates purely on trades.parquet schemas shared
by every ExitManagementBaseStrategy/StopPolicyMixin run (E0 baseline
included, read from the Phase 1 raw collection rather than re-run).

KEY DESIGN FACT (verified empirically before building this module):
entries are NOT byte-identical between E0 and a policy variant that
exits some trades early -- NT's position-gated entry logic (a new
entry can only SUBMIT once self._trade is None) means an early stop
exit frees up entry capacity sooner than E0's sequential
exit-then-entry chain at a flip boundary, shifting subsequent
entry_ts by up to ~8 seconds for the same logical trade (verified on
ALL_FLIPS 2025 S1_checkpoint vs E0: 7342/7342 trades, 100% direction
match, median entry_ts diff 0s, max 8s). Trade-by-trade E0 comparison
therefore uses ORDINAL POSITION after sorting both by entry_ts, not
exact entry_ts equality.

STOP-ARMING-TO-HIT TIMING NOTE: `time from stop arming to stop hit`
and `time from stop arming to new MFE` require per-checkpoint
policy_state history, which checkpoints.parquet does NOT carry (only
the fixed causal fields `_update_open_trade` writes). These two
sub-metrics are computed by a separate, targeted replay
(phase7_arm_timing.py) restricted to trades that actually hit a stop
-- NOT by re-scoring the full checkpoint volume -- and are merged in
by the driver script if that replay has been run; otherwise they are
reported as NaN with a note, never silently fabricated.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

TICK_EPS = 1e-9


def _to_atr(df: pd.DataFrame) -> pd.DataFrame:
    """Attach ATR-normalized PnL/MFE/MAE/giveback columns. Uses
    atr_at_signal (the frozen ATR-at-entry, already on every
    trades.parquet row) as the normalizer -- same convention as
    Phase 1-4's *_atr_from_entry fields."""
    df = df.copy()
    atr = df["atr_at_signal"].replace(0, np.nan)
    d = df["direction"]
    ep = df["fill_price"]
    ex = df["exit_price"]
    df["net_pnl_atr"] = (ex - ep) * d / atr  # gross price move, ATR units
    df["mfe_atr"] = df["running_mfe"] / atr
    df["mae_atr"] = df["running_mae"] / atr
    df["giveback_atr"] = df["mfe_atr"] - df["net_pnl_atr"]
    return df


def load_trades(path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    return _to_atr(df)


def filter_window(df: pd.DataFrame, start: pd.Timestamp,
                       end: pd.Timestamp) -> pd.DataFrame:
    if len(df) == 0:
        return df
    return df[(df["entry_ts"] >= start.value)
                 & (df["entry_ts"] < end.value)].copy()


def _drawdown_stats(df: pd.DataFrame) -> tuple[float, float]:
    """Max drawdown (in $) and longest drawdown duration (in days,
    calendar time from peak to recovery/end) over the equity curve
    built from trades sorted by exit_ts."""
    if len(df) == 0:
        return 0.0, 0.0
    d = df.sort_values("exit_ts")
    equity = d["net_pnl"].cumsum().to_numpy()
    ts = d["exit_ts"].to_numpy()
    peak = -np.inf
    peak_ts = ts[0]
    max_dd = 0.0
    max_dd_dur_ns = 0
    for i in range(len(equity)):
        if equity[i] > peak:
            peak = equity[i]
            peak_ts = ts[i]
        dd = peak - equity[i]
        if dd > max_dd:
            max_dd = dd
        dur = ts[i] - peak_ts
        if dur > max_dd_dur_ns:
            max_dd_dur_ns = dur
    return float(max_dd), float(max_dd_dur_ns / 1e9 / 86400)  # days


def _runner_retention(df: pd.DataFrame, top_pct: float) -> float:
    """Among the top `top_pct` of trades by MFE (the biggest
    potential winners), mean(net_pnl_atr / mfe_atr) -- how much of
    the available move the policy's exit actually retained."""
    if len(df) == 0:
        return float("nan")
    n = max(1, int(round(len(df) * top_pct)))
    top = df.nlargest(n, "mfe_atr")
    valid = top[top["mfe_atr"] > TICK_EPS]
    if len(valid) == 0:
        return float("nan")
    return float((valid["net_pnl_atr"] / valid["mfe_atr"]).mean())


def match_ordinal(policy_df: pd.DataFrame, baseline_df: pd.DataFrame
                      ) -> pd.DataFrame:
    """Pair each policy trade with its E0 counterpart by ordinal
    position after sorting both by entry_ts (see module docstring for
    why exact entry_ts matching is wrong). Returns a frame with one
    row per matched pair: policy_net_pnl, baseline_net_pnl,
    policy_exit_reason, direction, mfe_atr (policy's), giveback_atr.
    Only defined when trade counts match (guaranteed by construction:
    only exit logic differs between E0 and any policy variant)."""
    p = policy_df.sort_values("entry_ts").reset_index(drop=True)
    b = baseline_df.sort_values("entry_ts").reset_index(drop=True)
    n = min(len(p), len(b))
    if len(p) != len(b):
        # Should not happen (entries are policy-independent) -- but
        # guard rather than silently mismatch if it ever does (e.g. a
        # dropped chunk-boundary trade, see nt_runner.py's documented
        # limitation).
        p, b = p.iloc[:n], b.iloc[:n]
    return pd.DataFrame({
        "direction": p["direction"].values,
        "policy_net_pnl": p["net_pnl"].values,
        "baseline_net_pnl": b["net_pnl"].values,
        "policy_exit_reason": p["exit_reason"].values,
        "policy_mfe_atr": p["mfe_atr"].values,
        "policy_giveback_atr": p["giveback_atr"].values,
    })


def compute_policy_metrics(
    policy_trades: pd.DataFrame, baseline_trades: pd.DataFrame,
    is_stop_policy: bool, n_eligible: int | None = None,
) -> dict:
    """Core Phase 7 metrics for one (policy, population, period)
    cell. `n_eligible` is the diag.json entries_scheduled count (falls
    back to len(policy_trades) if not supplied)."""
    df = policy_trades
    n_filled = len(df)
    n_eligible = n_eligible if n_eligible is not None else n_filled

    out: dict = {
        "n_eligible": int(n_eligible),
        "n_filled": int(n_filled),
    }
    if n_filled == 0:
        return out

    reason_counts = df["exit_reason"].value_counts().to_dict()
    out["n_opposite_flip_exits"] = int(reason_counts.get("opposite_flip", 0))
    out["n_stop_policy_exits"] = int(
        reason_counts.get("stop_policy", 0)
        + reason_counts.get("stop_policy_direct", 0))

    net_pnl = df["net_pnl"]
    out["ev_per_eligible_trade"] = float(net_pnl.sum() / max(1, n_eligible))
    out["ev_per_filled_trade"] = float(net_pnl.mean())
    out["net_pnl_total"] = float(net_pnl.sum())
    out["win_rate"] = float((net_pnl > 0).mean())
    wins = net_pnl[net_pnl > 0].sum()
    losses = -net_pnl[net_pnl < 0].sum()
    out["profit_factor"] = float(wins / losses) if losses > 0 else float("inf")

    max_dd, max_dd_dur = _drawdown_stats(df)
    out["max_drawdown"] = max_dd
    out["longest_drawdown_duration_days"] = max_dd_dur

    out["avg_mfe_captured_atr"] = float(df["net_pnl_atr"].mean())
    valid_mfe = df[df["mfe_atr"] > TICK_EPS]
    out["mfe_capture_ratio"] = (
        float((valid_mfe["net_pnl_atr"] / valid_mfe["mfe_atr"]).mean())
        if len(valid_mfe) else float("nan"))
    out["avg_giveback_atr"] = float(df["giveback_atr"].mean())

    for pct, label in ((0.10, "top10"), (0.05, "top5"), (0.01, "top1")):
        out[f"runner_retention_{label}"] = _runner_retention(df, pct)

    if is_stop_policy and "policy_state" in df.columns:
        stopped = df[df["exit_reason"].isin(
            ["stop_policy", "stop_policy_direct"])]
        out["avg_remaining_mfe_sacrificed_atr"] = (
            float(stopped["giveback_atr"].mean()) if len(stopped)
            else float("nan"))

    # ---- E0-matched comparisons (ordinal-position pairing) ----
    matched = match_ordinal(df, baseline_trades)
    diff = matched["baseline_net_pnl"] - matched["policy_net_pnl"]
    # diff > 0: E0 did BETTER (policy sacrificed profit or took a
    # worse loss than E0 would have on the same entry).
    out["giveback_reduction_vs_e0_atr"] = None  # filled by caller (needs e0 metrics)
    out["largest_sacrificed_winner"] = (
        float(diff.max()) if len(diff) and diff.max() > 0 else 0.0)
    out["largest_avoided_loss"] = (
        float((-diff).max()) if len(diff) and (-diff).max() > 0 else 0.0)

    if is_stop_policy:
        stop_mask = matched["policy_exit_reason"].isin(
            ["stop_policy", "stop_policy_direct"])
        stopped_matched = matched[stop_mask]
        if len(stopped_matched):
            better_or_equal = (stopped_matched["policy_net_pnl"]
                                    >= stopped_matched["baseline_net_pnl"])
            out["n_true_terminal_stops"] = int(better_or_equal.sum())
            out["n_false_recovery_stops"] = int((~better_or_equal).sum())
            avoided = (stopped_matched["policy_net_pnl"]
                          - stopped_matched["baseline_net_pnl"])
            avoided_positive = avoided[avoided > 0]
            out["avg_loss_avoided"] = (
                float(avoided_positive.mean()) if len(avoided_positive)
                else 0.0)
        else:
            out["n_true_terminal_stops"] = 0
            out["n_false_recovery_stops"] = 0
            out["avg_loss_avoided"] = float("nan")

    return out
