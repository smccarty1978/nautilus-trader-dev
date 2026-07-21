"""Build retrospective risk-state geometry for frozen W4 fade trades."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
AUDIT = STUDY / "audit"
CONFIG_PATH = STUDY / "config.json"
PRE_EXEC_AUDIT = AUDIT / "stage1_pre_execution_audit.md"
PRE_EXEC_AUTH = AUDIT / "stage1_pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
PATH_STUDY = ROOT / "studies" / "codex_5_w4_countertrade_path_diagnostic"
PATH_RESULTS = PATH_STUDY / "results"
NS = 1_000_000_000

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402

RESULTS.mkdir(parents=True, exist_ok=True)
AUDIT.mkdir(parents=True, exist_ok=True)


def trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def validate_hash_contract(expected: dict, current: dict) -> None:
    if expected != current:
        raise RuntimeError("Stage 1 frozen input hash mismatch")


def validate_inputs(config: dict) -> None:
    current = {
        "path_checkpoints": sha256_file(PATH_RESULTS / "path_checkpoints.parquet"),
        "post_flip_diagnostic": sha256_file(PATH_RESULTS / "post_flip_exit_diagnostic.parquet"),
        "path_manifest": sha256_file(PATH_RESULTS / "run_manifest.json"),
    }
    for year in (2025, 2026):
        current[str(year)] = {"raw": sha256_file(RAW_1S[year]),
                              "trades": sha256_file(trade_path(year))}
    validate_hash_contract(config["input_sha256"], current)


def require_authorization() -> None:
    if not PRE_EXEC_AUDIT.exists() or not PRE_EXEC_AUTH.exists():
        raise RuntimeError("missing Stage 1 audit authorization")
    text = PRE_EXEC_AUDIT.read_text(encoding="utf-8")
    if (re.search(r"^\*\*Status:\*\*\s+\*\*PASS(?:\s|\*|-|\u2014)", text, re.MULTILINE) is None
            or re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                         text, re.MULTILINE) is None):
        raise RuntimeError("Stage 1 audit is not an exact clean PASS")
    auth = json.loads(PRE_EXEC_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH),
                "spec_sha256": sha256_file(STUDY / "SPEC.md"),
                "audit_sha256": sha256_file(PRE_EXEC_AUDIT)}
    if any(auth.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Stage 1 audit authorization is stale")


def label_present(series: pd.Series, label: str) -> pd.Series:
    return series.str.split("|").apply(lambda labels: label in labels)


def build_preflip(path: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    align = path[label_present(path["checkpoint_labels"], "aligning_flip")]
    final = path[label_present(path["checkpoint_labels"], "final_exit")]
    align = align.set_index("trade_id")
    final = final.set_index("trade_id")
    rows = []
    stop_rows = []
    for t in trades.itertuples(index=False):
        group = t.outcome_group
        boundary = final.loc[t.trade_id] if group == "stop_before_aligned_flip" else align.loc[t.trade_id]
        mae = float(boundary.countertrade_running_mae_atr)
        row = {"trade_id": t.trade_id, "year": int(t.year), "outcome_group": group,
               "trade_direction": "long_fade" if int(t.entry_direction) == 1 else "short_fade",
               "session": t.session, "pre_flip_mae_atr": mae,
               "boundary_kind": "stop_fill" if group == "stop_before_aligned_flip" else "aligning_flip_open"}
        for level in (0.50, 0.75, 1.00, 1.25, 1.50):
            row[f"mae_ge_{level:.2f}_atr"] = mae >= level
        rows.append(row)
        if group == "stop_before_aligned_flip":
            mfe = float(final.loc[t.trade_id].countertrade_running_mfe_atr)
            stop = {"trade_id": t.trade_id, "year": int(t.year), "outcome_group": group,
                    "trade_direction": row["trade_direction"], "session": t.session,
                    "pre_stop_mfe_atr": mfe}
            for level in (0.25, 0.50, 0.75, 1.00):
                stop[f"mfe_ge_{level:.2f}_atr"] = mfe >= level
            stop_rows.append(stop)
    return pd.DataFrame(rows), pd.DataFrame(stop_rows)


def adverse_floor_touched(direction: int, floor_px: float, highs: np.ndarray,
                          lows: np.ndarray, exit_fill: float) -> bool:
    if direction == 1:
        return bool((len(lows) and float(lows.min()) <= floor_px) or exit_fill <= floor_px)
    if direction == -1:
        return bool((len(highs) and float(highs.max()) >= floor_px) or exit_fill >= floor_px)
    raise RuntimeError("direction must be exact +/-1")


def build_postflip(post: pd.DataFrame, trades: pd.DataFrame,
                   raw_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    trade_map = trades.set_index("trade_id")
    rows = []
    for d in post.itertuples(index=False):
        t = trade_map.loc[d.trade_id]
        raw = raw_by_year[int(d.year)]
        ts = raw.index.view(np.int64)
        highs = raw["high"].to_numpy(float)
        lows = raw["low"].to_numpy(float)
        direction = int(t.entry_direction)
        entry = float(t.entry_fill_open)
        atr = float(t.atr_at_checkpoint)
        peak_available = int(d.post_flip_peak_available_ts)
        exit_ts = int(t.exit_fill_ts)
        a = int(np.searchsorted(ts, peak_available, side="left"))
        b = int(np.searchsorted(ts, exit_ts, side="left"))
        path_highs, path_lows = highs[a:b], lows[a:b]
        exit_fill = float(t.exit_fill_px)
        post_peak = float(d.post_flip_peak_mfe_atr)
        align_a = int(np.searchsorted(ts, int(d.aligning_flip_fill_ts), side="left"))
        align_highs, align_lows = highs[align_a:b], lows[align_a:b]
        row = {"trade_id": d.trade_id, "year": int(d.year), "outcome_group": d.outcome_group,
               "trade_direction": d.trade_direction, "session": d.session,
               "aligning_flip_pnl_atr": float(d.aligning_flip_pnl_atr),
               "post_flip_peak_mfe_atr": post_peak,
               "post_flip_peak_time_from_flip_s": float(d.post_flip_peak_time_from_flip_s),
               "post_flip_giveback_to_exit_atr": float(d.post_flip_peak_giveback_to_exit_atr),
               "realized_capture_ratio": float(d.realized_capture_ratio),
               "price_revisited_entry_after_flip": adverse_floor_touched(
                   direction, entry, align_highs, align_lows, exit_fill)}
        fixed = (("breakeven", 0.0), ("plus_0p25", 0.25), ("plus_0p50", 0.50))
        for name, floor_atr in fixed:
            eligible = post_peak >= floor_atr
            floor_px = entry + direction * floor_atr * atr
            row[f"eligible_{name}"] = eligible
            row[f"revisited_{name}_after_peak"] = (adverse_floor_touched(
                direction, floor_px, path_highs, path_lows, exit_fill) if eligible else None)
        for fraction, name in ((0.25, "retain_25pct_mfe"), (0.50, "retain_50pct_mfe")):
            floor_px = entry + direction * fraction * post_peak * atr
            row[f"revisited_{name}_after_peak"] = adverse_floor_touched(
                direction, floor_px, path_highs, path_lows, exit_fill)
        rows.append(row)
    return pd.DataFrame(rows)


def stage2_gate_2025(pre: pd.DataFrame, post: pd.DataFrame, config: dict) -> dict:
    pre25 = pre[(pre["year"] == 2025) & (pre["outcome_group"] != "stop_before_aligned_flip")]
    post25 = post[post["year"] == 2025]
    losers = post25[post25["outcome_group"] == "opposite_flip_exit_loser"]
    winners = post25[post25["outcome_group"] == "opposite_flip_exit_winner"]
    p95 = float(pre25["pre_flip_mae_atr"].quantile(0.95))
    initial_pass = p95 <= config["initial_geometry_p95_max_atr_2025"]
    loser_giveback = float(losers["post_flip_giveback_to_exit_atr"].median())
    loser_reach = float((losers["post_flip_peak_mfe_atr"] >= config["postflip_arm_atr"]).mean())
    winner_reach = float((winners["post_flip_peak_mfe_atr"] >= config["postflip_arm_atr"]).mean())
    post_pass = bool(
        loser_giveback >= config["postflip_loser_median_giveback_min_2025"]
        and loser_reach >= config["postflip_loser_reach_1atr_min_2025"]
        and winner_reach >= config["postflip_winner_reach_1atr_min_2025"])
    preservation = {}
    selected = None
    for candidate in config["preflip_stop_candidates_atr"]:
        rate = float((pre25["pre_flip_mae_atr"] < candidate).mean())
        preservation[str(candidate)] = rate
        if selected is None and rate >= config["preflip_preservation_min_2025"]:
            selected = candidate
    return {"selection_source": "2025_only", "initial_geometry_pass": bool(initial_pass),
            "postflip_geometry_pass": post_pass, "stage2_pass": bool(initial_pass or post_pass),
            "reached_flip_pre_mae_p95_2025": p95,
            "reached_flip_preservation_by_candidate_2025": preservation,
            "selected_preflip_stop_atr": selected if initial_pass else None,
            "planned_loser_median_giveback_2025": loser_giveback,
            "planned_loser_reach_1atr_rate_2025": loser_reach,
            "planned_winner_reach_1atr_rate_2025": winner_reach,
            "selected_postflip_rule": ({"arm_atr": config["postflip_arm_atr"],
                                         "floor_atr": config["postflip_floor_atr"]}
                                        if post_pass else None)}


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("stage1_descriptive_only") is not True:
        raise RuntimeError("Stage 1 descriptive guardrail missing")
    require_authorization()
    validate_inputs(config)
    path = pd.read_parquet(PATH_RESULTS / "path_checkpoints.parquet")
    post = pd.read_parquet(PATH_RESULTS / "post_flip_exit_diagnostic.parquet")
    trades = []
    raw = {}
    for year in (2025, 2026):
        frame = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
        frame["trade_id"] = [f"{year}_{i:05d}" for i in range(len(frame))]
        frame["outcome_group"] = np.where(
            frame["exit_reason"].eq("opposite_flip_against_countertrade"),
            np.where(frame["net_pnl_usd"] > 0, "opposite_flip_exit_winner", "opposite_flip_exit_loser"),
            frame["exit_reason"])
        trades.append(frame)
        raw[year] = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close"])
    trades = pd.concat(trades, ignore_index=True)
    pre, prestop = build_preflip(path, trades)
    postgeo = build_postflip(post, trades, raw)
    if len(pre) != len(trades) or len(prestop) != int((trades.outcome_group == "stop_before_aligned_flip").sum()):
        raise RuntimeError("Stage 1 geometry cardinality failure")
    if len(postgeo) != int((trades.outcome_group != "stop_before_aligned_flip").sum()):
        raise RuntimeError("post-flip geometry cardinality failure")
    gate = stage2_gate_2025(pre, postgeo, config)
    pre.to_parquet(RESULTS / "pre_flip_mae_geometry.parquet", index=False)
    prestop.to_parquet(RESULTS / "pre_stop_mfe_geometry.parquet", index=False)
    postgeo.to_parquet(RESULTS / "post_flip_giveback_geometry.parquet", index=False)
    manifest = {"status": "STAGE1_COMPLETE", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH), "trade_count": len(trades),
                "stage2_gate_2025": gate,
                "output_sha256": {name: sha256_file(RESULTS / name) for name in (
                    "pre_flip_mae_geometry.parquet", "pre_stop_mfe_geometry.parquet",
                    "post_flip_giveback_geometry.parquet")}}
    (RESULTS / "stage1_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
