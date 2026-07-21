"""Run the fixed PR10/PR30 delayed-entry replay on repaired W4 candidates."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, WORK, AUDIT = STUDY / "results", STUDY / "_work", STUDY / "audit"
CONFIG_PATH, FREEZE_PATH = STUDY / "config.json", STUDY / "input_freeze.json"
PRE_AUDIT = AUDIT / "pre_execution_audit.md"
PRE_AUTH = AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
ISOLATION = ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
ISOLATION_DIFFS = ISOLATION / "results" / "isolation_trade_diffs.parquet"
NS, TIMEOUT_NS = 1_000_000_000, 300_000_000_000
MULTIPLIER, COST = 20.0, 10.0
POLICY_A_ID = "POLICY_A_COMBINED_1P25_300S"

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402

for directory in (RESULTS, WORK, AUDIT):
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
             and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                           text, re.MULTILINE))
    if not clean:
        raise RuntimeError("pre-execution audit is not a clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH),
                "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(key) != value for key, value in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def validate_freeze() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_ANY_NEW_CODE_TEST_OR_REPLAY":
        raise RuntimeError("input freeze is inactive")
    policies = config.get("policies", [])
    if [p.get("policy_id") for p in policies] != ["PR10", "PR30"]:
        raise RuntimeError("unexpected policy IDs")
    if [p.get("delay_seconds") for p in policies] != [10, 30]:
        raise RuntimeError("unexpected delay set")
    fixed = {"virtual_directional_pnl_threshold_points": 0.0,
             "confirmation_mark": "latest_fully_completed_1s_close",
             "delayed_fill_rule": "first_available_1s_open_strictly_after_gate_decision",
             "timeout_anchor": "actual_delayed_entry_fill", "timeout_seconds": 300,
             "preflip_stop_atr": 1.25, "postflip_stop_atr": 1.5,
             "atr_denominator": "atr_at_checkpoint"}
    if any(config.get(key) != value for key, value in fixed.items()):
        raise RuntimeError("causal execution contract changed")
    current = {
        "2025_raw": sha256_file(RAW_1S[2025]),
        "2026_raw": sha256_file(RAW_1S[2026]),
        "2025_trades": sha256_file(trade_path(2025)),
        "2026_trades": sha256_file(trade_path(2026)),
        "policy_a_isolation_diffs": sha256_file(ISOLATION_DIFFS),
        "policy_a_isolation_completion_audit": sha256_file(ISOLATION / "audit" / "completion_audit.md"),
        "policy_a_isolation_manifest": sha256_file(ISOLATION / "results" / "run_manifest.json"),
    }
    if current != freeze.get("input_sha256"):
        raise RuntimeError("frozen dependency mismatch")
    if freeze.get("candidate_count") != 4383 or freeze.get("policy_ids") != ["PR10", "PR30"]:
        raise RuntimeError("unexpected frozen opportunity set")
    return config


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def stop_fill(direction: int, stop: float, open_px: float) -> float:
    gap = open_px <= stop if direction == 1 else open_px >= stop
    return open_px if gap else stop


def gate_candidate(t: pd.Series, raw: pd.DataFrame, delay_seconds: int) -> dict:
    """Evaluate a causal gate and locate a strictly later actual entry open."""
    ts = raw.index.view(np.int64)
    closes = raw["close"].to_numpy(float)
    opens = raw["open"].to_numpy(float)
    original_ts = int(t.entry_fill_ts)
    original_px = float(t.entry_fill_open)
    direction = int(t.entry_direction)
    align_ts = int(t.confirm_flip_ns)
    gate_ts = original_ts + int(delay_seconds) * NS

    # A bar stamped s covers [s, s+1s). At tg, only bars with s+1s <= tg
    # are complete. search-left(tg)-1 selects the latest such regular bar and
    # remains conservative across raw-data gaps.
    mark_i = int(np.searchsorted(ts, gate_ts, side="left")) - 1
    if mark_i < 0 or int(ts[mark_i]) + NS > gate_ts:
        raise RuntimeError("no fully completed confirmation bar")
    mark_ts = int(ts[mark_i])
    mark_close = float(closes[mark_i])
    virtual_points = direction * (mark_close - original_px)
    mark_staleness_s = (gate_ts - (mark_ts + NS)) / NS

    base = {"gate_decision_ts": gate_ts, "confirmation_mark_ts": mark_ts,
            "confirmation_mark_close": mark_close,
            "confirmation_mark_staleness_s": mark_staleness_s,
            "virtual_directional_pnl_points": virtual_points,
            "virtual_directional_pnl_atr": virtual_points / float(t.atr_at_checkpoint)}
    if align_ts <= gate_ts:
        return {**base, "approved": False, "skip_reason": "regime_ended_by_confirmation",
                "delayed_entry_fill_ts": pd.NA, "delayed_entry_fill_open": np.nan}
    if virtual_points < 0.0:
        return {**base, "approved": False, "skip_reason": "adverse_virtual_response",
                "delayed_entry_fill_ts": pd.NA, "delayed_entry_fill_open": np.nan}

    entry_i = int(np.searchsorted(ts, gate_ts, side="right"))
    if entry_i >= len(ts):
        return {**base, "approved": False, "skip_reason": "no_later_entry_open",
                "delayed_entry_fill_ts": pd.NA, "delayed_entry_fill_open": np.nan}
    delayed_ts = int(ts[entry_i])
    if align_ts <= delayed_ts:
        return {**base, "approved": False, "skip_reason": "aligning_flip_before_delayed_entry",
                "delayed_entry_fill_ts": pd.NA, "delayed_entry_fill_open": np.nan}
    return {**base, "approved": True, "skip_reason": "executed",
            "delayed_entry_fill_ts": delayed_ts,
            "delayed_entry_fill_open": float(opens[entry_i])}


def simulate_delayed(t: pd.Series, raw: pd.DataFrame, gate: dict) -> dict:
    """Replay fixed Policy A from an approved delayed actual fill."""
    if not gate["approved"]:
        raise ValueError("cannot replay a rejected gate")
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[column].to_numpy(float) for column in ("open", "high", "low"))
    entry_ts = int(gate["delayed_entry_fill_ts"])
    entry = float(gate["delayed_entry_fill_open"])
    direction, atr = int(t.entry_direction), float(t.atr_at_checkpoint)
    align_ts = int(t.confirm_flip_ns)
    scheduled_decision = int(t.scheduled_exit_decision_ts)
    timeout_ts = entry_ts + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled_decision, side="left"))
    if start >= len(ts) or int(ts[start]) != entry_ts:
        raise RuntimeError("delayed entry is not an exact raw open")
    if align_ts <= entry_ts:
        raise RuntimeError("invalid delayed entry after completed setup")
    if scheduled_i >= len(ts):
        raise RuntimeError("scheduled exit has no next raw open")
    scheduled_fill_ts = int(ts[scheduled_i])

    preflip_stop = entry - direction * 1.25 * atr
    postflip_stop = entry - direction * 1.5 * atr
    aligned, timeout_pending = False, False
    exit_ts, exit_px, reason = None, np.nan, None
    for i in range(start, scheduled_i + 1):
        now = int(ts[i])
        if not aligned and now >= align_ts and align_ts <= timeout_ts:
            aligned = True
        if timeout_pending and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if not aligned and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if now >= scheduled_fill_ts:
            exit_ts, exit_px, reason = now, opens[i], "original_opposing_flip_exit"
            break
        if not aligned and now >= align_ts:
            aligned = True
        if now == timeout_ts and not aligned:
            timeout_pending = True
        active_stop = postflip_stop if aligned else preflip_stop
        stop_reason = "original_stop_after_aligned_flip" if aligned else "preflip_policy_stop"
        if touched_stop(direction, active_stop, highs[i], lows[i]):
            exit_ts, exit_px, reason = now, stop_fill(direction, active_stop, opens[i]), stop_reason
            break
    if exit_ts is None:
        raise RuntimeError("delayed replay ended without exit")
    points = direction * (float(exit_px) - entry)
    return {"new_exit_fill_ts": int(exit_ts), "new_exit_fill_px": float(exit_px),
            "new_exit_reason": reason, "reached_aligning_flip": bool(aligned),
            "timeout_ts": timeout_ts, "stop_submission_ts": entry_ts,
            "stop_active_entry_bar": True, "new_gross_pnl_pts": points,
            "new_gross_pnl_usd": points * MULTIPLIER,
            "new_net_pnl_usd": points * MULTIPLIER - COST}


def load_policy_a(year: int) -> pd.DataFrame:
    frame = pd.read_parquet(ISOLATION_DIFFS)
    frame = frame[(frame.policy_id == POLICY_A_ID) & (frame.year == year)].copy()
    return frame.sort_values("entry_fill_ts").reset_index(drop=True)


def build_year(year: int, config: dict) -> pd.DataFrame:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    trades = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
    baseline = load_policy_a(year)
    if len(trades) != len(baseline) or len(trades) != (3246 if year == 2025 else 1137):
        raise RuntimeError("opportunity-set cardinality mismatch")
    expected_ids = [f"{year}_{index:05d}" for index in range(len(trades))]
    if baseline.trade_id.tolist() != expected_ids:
        raise RuntimeError("Policy A trade IDs are not the frozen entry order")

    rows = []
    for index, t in trades.iterrows():
        trade_id = expected_ids[index]
        b = baseline.iloc[index]
        if int(b.entry_fill_ts) != int(t.entry_fill_ts):
            raise RuntimeError(f"Policy A entry mismatch: {trade_id}")
        for policy in config["policies"]:
            gate = gate_candidate(t, raw, int(policy["delay_seconds"]))
            result = (simulate_delayed(t, raw, gate) if gate["approved"] else
                      {"new_exit_fill_ts": pd.NA, "new_exit_fill_px": np.nan,
                       "new_exit_reason": "skipped", "reached_aligning_flip": False,
                       "timeout_ts": pd.NA, "stop_submission_ts": pd.NA,
                       "stop_active_entry_bar": False, "new_gross_pnl_pts": 0.0,
                       "new_gross_pnl_usd": 0.0, "new_net_pnl_usd": 0.0})
            delayed_ts = gate["delayed_entry_fill_ts"]
            delayed_px = gate["delayed_entry_fill_open"]
            fill_change = (int(t.entry_direction) * (float(delayed_px) - float(t.entry_fill_open))
                           if gate["approved"] else np.nan)
            rows.append({"policy_id": policy["policy_id"], "delay_seconds": policy["delay_seconds"],
                "trade_id": trade_id, "year": year,
                "trade_direction": "long_fade" if int(t.entry_direction) == 1 else "short_fade",
                "session": str(t.session), "original_entry_fill_ts": int(t.entry_fill_ts),
                "original_entry_fill_open": float(t.entry_fill_open),
                "atr_at_checkpoint": float(t.atr_at_checkpoint), "w4_score": float(t.w4_score),
                "aligning_flip_ts": int(t.confirm_flip_ns),
                "scheduled_exit_decision_ts": int(t.scheduled_exit_decision_ts),
                "original_outcome_group": str(b.original_outcome_group),
                "policy_a_exit_reason": str(b.new_exit_reason),
                "policy_a_net_pnl_usd": float(b.new_net_pnl_usd),
                **gate, **result, "delayed_entry_directional_fill_change_points": fill_change,
                "fill_improved": bool(gate["approved"] and fill_change < -1e-12),
                "fill_worsened": bool(gate["approved"] and fill_change > 1e-12),
                "fill_unchanged": bool(gate["approved"] and abs(fill_change) <= 1e-12),
                "net_pnl_change_vs_policy_a_usd": float(result["new_net_pnl_usd"])
                                                     - float(b.new_net_pnl_usd)})
    frame = pd.DataFrame(rows)
    for column in ("delayed_entry_fill_ts", "new_exit_fill_ts", "timeout_ts", "stop_submission_ts"):
        frame[column] = pd.array(frame[column], dtype="Int64")
    return frame


def profit_factor(pnl: pd.Series) -> float:
    losses = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / losses) if losses > 0 else np.nan


def max_trade_sequence_drawdown(pnl: pd.Series) -> float:
    equity = np.concatenate(([0.0], pnl.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(equity) - equity))


def split_specs(frame: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    interaction = frame.trade_direction.str.replace("_fade", "", regex=False) + "_" + frame.session
    return [("combined", pd.Series("ALL", index=frame.index)),
            ("year", frame.year.astype(str)),
            ("trade_direction", frame.trade_direction),
            ("session", frame.session),
            ("direction_session", interaction)]


def metric_row(policy_id: str, group: pd.DataFrame, baseline: bool) -> dict:
    if baseline:
        pnl = group.policy_a_net_pnl_usd
        executed = group
        stop_mask = group.policy_a_exit_reason.str.contains("stop")
        timeout_mask = group.policy_a_exit_reason == "confirmation_timeout_exit"
    else:
        executed = group[group.approved]
        pnl = executed.new_net_pnl_usd
        stop_mask = executed.new_exit_reason.str.contains("stop")
        timeout_mask = executed.new_exit_reason == "confirmation_timeout_exit"
    total = float(pnl.sum())
    return {"policy_id": policy_id, "candidate_trades": len(group),
        "approved_trades": len(executed), "skipped_trades": 0 if baseline else len(group) - len(executed),
        "total_net_pnl_usd": total,
        "mean_net_pnl_usd": float(pnl.mean()) if len(pnl) else np.nan,
        "mean_net_pnl_per_candidate_usd": total / len(group) if len(group) else np.nan,
        "profit_factor": profit_factor(pnl),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "stop_count": int(stop_mask.sum()), "stop_rate": float(stop_mask.mean()) if len(executed) else np.nan,
        "timeout_count": int(timeout_mask.sum()),
        "timeout_rate": float(timeout_mask.mean()) if len(executed) else np.nan,
        "average_winner_usd": float(pnl[pnl > 0].mean()) if (pnl > 0).any() else np.nan,
        "average_loser_usd": float(pnl[pnl < 0].mean()) if (pnl < 0).any() else np.nan,
        "max_trade_sequence_drawdown_usd": max_trade_sequence_drawdown(
            group.policy_a_net_pnl_usd if baseline else group.new_net_pnl_usd)}


def summarize(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = diffs[diffs.policy_id == "PR10"].sort_values("original_entry_fill_ts")
    for split_type, labels in split_specs(base):
        for split_value, group in base.assign(_split=labels).groupby("_split", sort=False):
            rows.append({"split_type": split_type, "split_value": str(split_value),
                         **metric_row("BASELINE_POLICY_A", group, True)})
    for policy_id, policy in diffs.groupby("policy_id", sort=False):
        policy = policy.sort_values("original_entry_fill_ts")
        for split_type, labels in split_specs(policy):
            for split_value, group in policy.assign(_split=labels).groupby("_split", sort=False):
                rows.append({"split_type": split_type, "split_value": str(split_value),
                             **metric_row(policy_id, group, False)})
    return pd.DataFrame(rows)


def class_masks(group: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    skipped = ~group.approved
    original = group.original_outcome_group
    return [
        ("skipped_original_stop_before_losses", skipped & (original == "stop_before_aligned_flip")),
        ("skipped_original_planned_winners", skipped & (original == "opposite_flip_exit_winner")),
        ("skipped_original_planned_losers", skipped & (original == "opposite_flip_exit_loser")),
        ("skipped_original_stop_after_trades", skipped & (original == "stop_after_aligned_flip")),
        ("aligning_flip_before_delayed_entry", group.skip_reason.isin(
            ["regime_ended_by_confirmation", "aligning_flip_before_delayed_entry"])),
        ("delayed_entry_slippage_vs_original_entry", group.approved),
        ("approved_delay_improved_fill", group.approved & group.fill_improved),
        ("approved_delay_worsened_fill", group.approved & group.fill_worsened),
        ("approved_delay_unchanged_fill", group.approved & group.fill_unchanged),
        ("approved_later_timed_out", group.approved & (group.new_exit_reason == "confirmation_timeout_exit")),
        ("approved_stopped_before_alignment", group.approved & (group.new_exit_reason == "preflip_policy_stop")),
        ("approved_reached_alignment", group.approved & group.reached_aligning_flip),
    ]


def trade_accounting(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy_id, group in diffs.groupby("policy_id", sort=False):
        for class_name, mask in class_masks(group):
            selected = group[mask]
            change = selected.net_pnl_change_vs_policy_a_usd
            rows.append({"policy_id": policy_id, "accounting_class": class_name,
                "trade_count": len(selected),
                "baseline_policy_a_total_net_pnl_usd": float(selected.policy_a_net_pnl_usd.sum()),
                "delayed_policy_total_net_pnl_usd": float(selected.new_net_pnl_usd.sum()),
                "net_change_usd": float(change.sum()),
                "average_change_per_trade_usd": float(change.mean()) if len(selected) else np.nan,
                "mean_directional_fill_change_points": float(
                    selected.delayed_entry_directional_fill_change_points.mean()) if selected.approved.any() else np.nan})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "config": sha256_file(CONFIG_PATH),
            "freeze": sha256_file(FREEZE_PATH), "audit": sha256_file(PRE_AUDIT),
            "authorization": sha256_file(PRE_AUTH), "raw_2025": sha256_file(RAW_1S[2025]),
            "trades_2025": sha256_file(trade_path(2025)),
            "policy_a_diffs": sha256_file(ISOLATION_DIFFS)}


def require_2025_seal() -> None:
    path = WORK / "reconciliation_2025.json"
    if not path.exists():
        raise RuntimeError("2026 is sealed until 2025 completes")
    seal = json.loads(path.read_text(encoding="utf-8"))
    if seal.get("blocking_errors") != 0 or seal.get("dependency_hashes_2025") != dependency_hashes_2025():
        raise RuntimeError("2025 predecessor seal mismatch")
    if sha256_file(WORK / "price_response_trade_diffs_2025.parquet") != seal.get("diffs_sha256"):
        raise RuntimeError("2025 diff artifact changed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=(2025, 2026), required=True)
    args = parser.parse_args()
    require_authorization()
    config = validate_freeze()
    if args.year == 2026:
        require_2025_seal()
    diffs = build_year(args.year, config)
    expected = (3246 if args.year == 2025 else 1137) * 2
    if len(diffs) != expected or diffs[["policy_id", "trade_id"]].duplicated().any():
        raise RuntimeError("delayed replay cardinality failure")
    year_path = WORK / f"price_response_trade_diffs_{args.year}.parquet"
    diffs.to_parquet(year_path, index=False)
    seal = {"year": args.year, "blocking_errors": 0, "policy_row_count": len(diffs),
            "dependency_hashes_2025": dependency_hashes_2025(),
            "diffs_sha256": sha256_file(year_path)}
    (WORK / f"reconciliation_{args.year}.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    if args.year == 2026:
        combined = pd.concat([pd.read_parquet(WORK / "price_response_trade_diffs_2025.parquet"),
                              diffs], ignore_index=True)
        outputs = {"price_response_trade_diffs.parquet": combined,
                   "price_response_policy_results.parquet": summarize(combined),
                   "price_response_trade_accounting.parquet": trade_accounting(combined)}
        for filename, frame in outputs.items():
            frame.to_parquet(RESULTS / filename, index=False)
        manifest = {"status": "OUTPUTS_COMPLETE_PENDING_REPORT_AND_COMPLETION_AUDIT",
            "candidate_count": 4383, "policy_count": 2, "policy_row_count": len(combined),
            "runner_sha256": script_sha256(), "config_sha256": sha256_file(CONFIG_PATH),
            "freeze_sha256": sha256_file(FREEZE_PATH),
            "output_sha256": {filename: sha256_file(RESULTS / filename) for filename in outputs}}
        (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(diffs):,} fixed delayed-entry rows")


if __name__ == "__main__":
    main()
