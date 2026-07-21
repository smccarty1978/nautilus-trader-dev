"""Run frozen W4 confirmation-clock policies as paired 1-second OHLC replays."""
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
RESULTS = STUDY / "results"
WORK = STUDY / "_work"
AUDIT = STUDY / "audit"
CONFIG_PATH = STUDY / "config.json"
FREEZE_PATH = STUDY / "policy_freeze.json"
PRE_AUDIT = AUDIT / "pre_execution_audit.md"
PRE_AUTH = AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
NS = 1_000_000_000
TIMEOUT_NS = 300 * NS
MULTIPLIER = 20.0
COST = 10.0

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
        raise RuntimeError("pre-execution audit is not an exact clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH),
                "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(key) != value for key, value in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def validate_freeze() -> tuple[dict, dict]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_ANY_CONFIRMATION_CLOCK_SIMULATION":
        raise RuntimeError("policy freeze is not active")
    policy_ids = [p["policy_id"] for p in config["policies"]]
    expected_ids = ["POLICY_A_TIMEOUT_300S_STOP_1P25",
                    "POLICY_B_TIMEOUT_300S_MFE_0P75_STOP_1P25",
                    "POLICY_C_TIMEOUT_300S_STOP_1P00"]
    if policy_ids != expected_ids or config["timeout_seconds"] != 300:
        raise RuntimeError("unexpected policy set")
    current = {
        "2025_raw": sha256_file(RAW_1S[2025]),
        "2026_raw": sha256_file(RAW_1S[2026]),
        "2025_trades": sha256_file(trade_path(2025)),
        "2026_trades": sha256_file(trade_path(2026)),
        "repair_runner": sha256_file(REPAIR / "CODEX_5_X_run_established_fade.py"),
        "repair_common": sha256_file(REPAIR / "CODEX_5_X_common.py"),
    }
    if current != freeze["input_sha256"]:
        raise RuntimeError("frozen input/dependency hash mismatch")
    return config, freeze


def original_group(t: pd.Series) -> str:
    if t.exit_reason == "opposite_flip_against_countertrade":
        return "opposite_flip_exit_winner" if t.net_pnl_usd > 0 else "opposite_flip_exit_loser"
    return str(t.exit_reason)


def favorable_points(direction: int, entry: float, high: float, low: float) -> float:
    return max(high - entry, 0.0) if direction == 1 else max(entry - low, 0.0)


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def fill_at_stop(direction: int, stop: float, open_px: float) -> float:
    through = open_px <= stop if direction == 1 else open_px >= stop
    return open_px if through else stop


def pnl_fields(direction: int, entry: float, exit_px: float) -> dict:
    points = direction * (exit_px - entry)
    return {"new_gross_pnl_pts": points, "new_gross_pnl_usd": points * MULTIPLIER,
            "new_net_pnl_usd": points * MULTIPLIER - COST}


def simulate(t: pd.Series, raw: pd.DataFrame, policy: dict | None) -> dict:
    """Replay one fixed entry. `policy=None` is the exact repaired baseline."""
    ts = raw.index.view(np.int64)
    opens = raw.open.to_numpy(float)
    highs = raw.high.to_numpy(float)
    lows = raw.low.to_numpy(float)
    entry_ts = int(t.entry_fill_ts)
    entry = float(t.entry_fill_open)
    direction = int(t.entry_direction)
    atr = float(t.atr_at_checkpoint)
    align_ts = int(t.confirm_flip_ns)
    scheduled_ts = int(t.scheduled_exit_decision_ts)
    timeout_ts = entry_ts + TIMEOUT_NS
    start_i = int(np.searchsorted(ts, entry_ts, side="left"))
    end_i = int(np.searchsorted(ts, scheduled_ts, side="left"))
    if start_i >= len(ts) or int(ts[start_i]) != entry_ts:
        raise RuntimeError("entry fill does not map to an exact raw open")
    if end_i >= len(ts):
        raise RuntimeError("scheduled exit has no next available raw open")
    scheduled_fill_ts = int(ts[end_i])
    if str(t.exit_reason) == "opposite_flip_against_countertrade":
        if scheduled_fill_ts != int(t.exit_fill_ts):
            raise RuntimeError("stored scheduled fill is not the next available raw open")
        if not np.isclose(opens[end_i], float(t.exit_fill_px), rtol=0, atol=1e-12):
            raise RuntimeError("stored scheduled fill price is not the raw open")

    baseline = policy is None
    preflip_stop_atr = 1.5 if baseline else float(policy["preflip_stop_atr"])
    preflip_stop = entry - direction * preflip_stop_atr * atr
    original_stop = entry - direction * 1.5 * atr
    qualify_atr = None if baseline else policy.get("mfe_qualification_atr")
    protected_stop = None if qualify_atr is None else entry + direction * float(policy["protected_profit_atr"]) * atr
    aligned = False
    timeout_handled = baseline
    timeout_exit_pending = False
    qualified = False
    peak_before_timeout_pts = 0.0
    exit_ts = None
    exit_px = np.nan
    exit_reason = None

    for i in range(start_i, end_i + 1):
        now = int(ts[i])

        # A timeout decision between available bars precedes all events at the
        # first later open. A/C fill immediately there; B changes stop state.
        if not timeout_handled and now > timeout_ts and align_ts > timeout_ts:
            timeout_handled = True
            if qualify_atr is not None and peak_before_timeout_pts >= float(qualify_atr) * atr:
                qualified = True
            else:
                exit_ts, exit_px, exit_reason = now, opens[i], "confirmation_timeout_exit"
                break

        if timeout_exit_pending and now > timeout_ts:
            exit_ts, exit_px, exit_reason = now, opens[i], "confirmation_timeout_exit"
            break

        # Known decision boundaries occur at the open, before this bar's range.
        if now >= scheduled_fill_ts:
            exit_ts, exit_px, exit_reason = now, opens[i], "original_opposing_flip_exit"
            break
        if not aligned and now >= align_ts:
            aligned = True

        # Equality is within the window: align was processed first. Otherwise
        # the timeout decision is made now, before this bar's range.
        if not timeout_handled and now == timeout_ts and not aligned:
            timeout_handled = True
            if qualify_atr is not None and peak_before_timeout_pts >= float(qualify_atr) * atr:
                qualified = True
            else:
                timeout_exit_pending = True

        active_stop = original_stop if aligned else preflip_stop
        stop_reason = "original_stop_after_aligned_flip" if aligned else "preflip_policy_stop"
        if qualified:
            active_stop = float(protected_stop)
            stop_reason = "mfe_protected_stop"
        if touched_stop(direction, active_stop, highs[i], lows[i]):
            exit_ts = now
            exit_px = fill_at_stop(direction, active_stop, opens[i])
            exit_reason = stop_reason
            break

        # Conservative same-bar rule: favorable excursion is recorded only
        # after confirming that the active stop did not touch.
        if now < timeout_ts:
            peak_before_timeout_pts = max(
                peak_before_timeout_pts,
                favorable_points(direction, entry, highs[i], lows[i]),
            )

    if exit_ts is None:
        raise RuntimeError("simulation ended without an exit")
    return {"new_exit_fill_ts": int(exit_ts), "new_exit_fill_px": float(exit_px),
            "new_exit_reason": exit_reason, "timeout_ts": timeout_ts,
            "mfe_at_timeout_atr": peak_before_timeout_pts / atr,
            "mfe_qualified_continuation": bool(qualified),
            **pnl_fields(direction, entry, float(exit_px))}


def path_diagnostic(t: pd.Series, raw: pd.DataFrame, trade_id: str) -> dict:
    ts = raw.index.view(np.int64)
    highs = raw.high.to_numpy(float)
    lows = raw.low.to_numpy(float)
    closes = raw.close.to_numpy(float)
    entry_ts = int(t.entry_fill_ts)
    timeout_ts = entry_ts + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    timeout_i = int(np.searchsorted(ts, timeout_ts, side="left"))
    completed_end = timeout_i
    entry = float(t.entry_fill_open)
    direction = int(t.entry_direction)
    atr = float(t.atr_at_checkpoint)
    peak = 0.0
    for i in range(start, completed_end):
        peak = max(peak, favorable_points(direction, entry, highs[i], lows[i]))
    # A stop timestamp names the containing one-second bar, so a stop on the
    # timeout-labelled bar occurs after the timeout-open decision instant.
    # A scheduled opposing-flip fill at that timestamp occurs at the open.
    exit_at_timeout_after_open = (int(t.exit_fill_ts) == timeout_ts
                                  and str(t.exit_reason).startswith("stop_"))
    alive = int(t.exit_fill_ts) > timeout_ts or exit_at_timeout_after_open
    mark_i = completed_end - 1
    pnl_at_timeout = direction * (closes[mark_i] - entry) / atr if alive and mark_i >= start else np.nan
    group = original_group(t)
    flip_within = int(t.confirm_flip_ns) <= timeout_ts
    return {"trade_id": trade_id, "year": int(t.year), "outcome_group": group,
            "trade_direction": "long_fade" if direction == 1 else "short_fade",
            "session": str(t.session), "entry_fill_ts": entry_ts,
            "timeout_ts": timeout_ts, "aligning_flip_ts": int(t.confirm_flip_ns),
            "time_to_aligning_flip_s": (int(t.confirm_flip_ns) - entry_ts) / NS,
            "flip_within_5m": flip_within, "baseline_alive_at_5m": alive,
            "pnl_at_5m_atr": pnl_at_timeout,
            "mfe_through_5m_atr": peak / atr if alive else np.nan,
            "no_flip_alive_at_5m": alive and not flip_within,
            "mfe_0p75_qualified_at_5m": alive and not flip_within and peak >= 0.75 * atr,
            "baseline_exit_reason": str(t.exit_reason),
            "baseline_net_pnl_usd": float(t.net_pnl_usd)}


def build_year(year: int, config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    trades = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
    diagnostic_rows = []
    diff_rows = []
    for index, row in trades.iterrows():
        trade_id = f"{year}_{index:05d}"
        baseline = simulate(row, raw, None)
        if (baseline["new_exit_fill_ts"] != int(row.exit_fill_ts)
                or not np.isclose(baseline["new_exit_fill_px"], float(row.exit_fill_px), rtol=0, atol=1e-12)
                or not np.isclose(baseline["new_net_pnl_usd"], float(row.net_pnl_usd), rtol=0, atol=1e-8)):
            raise RuntimeError(f"baseline replay mismatch: {trade_id}")
        diagnostic_rows.append(path_diagnostic(row, raw, trade_id))
        group = original_group(row)
        for policy in config["policies"]:
            result = simulate(row, raw, policy)
            delta = result["new_net_pnl_usd"] - float(row.net_pnl_usd)
            timeout_exit = result["new_exit_reason"] == "confirmation_timeout_exit"
            diff_rows.append({"policy_id": policy["policy_id"], "trade_id": trade_id,
                "year": year, "original_outcome_group": group,
                "trade_direction": "long_fade" if int(row.entry_direction) == 1 else "short_fade",
                "session": str(row.session), "entry_fill_ts": int(row.entry_fill_ts),
                "original_exit_fill_ts": int(row.exit_fill_ts),
                "original_exit_reason": str(row.exit_reason),
                "original_net_pnl_usd": float(row.net_pnl_usd), **result,
                "net_pnl_change_usd": delta,
                "timeout_exit_later_flip": timeout_exit and int(row.confirm_flip_ns) > result["timeout_ts"],
                "timeout_exit_baseline_later_reached_flip": timeout_exit and group != "stop_before_aligned_flip",
                "planned_winner_clipped": group == "opposite_flip_exit_winner" and delta < -1e-9,
                "planned_loser_avoided": group == "opposite_flip_exit_loser" and result["new_net_pnl_usd"] >= 0,
                "stop_before_loss_reduced": group == "stop_before_aligned_flip" and delta > 1e-9})
    diagnostics = pd.DataFrame(diagnostic_rows)
    diffs = pd.DataFrame(diff_rows)
    for frame, columns in ((diagnostics, ["entry_fill_ts", "timeout_ts", "aligning_flip_ts"]),
                           (diffs, ["entry_fill_ts", "original_exit_fill_ts", "new_exit_fill_ts", "timeout_ts"])):
        for column in columns:
            if not pd.api.types.is_integer_dtype(frame[column].dtype):
                raise RuntimeError(f"timestamp dtype is not integer: {column}")
    return diagnostics, diffs


def profit_factor(pnl: pd.Series) -> float:
    losses = -pnl[pnl < 0].sum()
    return pnl[pnl > 0].sum() / losses if losses > 0 else np.nan


def policy_summary(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    baseline = diffs.drop_duplicates("trade_id")
    splits = [("overall", pd.Series("ALL", index=diffs.index)),
              ("year", diffs.year.astype(str)),
              ("trade_direction", diffs.trade_direction), ("session", diffs.session)]
    for split_type, labels in splits:
        frame = diffs.assign(_split=labels)
        for split_value, split in frame.groupby("_split"):
            base = split.drop_duplicates("trade_id")
            pnl = base.original_net_pnl_usd
            rows.append({"policy_id": "BASELINE_1P5", "version": "baseline",
                "split_type": split_type, "split_value": split_value, "trade_count": len(base),
                "mean_net_pnl_usd": pnl.mean(), "total_net_pnl_usd": pnl.sum(),
                "profit_factor": profit_factor(pnl), "win_rate": (pnl > 0).mean(),
                "stop_rate": base.original_exit_reason.str.startswith("stop_").mean(),
                "timeout_exit_count": 0, "timeout_exits_later_flip": 0,
                "timeout_exits_baseline_later_reached_flip": 0,
                "mfe_qualified_continuations": 0, "protected_stop_exits": 0,
                "planned_winners_clipped": 0, "planned_losers_avoided": 0,
                "stop_before_losses_reduced": 0})
            for policy_id, group in split.groupby("policy_id"):
                pnl = group.new_net_pnl_usd
                rows.append({"policy_id": policy_id, "version": "policy",
                    "split_type": split_type, "split_value": split_value, "trade_count": len(group),
                    "mean_net_pnl_usd": pnl.mean(), "total_net_pnl_usd": pnl.sum(),
                    "profit_factor": profit_factor(pnl), "win_rate": (pnl > 0).mean(),
                    "stop_rate": group.new_exit_reason.str.contains("stop").mean(),
                    "timeout_exit_count": int((group.new_exit_reason == "confirmation_timeout_exit").sum()),
                    "timeout_exits_later_flip": int(group.timeout_exit_later_flip.sum()),
                    "timeout_exits_baseline_later_reached_flip": int(group.timeout_exit_baseline_later_reached_flip.sum()),
                    "mfe_qualified_continuations": int(group.mfe_qualified_continuation.sum()),
                    "protected_stop_exits": int((group.new_exit_reason == "mfe_protected_stop").sum()),
                    "planned_winners_clipped": int(group.planned_winner_clipped.sum()),
                    "planned_losers_avoided": int(group.planned_loser_avoided.sum()),
                    "stop_before_losses_reduced": int(group.stop_before_loss_reduced.sum())})
    return pd.DataFrame(rows)


def diagnostic_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group_name, group in diagnostics.groupby("outcome_group"):
        alive = group[group.baseline_alive_at_5m]
        no_flip = group[group.no_flip_alive_at_5m]
        rows.append({"summary_type": "outcome_group_5m", "summary_value": group_name,
            "trade_count": len(group), "alive_at_5m_count": len(alive),
            "median_pnl_at_5m_atr": alive.pnl_at_5m_atr.median(),
            "median_mfe_through_5m_atr": alive.mfe_through_5m_atr.median(),
            "no_flip_alive_at_5m_count": len(no_flip),
            "mfe_0p75_qualified_count": int(no_flip.mfe_0p75_qualified_at_5m.sum()),
            "mfe_0p75_qualified_rate": no_flip.mfe_0p75_qualified_at_5m.mean() if len(no_flip) else np.nan,
            "median_time_to_aligning_flip_s": group.time_to_aligning_flip_s.median()})
    winners = diagnostics[diagnostics.outcome_group == "opposite_flip_exit_winner"]
    for dimension in ("year", "trade_direction", "session"):
        for value, group in winners.groupby(dimension):
            rows.append({"summary_type": f"winner_time_to_flip_by_{dimension}",
                "summary_value": str(value), "trade_count": len(group),
                "alive_at_5m_count": int(group.baseline_alive_at_5m.sum()),
                "median_pnl_at_5m_atr": np.nan, "median_mfe_through_5m_atr": np.nan,
                "no_flip_alive_at_5m_count": int(group.no_flip_alive_at_5m.sum()),
                "mfe_0p75_qualified_count": int(group.mfe_0p75_qualified_at_5m.sum()),
                "mfe_0p75_qualified_rate": group.mfe_0p75_qualified_at_5m.mean(),
                "median_time_to_aligning_flip_s": group.time_to_aligning_flip_s.median()})
    qualified = diagnostics[diagnostics.mfe_0p75_qualified_at_5m]
    for outcome, group in qualified.groupby("outcome_group"):
        rows.append({"summary_type": "qualified_baseline_outcome", "summary_value": outcome,
            "trade_count": len(group), "alive_at_5m_count": len(group),
            "median_pnl_at_5m_atr": group.pnl_at_5m_atr.median(),
            "median_mfe_through_5m_atr": group.mfe_through_5m_atr.median(),
            "no_flip_alive_at_5m_count": len(group), "mfe_0p75_qualified_count": len(group),
            "mfe_0p75_qualified_rate": 1.0,
            "median_time_to_aligning_flip_s": group.time_to_aligning_flip_s.median(),
            "baseline_total_net_pnl_usd": group.baseline_net_pnl_usd.sum(),
            "baseline_mean_net_pnl_usd": group.baseline_net_pnl_usd.mean()})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "config": sha256_file(CONFIG_PATH),
            "freeze": sha256_file(FREEZE_PATH), "raw_2025": sha256_file(RAW_1S[2025]),
            "trades_2025": sha256_file(trade_path(2025)), "audit": sha256_file(PRE_AUDIT),
            "authorization": sha256_file(PRE_AUTH)}


def require_2025_seal() -> None:
    seal_path = WORK / "reconciliation_2025.json"
    if not seal_path.exists():
        raise RuntimeError("2026 is sealed until 2025 completes")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("blocking_errors") != 0 or seal.get("dependency_hashes_2025") != dependency_hashes_2025():
        raise RuntimeError("2025 predecessor seal mismatch")
    for key, filename in (("diffs_sha256", "policy_trade_diffs_2025.parquet"),
                          ("diagnostics_sha256", "path_diagnostics_2025.parquet")):
        if sha256_file(WORK / filename) != seal[key]:
            raise RuntimeError(f"2025 predecessor artifact mismatch: {filename}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=(2025, 2026), required=True)
    args = parser.parse_args()
    require_authorization()
    config, _ = validate_freeze()
    if args.year == 2026:
        require_2025_seal()
    diagnostics, diffs = build_year(args.year, config)
    expected_trades = 3246 if args.year == 2025 else 1137
    if len(diagnostics) != expected_trades or len(diffs) != expected_trades * 3:
        raise RuntimeError("yearly output cardinality failure")
    diag_path = WORK / f"path_diagnostics_{args.year}.parquet"
    diff_path = WORK / f"policy_trade_diffs_{args.year}.parquet"
    diagnostics.to_parquet(diag_path, index=False)
    diffs.to_parquet(diff_path, index=False)
    seal = {"year": args.year, "blocking_errors": 0, "trade_count": len(diagnostics),
            "policy_row_count": len(diffs), "dependency_hashes_2025": dependency_hashes_2025(),
            "diagnostics_sha256": sha256_file(diag_path), "diffs_sha256": sha256_file(diff_path)}
    (WORK / f"reconciliation_{args.year}.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    if args.year == 2026:
        combined_diag = pd.concat([pd.read_parquet(WORK / "path_diagnostics_2025.parquet"), diagnostics],
                                  ignore_index=True)
        combined_diffs = pd.concat([pd.read_parquet(WORK / "policy_trade_diffs_2025.parquet"), diffs],
                                   ignore_index=True)
        outputs = {
            "confirmation_clock_path_diagnostics.parquet": combined_diag,
            "confirmation_clock_diagnostic_summary.parquet": diagnostic_summary(combined_diag),
            "confirmation_clock_policy_trade_diffs.parquet": combined_diffs,
            "confirmation_clock_policy_results.parquet": policy_summary(combined_diffs),
        }
        for filename, frame in outputs.items():
            frame.to_parquet(RESULTS / filename, index=False)
        manifest = {"status": "COMPLETE_PENDING_REPORT_AUDIT", "trade_count": len(combined_diag),
                    "policy_count": 3, "policy_row_count": len(combined_diffs),
                    "runner_sha256": script_sha256(), "config_sha256": sha256_file(CONFIG_PATH),
                    "freeze_sha256": sha256_file(FREEZE_PATH),
                    "output_sha256": {filename: sha256_file(RESULTS / filename) for filename in outputs}}
        (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(diagnostics):,} trades, {len(diffs):,} paired policy rows")


if __name__ == "__main__":
    main()
