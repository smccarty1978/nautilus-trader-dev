"""Run fixed S/T/A confirmation-clock isolation policies on repaired W4 entries."""
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
CONFIG_PATH, FREEZE_PATH = STUDY / "config.json", STUDY / "policy_freeze.json"
PRE_AUDIT, PRE_AUTH = AUDIT / "pre_execution_audit.md", AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
PRIOR = ROOT / "studies" / "codex_5_w4_fade_confirmation_clock"
NS, TIMEOUT_NS = 1_000_000_000, 300_000_000_000
MULTIPLIER, COST = 20.0, 10.0
INTERACTION_TOLERANCE_FRACTION = 0.05

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
             and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$", text, re.MULTILINE))
    if not clean:
        raise RuntimeError("pre-execution audit is not a clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH), "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(key) != value for key, value in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def validate_freeze() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_ANY_ISOLATION_REPLAY":
        raise RuntimeError("freeze is inactive")
    ids = [p["policy_id"] for p in config["policies"]]
    if ids != freeze["policy_ids"] or len(ids) != 3:
        raise RuntimeError("unexpected isolation policy set")
    if (config.get("interaction_additive_tolerance_fraction") != INTERACTION_TOLERANCE_FRACTION
            or freeze.get("interaction_interpretation", {}).get("additive_tolerance_fraction")
            != INTERACTION_TOLERANCE_FRACTION):
        raise RuntimeError("unexpected interaction interpretation tolerance")
    current = {"2025_raw": sha256_file(RAW_1S[2025]), "2026_raw": sha256_file(RAW_1S[2026]),
        "2025_trades": sha256_file(trade_path(2025)), "2026_trades": sha256_file(trade_path(2026)),
        "repair_runner": sha256_file(REPAIR / "CODEX_5_X_run_established_fade.py"),
        "repair_common": sha256_file(REPAIR / "CODEX_5_X_common.py"),
        "prior_confirmation_runner": sha256_file(PRIOR / "run_study.py"),
        "prior_completion_audit": sha256_file(PRIOR / "audit" / "completion_audit.md")}
    if current != freeze["input_sha256"]:
        raise RuntimeError("frozen dependency mismatch")
    return config


def original_group(t: pd.Series) -> str:
    if t.exit_reason == "opposite_flip_against_countertrade":
        return "opposite_flip_exit_winner" if t.net_pnl_usd > 0 else "opposite_flip_exit_loser"
    return str(t.exit_reason)


def planned_loser_avoided(group: str, original_net: float, new_net: float) -> bool:
    return group == "opposite_flip_exit_loser" and original_net < 0 and new_net >= 0


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def stop_fill(direction: int, stop: float, open_px: float) -> float:
    gap = open_px <= stop if direction == 1 else open_px >= stop
    return open_px if gap else stop


def simulate(t: pd.Series, raw: pd.DataFrame, policy: dict | None) -> dict:
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[column].to_numpy(float) for column in ("open", "high", "low"))
    entry_ts, entry = int(t.entry_fill_ts), float(t.entry_fill_open)
    direction, atr = int(t.entry_direction), float(t.atr_at_checkpoint)
    align_ts, scheduled_decision = int(t.confirm_flip_ns), int(t.scheduled_exit_decision_ts)
    timeout_ts = entry_ts + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled_decision, side="left"))
    if start >= len(ts) or int(ts[start]) != entry_ts:
        raise RuntimeError("entry is not an exact raw open")
    if scheduled_i >= len(ts):
        raise RuntimeError("scheduled exit has no next raw open")
    scheduled_fill_ts = int(ts[scheduled_i])
    if str(t.exit_reason) == "opposite_flip_against_countertrade":
        if scheduled_fill_ts != int(t.exit_fill_ts) or not np.isclose(opens[scheduled_i], float(t.exit_fill_px), rtol=0, atol=1e-12):
            raise RuntimeError("stored planned fill differs from next raw open")

    preflip_atr = 1.5 if policy is None else float(policy["preflip_stop_atr"])
    timeout_enabled = False if policy is None else bool(policy["timeout_enabled"])
    preflip_stop = entry - direction * preflip_atr * atr
    original_stop = entry - direction * 1.5 * atr
    aligned, timeout_pending = False, False
    exit_ts, exit_px, reason = None, np.nan, None
    for i in range(start, scheduled_i + 1):
        now = int(ts[i])
        # A flip can occur during a raw-data gap. No-timeout paths always
        # recognize it before the first later open; timeout paths do so only
        # when it occurred within the confirmation window. A late flip must
        # not cancel a timeout decision already made at 300 seconds.
        if (not aligned and now >= align_ts
                and (not timeout_enabled or align_ts <= timeout_ts)):
            aligned = True
        if timeout_pending and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if timeout_enabled and not aligned and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if now >= scheduled_fill_ts:
            exit_ts, exit_px, reason = now, opens[i], "original_opposing_flip_exit"
            break
        if not aligned and now >= align_ts:
            aligned = True
        if timeout_enabled and now == timeout_ts and not aligned:
            timeout_pending = True
        active_stop = original_stop if aligned else preflip_stop
        stop_reason = "original_stop_after_aligned_flip" if aligned else "preflip_policy_stop"
        if touched_stop(direction, active_stop, highs[i], lows[i]):
            exit_ts, exit_px, reason = now, stop_fill(direction, active_stop, opens[i]), stop_reason
            break
    if exit_ts is None:
        raise RuntimeError("replay ended without exit")
    points = direction * (float(exit_px) - entry)
    return {"new_exit_fill_ts": int(exit_ts), "new_exit_fill_px": float(exit_px),
            "new_exit_reason": reason, "reached_aligning_flip": bool(aligned),
            "timeout_ts": timeout_ts, "new_gross_pnl_pts": points,
            "new_gross_pnl_usd": points * MULTIPLIER, "new_net_pnl_usd": points * MULTIPLIER - COST}


def build_year(year: int, config: dict) -> pd.DataFrame:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    trades = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
    rows = []
    for index, t in trades.iterrows():
        trade_id = f"{year}_{index:05d}"
        baseline = simulate(t, raw, None)
        if (baseline["new_exit_fill_ts"] != int(t.exit_fill_ts)
                or not np.isclose(baseline["new_exit_fill_px"], float(t.exit_fill_px), rtol=0, atol=1e-12)
                or not np.isclose(baseline["new_net_pnl_usd"], float(t.net_pnl_usd), rtol=0, atol=1e-8)):
            raise RuntimeError(f"baseline mismatch: {trade_id}")
        group = original_group(t)
        baseline_reached = group != "stop_before_aligned_flip"
        for policy in config["policies"]:
            result = simulate(t, raw, policy)
            delta = result["new_net_pnl_usd"] - float(t.net_pnl_usd)
            unchanged = (result["new_exit_fill_ts"] == int(t.exit_fill_ts)
                         and np.isclose(result["new_exit_fill_px"], float(t.exit_fill_px), rtol=0, atol=1e-12))
            tighter = (float(policy["preflip_stop_atr"]) == 1.25
                       and result["new_exit_reason"] == "preflip_policy_stop" and not unchanged)
            timeout = result["new_exit_reason"] == "confirmation_timeout_exit"
            stop_after = group == "stop_after_aligned_flip"
            primary = "unchanged" if unchanged else ("exited_by_5m_timeout" if timeout else
                ("stopped_earlier_by_1p25" if tighter else "other_changed"))
            rows.append({"policy_id": policy["policy_id"], "trade_id": trade_id, "year": year,
                "trade_direction": "long_fade" if int(t.entry_direction) == 1 else "short_fade",
                "session": str(t.session), "entry_fill_ts": int(t.entry_fill_ts),
                "original_outcome_group": group, "baseline_reached_aligning_flip": baseline_reached,
                "original_exit_fill_ts": int(t.exit_fill_ts), "original_exit_reason": str(t.exit_reason),
                "original_net_pnl_usd": float(t.net_pnl_usd), **result, "net_pnl_change_usd": delta,
                "primary_change_class": primary, "class_unchanged": unchanged,
                "class_stopped_earlier_by_1p25": tighter, "class_exited_by_5m_timeout": timeout,
                "class_reached_flip_lost": baseline_reached and not result["reached_aligning_flip"],
                "class_stop_before_loss_reduced": group == "stop_before_aligned_flip" and delta > 1e-9,
                "class_planned_winner_clipped": group == "opposite_flip_exit_winner" and delta < -1e-9,
                "class_planned_loser_improved": group == "opposite_flip_exit_loser" and delta > 1e-9,
                "class_planned_loser_avoided": planned_loser_avoided(
                    group, float(t.net_pnl_usd), result["new_net_pnl_usd"]),
                "class_stop_after_improved": stop_after and delta > 1e-9,
                "class_stop_after_worsened": stop_after and delta < -1e-9})
    frame = pd.DataFrame(rows)
    for column in ("entry_fill_ts", "original_exit_fill_ts", "new_exit_fill_ts", "timeout_ts"):
        if not pd.api.types.is_integer_dtype(frame[column].dtype):
            raise RuntimeError(f"timestamp dtype is not integer: {column}")
    return frame


def profit_factor(pnl: pd.Series) -> float:
    losses = -pnl[pnl < 0].sum()
    return pnl[pnl > 0].sum() / losses if losses > 0 else np.nan


def max_trade_sequence_drawdown(pnl: pd.Series) -> float:
    equity = pnl.cumsum().to_numpy(float)
    equity = np.concatenate(([0.0], equity))
    peaks = np.maximum.accumulate(equity)
    return float(np.max(peaks - equity))


def metrics_row(policy_id: str, version: str, split_type: str, split_value: str,
                group: pd.DataFrame, pnl_column: str) -> dict:
    pnl = group[pnl_column]
    stop_reasons = group.original_exit_reason.str.startswith("stop_") if version == "baseline" else group.new_exit_reason.str.contains("stop")
    return {"policy_id": policy_id, "version": version, "split_type": split_type,
        "split_value": split_value, "trade_count": len(group), "mean_net_pnl_usd": pnl.mean(),
        "total_net_pnl_usd": pnl.sum(), "profit_factor": profit_factor(pnl),
        "win_rate": (pnl > 0).mean(), "stop_rate": stop_reasons.mean(),
        "timeout_exit_count": 0 if version == "baseline" else int((group.new_exit_reason == "confirmation_timeout_exit").sum()),
        "reached_aligning_flip_count": int(group.baseline_reached_aligning_flip.sum()) if version == "baseline" else int(group.reached_aligning_flip.sum()),
        "reached_flip_trades_lost": 0 if version == "baseline" else int(group.class_reached_flip_lost.sum()),
        "stop_before_losses_reduced": 0 if version == "baseline" else int(group.class_stop_before_loss_reduced.sum()),
        "planned_winners_clipped": 0 if version == "baseline" else int(group.class_planned_winner_clipped.sum()),
        "planned_losers_avoided": 0 if version == "baseline" else int(group.class_planned_loser_avoided.sum()),
        "stop_after_improved": 0 if version == "baseline" else int(group.class_stop_after_improved.sum()),
        "stop_after_worsened": 0 if version == "baseline" else int(group.class_stop_after_worsened.sum()),
        "stop_after_net_change_usd": 0.0 if version == "baseline" else group.loc[group.original_outcome_group == "stop_after_aligned_flip", "net_pnl_change_usd"].sum(),
        "average_winner_usd": pnl[pnl > 0].mean(), "average_loser_usd": pnl[pnl < 0].mean(),
        "max_trade_sequence_drawdown_usd": max_trade_sequence_drawdown(pnl)}


CLASS_COLUMNS = ["class_unchanged", "class_stopped_earlier_by_1p25", "class_exited_by_5m_timeout",
    "class_reached_flip_lost", "class_stop_before_loss_reduced", "class_planned_winner_clipped",
    "class_planned_loser_improved", "class_planned_loser_avoided", "class_stop_after_improved",
    "class_stop_after_worsened"]


def summarize(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    split_specs = [("overall", pd.Series("ALL", index=diffs.index)), ("year", diffs.year.astype(str)),
                   ("trade_direction", diffs.trade_direction), ("session", diffs.session)]
    for split_type, labels in split_specs:
        frame = diffs.assign(_split=labels)
        for split_value, split in frame.groupby("_split", sort=False):
            baseline = split.drop_duplicates("trade_id").sort_values("entry_fill_ts")
            rows.append(metrics_row("BASELINE_1P5", "baseline", split_type, str(split_value), baseline,
                                    "original_net_pnl_usd"))
            for policy_id, group in split.groupby("policy_id", sort=False):
                rows.append(metrics_row(policy_id, "policy", split_type, str(split_value),
                                        group.sort_values("entry_fill_ts"), "new_net_pnl_usd"))
    for policy_id, policy in diffs.groupby("policy_id", sort=False):
        for class_column in CLASS_COLUMNS:
            group = policy[policy[class_column]].sort_values("entry_fill_ts")
            rows.append({"policy_id": policy_id, "version": "policy_class",
                "split_type": "change_class", "split_value": class_column.removeprefix("class_"),
                "trade_count": len(group), "baseline_total_net_pnl_usd": group.original_net_pnl_usd.sum(),
                "total_net_pnl_usd": group.new_net_pnl_usd.sum(),
                "net_pnl_change_usd": group.net_pnl_change_usd.sum(),
                "average_change_per_trade_usd": group.net_pnl_change_usd.mean() if len(group) else np.nan})
    return pd.DataFrame(rows)


def attribution(diffs: pd.DataFrame) -> pd.DataFrame:
    ids = {"stop_only": "POLICY_S_STOP_ONLY_1P25", "timeout_only": "POLICY_T_TIMEOUT_ONLY_300S",
           "combined": "POLICY_A_COMBINED_1P25_300S"}
    changes = {}
    for name, policy_id in ids.items():
        policy = diffs[diffs.policy_id == policy_id]
        changes[name] = {str(year): group.net_pnl_change_usd.sum() for year, group in policy.groupby("year")}
        changes[name]["combined"] = policy.net_pnl_change_usd.sum()
    interaction = {sample: changes["combined"][sample] - changes["stop_only"][sample] - changes["timeout_only"][sample]
                   for sample in ("2025", "2026", "combined")}
    rows = []
    for component, label in (("stop_only", "1.25 stop only"), ("timeout_only", "5-minute timeout only"),
                             ("combined", "combined 1.25 + timeout")):
        rows.append({"component": label, "net_change_2025_usd": changes[component]["2025"],
            "net_change_2026_usd": changes[component]["2026"],
            "net_change_combined_usd": changes[component]["combined"],
            "interpretation": "direct paired change versus baseline"})
    tolerance = INTERACTION_TOLERANCE_FRACTION * min(abs(changes["stop_only"]["combined"]),
                                                     abs(changes["timeout_only"]["combined"]))
    if abs(interaction["combined"]) <= tolerance:
        sign = "approximately zero; additive"
    else:
        sign = "positive synergy" if interaction["combined"] > 0 else "negative/conflictive interaction"
    rows.append({"component": "interaction effect", "net_change_2025_usd": interaction["2025"],
        "net_change_2026_usd": interaction["2026"], "net_change_combined_usd": interaction["combined"],
        "interpretation": sign})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "config": sha256_file(CONFIG_PATH), "freeze": sha256_file(FREEZE_PATH),
            "raw_2025": sha256_file(RAW_1S[2025]), "trades_2025": sha256_file(trade_path(2025)),
            "audit": sha256_file(PRE_AUDIT), "authorization": sha256_file(PRE_AUTH)}


def require_2025_seal() -> None:
    path = WORK / "reconciliation_2025.json"
    if not path.exists():
        raise RuntimeError("2026 is sealed until 2025 completes")
    seal = json.loads(path.read_text(encoding="utf-8"))
    if seal.get("blocking_errors") != 0 or seal.get("dependency_hashes_2025") != dependency_hashes_2025():
        raise RuntimeError("2025 predecessor seal mismatch")
    if sha256_file(WORK / "isolation_trade_diffs_2025.parquet") != seal["diffs_sha256"]:
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
    expected = (3246 if args.year == 2025 else 1137) * 3
    if len(diffs) != expected or diffs[["policy_id", "trade_id"]].duplicated().any():
        raise RuntimeError("isolation cardinality failure")
    year_path = WORK / f"isolation_trade_diffs_{args.year}.parquet"
    diffs.to_parquet(year_path, index=False)
    seal = {"year": args.year, "blocking_errors": 0, "policy_row_count": len(diffs),
            "dependency_hashes_2025": dependency_hashes_2025(), "diffs_sha256": sha256_file(year_path)}
    (WORK / f"reconciliation_{args.year}.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    if args.year == 2026:
        combined = pd.concat([pd.read_parquet(WORK / "isolation_trade_diffs_2025.parquet"), diffs], ignore_index=True)
        outputs = {"isolation_trade_diffs.parquet": combined,
                   "isolation_policy_results.parquet": summarize(combined),
                   "isolation_component_attribution.parquet": attribution(combined)}
        for filename, frame in outputs.items():
            frame.to_parquet(RESULTS / filename, index=False)
        manifest = {"status": "OUTPUTS_COMPLETE_PENDING_REPORT_AUDIT", "entry_count": 4383,
            "policy_count": 3, "policy_row_count": len(combined), "runner_sha256": script_sha256(),
            "config_sha256": sha256_file(CONFIG_PATH), "freeze_sha256": sha256_file(FREEZE_PATH),
            "output_sha256": {filename: sha256_file(RESULTS / filename) for filename in outputs}}
        (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(diffs):,} paired isolation rows")


if __name__ == "__main__":
    main()
