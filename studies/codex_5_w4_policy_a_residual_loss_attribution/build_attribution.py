"""Build descriptive residual-loss attribution for frozen W4 Policy A outcomes."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, AUDIT = STUDY / "results", STUDY / "audit"
CONFIG_PATH, FREEZE_PATH = STUDY / "config.json", STUDY / "input_freeze.json"
PRE_AUDIT, PRE_AUTH = AUDIT / "pre_execution_audit.md", AUDIT / "pre_execution_authorization.json"
ISOLATION = ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
ISOLATION_RESULTS = ISOLATION / "results"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
NS, TIMEOUT_NS = 1_000_000_000, 300_000_000_000

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402

for directory in (RESULTS, AUDIT):
    directory.mkdir(parents=True, exist_ok=True)


def trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def require_authorization() -> None:
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists():
        raise RuntimeError("missing pre-execution authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    clean = (re.search(r"^\*\*Status:\*\*\s+\*\*PASS(?:\s|\*|-|\u2014)", text, re.MULTILINE)
             and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$", text, re.MULTILINE))
    if not clean:
        raise RuntimeError("audit is not a clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH), "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(key) != value for key, value in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def validate_freeze() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_ATTRIBUTION" or not freeze.get("analysis_only"):
        raise RuntimeError("attribution freeze is inactive")
    if config.get("policy_id") != "POLICY_A_COMBINED_1P25_300S" or config.get("timeout_seconds") != 300:
        raise RuntimeError("unexpected policy attribution scope")
    expected_config = {"align_time_seconds": [60, 120, 300], "regime_age_minutes": [15, 30, 60, 120],
        "w4_score_edges": [0.70, 0.75, 0.80], "mfe_timeout_atr_edges": [0.25, 0.50, 0.75, 1.00],
        "pnl_timeout_atr_edges": [-1.00, -0.50, 0.00, 0.50, 1.00]}
    if any(config.get(key) != value for key, value in expected_config.items()):
        raise RuntimeError("descriptive bucket config changed")
    current = {"isolation_trade_diffs": sha256_file(ISOLATION_RESULTS / "isolation_trade_diffs.parquet"),
        "isolation_completion_audit": sha256_file(ISOLATION / "audit" / "completion_audit.md"),
        "isolation_manifest": sha256_file(ISOLATION_RESULTS / "run_manifest.json"),
        "2025_trades": sha256_file(trade_path(2025)), "2026_trades": sha256_file(trade_path(2026)),
        "2025_raw": sha256_file(RAW_1S[2025]), "2026_raw": sha256_file(RAW_1S[2026])}
    if current != freeze["input_sha256"]:
        raise RuntimeError("frozen attribution input changed")
    return config


def align_time_bucket(reached: bool, confirm_ts: int, exit_ts: int, elapsed_s: float) -> str:
    if not reached and confirm_ts >= exit_ts:
        return "no_flip_before_exit"
    if elapsed_s <= 60:
        return "0-60s"
    if elapsed_s <= 120:
        return "60-120s"
    if elapsed_s <= 300:
        return "120-300s"
    return ">300s"


def regime_age_bucket(seconds: float) -> str:
    minutes = seconds / 60.0
    if minutes < 15:
        return "<15m"
    if minutes < 30:
        return "15-30m"
    if minutes < 60:
        return "30-60m"
    if minutes < 120:
        return "60-120m"
    return ">=120m"


def w4_bucket(score: float) -> str:
    if score < 0.70:
        return "<0.70"
    if score < 0.75:
        return "0.70-0.75"
    if score < 0.80:
        return "0.75-0.80"
    return ">=0.80"


def mfe_bucket(value: float, alive: bool) -> str:
    if not alive:
        return "not_alive_at_timeout"
    if value < 0.25:
        return "<0.25"
    if value < 0.50:
        return "0.25-0.50"
    if value < 0.75:
        return "0.50-0.75"
    if value < 1.00:
        return "0.75-1.00"
    return ">=1.00"


def pnl_bucket(value: float, alive: bool) -> str:
    if not alive:
        return "not_alive_at_timeout"
    if value < -1.00:
        return "<-1.00"
    if value < -0.50:
        return "-1.00--0.50"
    if value < 0.00:
        return "-0.50-0.00"
    if value < 0.50:
        return "0.00-0.50"
    if value < 1.00:
        return "0.50-1.00"
    return ">=1.00"


def timeout_state(row: pd.Series, trade: pd.Series, raw: pd.DataFrame) -> dict:
    timeout_ts = int(row.entry_fill_ts) + TIMEOUT_NS
    stop_at_timeout = (int(row.new_exit_fill_ts) == timeout_ts and "stop" in str(row.new_exit_reason))
    alive = int(row.new_exit_fill_ts) > timeout_ts or stop_at_timeout
    if not alive:
        return {"alive_at_timeout": False, "mfe_at_timeout_atr": np.nan,
                "pnl_at_timeout_atr": np.nan, "timeout_mark_ts": pd.NA,
                "timeout_mark_staleness_s": np.nan}
    ts = raw.index.view(np.int64)
    start = int(np.searchsorted(ts, int(row.entry_fill_ts), side="left"))
    end = int(np.searchsorted(ts, timeout_ts, side="left"))
    if start >= len(ts) or int(ts[start]) != int(row.entry_fill_ts) or end <= start:
        raise RuntimeError("invalid timeout path interval")
    direction, entry, atr = int(trade.entry_direction), float(trade.entry_fill_open), float(trade.atr_at_checkpoint)
    highs = raw.high.to_numpy(float)[start:end]
    lows = raw.low.to_numpy(float)[start:end]
    if direction == 1:
        mfe_points = max(float(np.max(highs)) - entry, 0.0)
    else:
        mfe_points = max(entry - float(np.min(lows)), 0.0)
    mark_i = end - 1
    mark_close = float(raw.close.iloc[mark_i])
    mark_ts = int(ts[mark_i])
    pnl_atr = direction * (mark_close - entry) / atr
    staleness = max((timeout_ts - (mark_ts + NS)) / NS, 0.0)
    return {"alive_at_timeout": True, "mfe_at_timeout_atr": mfe_points / atr,
            "pnl_at_timeout_atr": pnl_atr, "timeout_mark_ts": mark_ts,
            "timeout_mark_staleness_s": staleness}


def residual_loss_mode(row: pd.Series) -> str:
    if float(row.new_net_pnl_usd) >= 0:
        return "policy_non_loss"
    if not bool(row.reached_aligning_flip):
        if row.new_exit_reason == "preflip_policy_stop":
            return "stopped_before_alignment"
        if row.new_exit_reason == "confirmation_timeout_exit":
            return "timed_out_before_alignment"
        return "other_pre_alignment_loss"
    if row.new_exit_reason == "original_stop_after_aligned_flip":
        return "reached_alignment_then_stopped"
    if row.new_exit_reason == "original_opposing_flip_exit":
        return "reached_alignment_then_planned_exit_loss"
    return "other_post_alignment_loss"


def load_trades() -> pd.DataFrame:
    frames = []
    for year in (2025, 2026):
        frame = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
        frame["trade_id"] = [f"{year}_{index:05d}" for index in range(len(frame))]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def build_trade_attribution() -> pd.DataFrame:
    diffs = pd.read_parquet(ISOLATION_RESULTS / "isolation_trade_diffs.parquet")
    diffs = diffs[diffs.policy_id == "POLICY_A_COMBINED_1P25_300S"].copy()
    trades = load_trades()
    required_trade_columns = ["trade_id", "confirm_flip_ns", "regime_age_s", "decision_ts", "w4_score",
        "entry_direction", "entry_fill_open", "atr_at_checkpoint"]
    frame = diffs.merge(trades[required_trade_columns], on="trade_id", how="left", validate="one_to_one")
    if len(frame) != 4383 or frame.confirm_flip_ns.isna().any():
        raise RuntimeError("trade attribution join failure")
    if not (frame.entry_fill_ts.astype("int64") == frame.trade_id.map(
            trades.set_index("trade_id").entry_fill_ts.astype("int64"))).all():
        raise RuntimeError("trade attribution entry mismatch")
    raw_by_year = {}
    timeout_rows = []
    trade_lookup = trades.set_index("trade_id")
    for row in frame.itertuples(index=False):
        if row.year not in raw_by_year:
            raw = pd.read_parquet(RAW_1S[int(row.year)], columns=["open", "high", "low", "close", "volume"])
            validate_raw_bars(raw)
            raw_by_year[row.year] = raw
        timeout_rows.append(timeout_state(pd.Series(row._asdict()), trade_lookup.loc[row.trade_id], raw_by_year[row.year]))
    timeout = pd.DataFrame(timeout_rows)
    timeout["timeout_mark_ts"] = pd.array(timeout.timeout_mark_ts, dtype="Int64")
    frame = pd.concat([frame.reset_index(drop=True), timeout], axis=1)
    elapsed = (frame.confirm_flip_ns.astype("int64") - frame.entry_fill_ts.astype("int64")) / NS
    frame["time_to_aligning_flip_s"] = elapsed
    frame["time_to_align_bucket"] = [align_time_bucket(bool(reached), int(confirm), int(exit_ts), float(seconds))
        for reached, confirm, exit_ts, seconds in zip(frame.reached_aligning_flip, frame.confirm_flip_ns,
                                                       frame.new_exit_fill_ts, elapsed)]
    entry_delay_s = (frame.entry_fill_ts.astype("int64") - frame.decision_ts.astype("int64")) / NS
    if (entry_delay_s < 0).any():
        raise RuntimeError("entry precedes W4 decision")
    frame["regime_age_at_entry_s"] = frame.regime_age_s + entry_delay_s
    frame["regime_age_bucket"] = frame.regime_age_at_entry_s.map(regime_age_bucket)
    frame["w4_score_bucket"] = frame.w4_score.map(w4_bucket)
    frame["mfe_at_timeout_bucket"] = [mfe_bucket(float(value), bool(alive))
        for value, alive in zip(frame.mfe_at_timeout_atr.fillna(0.0), frame.alive_at_timeout)]
    frame["pnl_at_timeout_bucket"] = [pnl_bucket(float(value), bool(alive))
        for value, alive in zip(frame.pnl_at_timeout_atr.fillna(0.0), frame.alive_at_timeout)]
    frame["year_direction_session"] = (frame.year.astype(str) + "|" + frame.trade_direction + "|" + frame.session)
    frame["residual_loss_mode"] = frame.apply(residual_loss_mode, axis=1)
    frame["late_aligning_baseline_winner_timed_out"] = (
        (frame.original_outcome_group == "opposite_flip_exit_winner")
        & (frame.new_exit_reason == "confirmation_timeout_exit") & (elapsed > 300))
    frame["late_winner_timeout_bucket"] = np.where(
        frame.late_aligning_baseline_winner_timed_out, "late_winner_timeout_clip", "other")
    frame["positive_pnl_capture_change_usd"] = (
        frame.new_net_pnl_usd.clip(lower=0) - frame.original_net_pnl_usd.clip(lower=0))
    frame = frame.sort_values("entry_fill_ts").reset_index(drop=True)
    for column in ("entry_fill_ts", "new_exit_fill_ts", "confirm_flip_ns"):
        if not pd.api.types.is_integer_dtype(frame[column].dtype):
            raise RuntimeError(f"timestamp dtype is not integer: {column}")
    return frame


def profit_factor(pnl: pd.Series) -> float:
    losses = -pnl[pnl < 0].sum()
    return pnl[pnl > 0].sum() / losses if losses > 0 else np.nan


def max_drawdown(pnl: pd.Series) -> float:
    equity = np.concatenate(([0.0], pnl.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(equity) - equity))


DIMENSIONS = {
    "year": "year", "direction": "trade_direction", "session": "session",
    "year_direction_session": "year_direction_session",
    "original_outcome_group": "original_outcome_group", "policy_exit_reason": "new_exit_reason",
    "time_to_aligning_flip_bucket": "time_to_align_bucket", "entry_regime_age_bucket": "regime_age_bucket",
    "w4_score_bucket": "w4_score_bucket", "mfe_at_timeout_bucket": "mfe_at_timeout_bucket",
    "pnl_at_timeout_bucket": "pnl_at_timeout_bucket", "residual_loss_mode": "residual_loss_mode",
    "late_winner_timeout": "late_winner_timeout_bucket",
}


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dimension, column in DIMENSIONS.items():
        dimension_total_loss = -frame.loc[frame.new_net_pnl_usd < 0, "new_net_pnl_usd"].sum()
        for value, group in frame.groupby(column, dropna=False, sort=False):
            group = group.sort_values("entry_fill_ts")
            pnl = group.new_net_pnl_usd
            gross_loss = -pnl[pnl < 0].sum()
            rows.append({"dimension": dimension, "bucket": str(value), "trade_count": len(group),
                "total_net_pnl_usd": pnl.sum(), "mean_net_pnl_usd": pnl.mean(),
                "win_rate": (pnl > 0).mean(), "profit_factor": profit_factor(pnl),
                "average_winner_usd": pnl[pnl > 0].mean(), "average_loser_usd": pnl[pnl < 0].mean(),
                "gross_loss_usd": gross_loss,
                "gross_loss_share_within_dimension": gross_loss / dimension_total_loss if dimension_total_loss else np.nan,
                "bucket_max_trade_sequence_drawdown_usd": max_drawdown(pnl),
                "baseline_total_net_pnl_usd": group.original_net_pnl_usd.sum(),
                "policy_vs_baseline_change_usd": group.net_pnl_change_usd.sum(),
                "positive_pnl_capture_change_usd": group.positive_pnl_capture_change_usd.sum(),
                "year_2025_count": int((group.year == 2025).sum()),
                "year_2025_total_net_pnl_usd": group.loc[group.year == 2025, "new_net_pnl_usd"].sum(),
                "year_2026_count": int((group.year == 2026).sum()),
                "year_2026_total_net_pnl_usd": group.loc[group.year == 2026, "new_net_pnl_usd"].sum()})
    return pd.DataFrame(rows)


def main() -> None:
    require_authorization()
    validate_freeze()
    attribution = build_trade_attribution()
    summary = summarize(attribution)
    attribution.to_parquet(RESULTS / "policy_a_residual_loss_attribution.parquet", index=False)
    summary.to_parquet(RESULTS / "policy_a_bucket_summary.parquet", index=False)
    manifest = {"status": "ATTRIBUTION_COMPLETE_PENDING_REPORT_AUDIT", "trade_count": len(attribution),
        "policy_id": "POLICY_A_COMBINED_1P25_300S", "script_sha256": script_sha256(),
        "config_sha256": sha256_file(CONFIG_PATH), "freeze_sha256": sha256_file(FREEZE_PATH),
        "output_sha256": {name: sha256_file(RESULTS / name) for name in
            ("policy_a_residual_loss_attribution.parquet", "policy_a_bucket_summary.parquet")}}
    (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{len(attribution):,} Policy A trades; {len(summary):,} bucket rows")


if __name__ == "__main__":
    main()
