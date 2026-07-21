"""Run the single frozen post-flip protection policy as a paired OHLC replay."""
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
FREEZE_PATH = STUDY / "stage2_policy_freeze.json"
PRE_EXEC_AUDIT = AUDIT / "stage2_pre_execution_audit.md"
PRE_EXEC_AUTH = AUDIT / "stage2_pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
NS = 1_000_000_000
MULTIPLIER = 20.0
COST = 10.0

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402

for p in (RESULTS, WORK, AUDIT):
    p.mkdir(parents=True, exist_ok=True)


def trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def require_authorization() -> None:
    if not PRE_EXEC_AUDIT.exists() or not PRE_EXEC_AUTH.exists():
        raise RuntimeError("missing Stage 2 audit authorization")
    text = PRE_EXEC_AUDIT.read_text(encoding="utf-8")
    clean = (re.search(r"^\*\*Status:\*\*\s+\*\*PASS(?:\s|\*|-|\u2014)", text, re.MULTILINE)
             and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                           text, re.MULTILINE))
    if not clean:
        raise RuntimeError("Stage 2 audit is not an exact clean PASS")
    auth = json.loads(PRE_EXEC_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_EXEC_AUDIT)}
    if any(auth.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Stage 2 audit authorization is stale")


def validate_freeze() -> dict:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_AFTER_STAGE1_BEFORE_POLICY_SIMULATION":
        raise RuntimeError("Stage 2 policy is not frozen")
    if freeze.get("preflip_policy_test") is not None:
        raise RuntimeError("closed preflip branch was re-opened")
    expected = freeze["stage1_sha256"]
    current = {
        "manifest": sha256_file(RESULTS / "stage1_manifest.json"),
        "pre_flip_mae": sha256_file(RESULTS / "pre_flip_mae_geometry.parquet"),
        "pre_stop_mfe": sha256_file(RESULTS / "pre_stop_mfe_geometry.parquet"),
        "post_flip_giveback": sha256_file(RESULTS / "post_flip_giveback_geometry.parquet"),
        "completion_audit": sha256_file(AUDIT / "stage1_completion_audit.md"),
    }
    if current != expected:
        raise RuntimeError("Stage 1/freeze hash mismatch")
    stage2_current = {
        "2025_raw": sha256_file(RAW_1S[2025]), "2025_trades": sha256_file(trade_path(2025)),
        "2026_raw": sha256_file(RAW_1S[2026]), "2026_trades": sha256_file(trade_path(2026)),
        "repair_runner": sha256_file(REPAIR / "CODEX_5_X_run_established_fade.py"),
        "repair_common": sha256_file(REPAIR / "CODEX_5_X_common.py"),
    }
    if stage2_current != freeze["stage2_input_sha256"]:
        raise RuntimeError("Stage 2 frozen input/dependency hash mismatch")
    rule = freeze["postflip_policy_test"]
    if rule["arm_postflip_entry_anchored_mfe_atr"] != 1.0 or rule["retained_profit_floor_atr"] != 0.25:
        raise RuntimeError("unexpected Stage 2 rule")
    return freeze


def original_group(t: pd.Series) -> str:
    if t.exit_reason == "opposite_flip_against_countertrade":
        return "opposite_flip_exit_winner" if t.net_pnl_usd > 0 else "opposite_flip_exit_loser"
    return str(t.exit_reason)


def favorable_points(direction: int, entry: float, high: float, low: float) -> float:
    return max(high - entry, 0.0) if direction == 1 else max(entry - low, 0.0)


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def fill_at_level(direction: int, level: float, open_px: float) -> float:
    gap = open_px <= level if direction == 1 else open_px >= level
    return open_px if gap else level


def records_frame(records: list[dict], optional_ns: tuple[str, ...] = ()) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in optional_ns:
        frame[column] = pd.array([row.get(column) for row in records], dtype="Int64")
    return frame


def simulate_from_align(t: pd.Series, raw: pd.DataFrame,
                        rule: dict | None) -> dict:
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    entry = float(t.entry_fill_open)
    direction = int(t.entry_direction)
    atr = float(t.atr_at_checkpoint)
    stop = float(t.stop_px)
    align_i = int(np.searchsorted(ts, int(t.confirm_flip_ns), side="left"))
    end_decision = int(t.scheduled_exit_decision_ts)
    end_i = int(np.searchsorted(ts, end_decision, side="left"))
    if align_i >= len(ts) or int(ts[align_i]) >= end_decision:
        raise RuntimeError("invalid post-flip replay interval")
    arm_level = None if rule is None else float(rule["arm_postflip_entry_anchored_mfe_atr"]) * atr
    floor = None if rule is None else entry + direction * float(rule["retained_profit_floor_atr"]) * atr
    armed = False
    active_from_i: int | None = None
    arm_ts: int | None = None
    peak_pts = 0.0
    exit_ts = None
    exit_px = np.nan
    reason = None
    for i in range(align_i, min(end_i, len(ts))):
        active = armed and active_from_i is not None and i >= active_from_i
        if active and touched_stop(direction, float(floor), highs[i], lows[i]):
            exit_ts, exit_px = int(ts[i]), fill_at_level(direction, float(floor), opens[i])
            reason = "postflip_retained_profit_floor"
            break
        # On the arm-reaching bar the original stop is loss-first; after the
        # floor activates it dominates the lower original stop.
        if touched_stop(direction, stop, highs[i], lows[i]):
            exit_ts, exit_px = int(ts[i]), fill_at_level(direction, stop, opens[i])
            reason = "original_stop_after_aligned_flip"
            break
        peak_pts = max(peak_pts, favorable_points(direction, entry, highs[i], lows[i]))
        if rule is not None and not armed and peak_pts >= float(arm_level):
            armed, active_from_i, arm_ts = True, i + 1, int(ts[i] + NS)
    if exit_ts is None:
        exit_ts = int(t.exit_fill_ts)
        exit_px = float(t.exit_fill_px)
        reason = "original_opposing_flip_exit"
        peak_pts = max(peak_pts, max(direction * (exit_px - entry), 0.0))
    gross_pts = direction * (exit_px - entry)
    return {"new_exit_fill_ts": exit_ts, "new_exit_fill_px": exit_px,
            "new_exit_reason": reason, "armed": armed, "arm_available_ts": arm_ts,
            "policy_postflip_peak_mfe_atr": peak_pts / atr,
            "new_gross_pnl_pts": gross_pts, "new_gross_pnl_usd": gross_pts * MULTIPLIER,
            "new_net_pnl_usd": gross_pts * MULTIPLIER - COST}


def build_diffs(year: int, freeze: dict) -> pd.DataFrame:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    trades = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
    trades["trade_id"] = [f"{year}_{i:05d}" for i in range(len(trades))]
    rule = freeze["postflip_policy_test"]
    rows = []
    for t in trades.itertuples(index=False):
        s = pd.Series(t._asdict())
        group = original_group(s)
        if group == "stop_before_aligned_flip":
            baseline = policy = {"new_exit_fill_ts": int(t.exit_fill_ts),
                "new_exit_fill_px": float(t.exit_fill_px), "new_exit_reason": "unchanged_stop_before_flip",
                "armed": False, "arm_available_ts": None,
                "policy_postflip_peak_mfe_atr": 0.0,
                "new_gross_pnl_pts": float(t.gross_pnl_pts),
                "new_gross_pnl_usd": float(t.gross_pnl_usd), "new_net_pnl_usd": float(t.net_pnl_usd)}
        else:
            baseline = simulate_from_align(s, raw, None)
            if (baseline["new_exit_fill_ts"] != int(t.exit_fill_ts)
                    or not np.isclose(baseline["new_exit_fill_px"], float(t.exit_fill_px), rtol=0, atol=1e-12)
                    or not np.isclose(baseline["new_net_pnl_usd"], float(t.net_pnl_usd), rtol=0, atol=1e-8)):
                raise RuntimeError(f"original baseline replay mismatch: {t.trade_id}")
            policy = simulate_from_align(s, raw, rule)
        original_peak = baseline["policy_postflip_peak_mfe_atr"]
        delta = policy["new_net_pnl_usd"] - float(t.net_pnl_usd)
        rows.append({"policy_id": rule["policy_id"], "trade_id": t.trade_id, "year": year,
            "original_outcome_group": group,
            "trade_direction": "long_fade" if int(t.entry_direction) == 1 else "short_fade",
            "session": t.session, "entry_fill_ts": int(t.entry_fill_ts),
            "original_exit_fill_ts": int(t.exit_fill_ts), "original_exit_reason": t.exit_reason,
            "original_net_pnl_usd": float(t.net_pnl_usd),
            "original_postflip_peak_mfe_atr": original_peak,
            **policy, "net_pnl_change_usd": delta,
            "planned_loser_converted": group == "opposite_flip_exit_loser" and policy["new_net_pnl_usd"] > 0,
            "stop_after_loss_reduced": group == "stop_after_aligned_flip" and delta > 0,
            "planned_winner_clipped": group == "opposite_flip_exit_winner" and delta < -1e-9,
            "planned_winner_lost": group == "opposite_flip_exit_winner" and policy["new_net_pnl_usd"] <= 0,
            "runner_mfe_lost_atr": max(original_peak - policy["policy_postflip_peak_mfe_atr"], 0.0)})
    frame = records_frame(rows, ("arm_available_ts",))
    for column in ("entry_fill_ts", "original_exit_fill_ts", "new_exit_fill_ts"):
        if not pd.api.types.is_integer_dtype(frame[column].dtype):
            raise RuntimeError(f"timestamp dtype is not integer: {column}")
    return frame


def summarize(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    splits = [("overall", pd.Series("ALL", index=diffs.index)),
              ("year", diffs.year.astype(str)),
              ("trade_direction", diffs.trade_direction), ("session", diffs.session)]
    for split_type, labels in splits:
        frame = diffs.assign(_split=labels)
        for value, group in frame.groupby("_split"):
            for version, pnl_col in (("baseline", "original_net_pnl_usd"),
                                     ("postflip_protection", "new_net_pnl_usd")):
                pnl = group[pnl_col]
                wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
                rows.append({"policy_id": "BASELINE_1P5" if version == "baseline" else group.policy_id.iloc[0],
                    "version": version, "split_type": split_type, "split_value": value,
                    "trade_count": len(group), "mean_net_pnl_usd": pnl.mean(),
                    "total_net_pnl_usd": pnl.sum(), "win_rate": (pnl > 0).mean(),
                    "profit_factor": wins / losses if losses > 0 else np.nan,
                    "planned_losers_converted": int(group.planned_loser_converted.sum()) if version != "baseline" else 0,
                    "stop_after_losses_reduced": int(group.stop_after_loss_reduced.sum()) if version != "baseline" else 0,
                    "planned_winners_clipped": int(group.planned_winner_clipped.sum()) if version != "baseline" else 0,
                    "planned_winners_lost": int(group.planned_winner_lost.sum()) if version != "baseline" else 0,
                    "runner_mfe_lost_atr_mean": group.runner_mfe_lost_atr.mean() if version != "baseline" else 0.0})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "freeze": sha256_file(FREEZE_PATH),
            "raw_2025": sha256_file(RAW_1S[2025]), "trades_2025": sha256_file(trade_path(2025)),
            "stage1_manifest": sha256_file(RESULTS / "stage1_manifest.json"),
            "stage2_audit": sha256_file(PRE_EXEC_AUDIT), "stage2_auth": sha256_file(PRE_EXEC_AUTH)}


def require_2025_seal() -> None:
    rec_path = WORK / "stage2_reconciliation_2025.json"
    if not rec_path.exists():
        raise RuntimeError("2026 sealed until 2025 Stage 2 completes")
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec.get("blocking_errors") != 0 or rec.get("dependency_hashes_2025") != dependency_hashes_2025():
        raise RuntimeError("2026 Stage 2 predecessor seal mismatch")
    if sha256_file(WORK / "policy_test_trade_diffs_2025.parquet") != rec["diffs_sha256"]:
        raise RuntimeError("2025 Stage 2 diff hash mismatch")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=(2025, 2026))
    args = ap.parse_args()
    require_authorization()
    freeze = validate_freeze()
    if args.year == 2026:
        require_2025_seal()
    diffs = build_diffs(args.year, freeze)
    if len(diffs) == 0 or diffs.trade_id.duplicated().any():
        raise RuntimeError("Stage 2 diff cardinality failure")
    year_path = WORK / f"policy_test_trade_diffs_{args.year}.parquet"
    diffs.to_parquet(year_path, index=False)
    rec = {"year": args.year, "blocking_errors": 0, "trade_count": len(diffs),
           "dependency_hashes_2025": dependency_hashes_2025(), "diffs_sha256": sha256_file(year_path)}
    (WORK / f"stage2_reconciliation_{args.year}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    if args.year == 2026:
        combined = pd.concat([pd.read_parquet(WORK / "policy_test_trade_diffs_2025.parquet"), diffs],
                             ignore_index=True)
        summary = summarize(combined)
        combined.to_parquet(RESULTS / "policy_test_trade_diffs.parquet", index=False)
        summary.to_parquet(RESULTS / "policy_test_results.parquet", index=False)
        manifest = {"status": "STAGE2_COMPLETE", "policy_count": 1, "trade_count": len(combined),
                    "runner_sha256": script_sha256(), "freeze_sha256": sha256_file(FREEZE_PATH),
                    "output_sha256": {name: sha256_file(RESULTS / name) for name in
                        ("policy_test_trade_diffs.parquet", "policy_test_results.parquet")}}
        (RESULTS / "stage2_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(diffs):,} paired trades")


if __name__ == "__main__":
    main()
