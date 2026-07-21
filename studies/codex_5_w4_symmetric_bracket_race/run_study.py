"""Run frozen original-W4 symmetric PT/SL first-touch races."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, WORK, AUDIT = STUDY / "results", STUDY / "_work", STUDY / "audit"
CONFIG_PATH, FREEZE_PATH = STUDY / "config.json", STUDY / "input_freeze.json"
PRE_AUDIT, PRE_AUTH = AUDIT / "pre_execution_audit.md", AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
RAW = {2025: ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet",
       2026: ROOT / "data" / "raw" / "NQ_v0_1s_2026_ytd.parquet"}
NS, MULTIPLIER, COST = 1_000_000_000, 20.0, 10.0

for directory in (RESULTS, WORK, AUDIT):
    directory.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def score_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def input_hashes() -> dict:
    return {"trades_2025": sha256_file(trade_path(2025)),
            "trades_2026": sha256_file(trade_path(2026)),
            "raw_2025": sha256_file(RAW[2025]), "raw_2026": sha256_file(RAW[2026]),
            "scores_2025": sha256_file(score_path(2025)),
            "scores_2026": sha256_file(score_path(2026)),
            "original_policy": sha256_file(REPAIR / "CODEX_5_X_established_fade_policy.json"),
            "original_policy_completion_audit": sha256_file(
                REPAIR / "audit" / "CODEX_5_X_policy_completion_audit.md"),
            "frozen_model_manifest": sha256_file(
                REPAIR_RESULTS / "CODEX_5_X_frozen_model_manifest.json")}


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def require_authorization() -> None:
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists():
        raise RuntimeError("missing pre-execution authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    if not (re.search(r"^\*\*Status:\*\*\s+\*\*PASS", text, re.MULTILINE)
            and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                          text, re.MULTILINE)):
        raise RuntimeError("pre-execution audit is not clean")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH),
                "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(k) != v for k, v in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def validate_contract() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_CODE_EXECUTION":
        raise RuntimeError("inactive input freeze")
    if freeze.get("population_count") != 4383 or freeze.get("population_count_by_year") != {
            "2025": 3246, "2026": 1137}:
        raise RuntimeError("population freeze changed")
    if input_hashes() != freeze.get("input_sha256"):
        raise RuntimeError("frozen dependency mismatch")
    fixed = {"primary_bracket_atr": 1.25, "sensitivity_brackets_atr": [1.0, 1.25, 1.5],
             "tie_policies": ["conservative", "decisive"],
             "primary_tie_policy": "conservative", "entry_bar_included": True,
             "race_terminal": "first_pt_or_sl_touch_or_raw_year_end",
             "unresolved_economics": "excluded_no_invented_exit",
             "atr_denominator": "atr_at_checkpoint", "multiplier_usd_per_point": 20.0,
             "round_trip_cost_usd": 10.0, "policy_a_alignment_count": 2332,
             "policy_a_population_count": 4383, "development_year": 2025,
             "selection_isolated_year": 2026}
    if any(config.get(k) != v for k, v in fixed.items()):
        raise RuntimeError("fixed study contract changed")
    return config


def validate_raw(raw: pd.DataFrame) -> None:
    if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
        raise RuntimeError("raw index must be timezone-aware")
    if not raw.index.is_monotonic_increasing or raw.index.has_duplicates:
        raise RuntimeError("raw timestamps invalid")
    values = raw[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(values).all():
        raise RuntimeError("nonfinite OHLC")
    o, h, l, c = (raw[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    if np.any(h < l) or np.any(h < np.maximum(o, c)) or np.any(l > np.minimum(o, c)):
        raise RuntimeError("invalid OHLC geometry")


def load_population(year: int, raw: pd.DataFrame) -> pd.DataFrame:
    trades = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
    expected = {2025: 3246, 2026: 1137}[year]
    if len(trades) != expected:
        raise RuntimeError("original W4 count mismatch")
    if trades.entry_fill_ts.duplicated().any():
        raise RuntimeError("duplicate entry timestamp")
    if not trades.research_contract.eq("EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT").all():
        raise RuntimeError("unexpected upstream research contract")
    if not trades.policy_sha256.eq(
            "1a22e4adaf7ebf141cb9b9011c4b5d05f7da8b0de7130ee4f7f7bcea7bc77c5b").all():
        raise RuntimeError("upstream policy hash mismatch")
    ts = raw.index.view(np.int64)
    idx = np.searchsorted(ts, trades.entry_fill_ts.to_numpy(np.int64), side="left")
    if np.any(idx >= len(ts)) or np.any(ts[idx] != trades.entry_fill_ts.to_numpy(np.int64)):
        raise RuntimeError("entry timestamp missing from raw")
    if not np.allclose(raw.open.to_numpy(float)[idx], trades.entry_fill_open, rtol=0, atol=1e-12):
        raise RuntimeError("entry open mismatch")
    return trades


def first_touch(trade: pd.Series, raw: pd.DataFrame, bracket_atr: float,
                tie_policy: str) -> dict:
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[x].to_numpy(float) for x in ("open", "high", "low"))
    entry_ts, entry = int(trade.entry_fill_ts), float(trade.entry_fill_open)
    direction, atr = int(trade.entry_direction), float(trade.atr_at_checkpoint)
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    pt, sl = entry + direction * bracket_atr * atr, entry - direction * bracket_atr * atr
    running_fav = running_adv = 0.0
    outcome, resolution_i, tie = "unresolved", None, False
    fav_before = adv_before = 0.0
    for i in range(start, len(ts)):
        high, low = float(highs[i]), float(lows[i])
        favorable = max((high - entry) if direction == 1 else (entry - low), 0.0) / atr
        adverse = max((entry - low) if direction == 1 else (high - entry), 0.0) / atr
        pt_touch = high >= pt if direction == 1 else low <= pt
        sl_touch = low <= sl if direction == 1 else high >= sl
        if pt_touch or sl_touch:
            fav_before, adv_before = running_fav, running_adv
            tie = bool(pt_touch and sl_touch)
            if tie and tie_policy == "decisive":
                outcome = "pt_first" if (favorable - bracket_atr) > (adverse - bracket_atr) else "sl_first"
            elif tie:
                outcome = "sl_first"
            else:
                outcome = "pt_first" if pt_touch else "sl_first"
            resolution_i = i
            running_fav, running_adv = max(running_fav, favorable), max(running_adv, adverse)
            break
        running_fav, running_adv = max(running_fav, favorable), max(running_adv, adverse)
    if resolution_i is None:
        resolution_ts, seconds = pd.NA, np.nan
    else:
        resolution_ts = int(ts[resolution_i])
        seconds = (resolution_ts - entry_ts) / NS
    gross = bracket_atr * atr * MULTIPLIER
    net = gross - COST if outcome == "pt_first" else (-gross - COST if outcome == "sl_first" else np.nan)
    return {"bracket_atr": bracket_atr, "tie_policy": tie_policy,
        "pt_px": pt, "sl_px": sl, "outcome": outcome,
        "pt_first": outcome == "pt_first", "sl_first": outcome == "sl_first",
        "same_bar_tie": tie, "resolution_ts": resolution_ts,
        "time_to_resolution_s": seconds, "net_pnl_usd": net,
        "gross_bracket_value_usd": gross,
        "favorable_excursion_before_resolution_atr": fav_before,
        "adverse_excursion_before_resolution_atr": adv_before,
        "max_favorable_through_resolution_atr": running_fav,
        "max_adverse_through_resolution_atr": running_adv}


def tail_diagnostic(trade: pd.Series, primary: pd.Series, raw: pd.DataFrame) -> dict:
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[x].to_numpy(float) for x in ("open", "high", "low"))
    entry_ts, entry = int(trade.entry_fill_ts), float(trade.entry_fill_open)
    direction, atr = int(trade.entry_direction), float(trade.atr_at_checkpoint)
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    horizon_i = int(np.searchsorted(ts, int(trade.scheduled_exit_decision_ts), side="left"))
    horizon_available = horizon_i < len(ts)
    end = horizon_i if horizon_available else len(ts)
    if end <= start:
        raise RuntimeError("invalid tail horizon")
    favorable = ((highs[start:end] - entry) if direction == 1
                 else (entry - lows[start:end])) / atr
    adverse = ((entry - lows[start:end]) if direction == 1
               else (highs[start:end] - entry)) / atr
    favorable = np.maximum(favorable, 0.0)
    adverse = np.maximum(adverse, 0.0)
    max_mfe, max_mae = float(favorable.max()), float(adverse.max())
    resolution_ts = primary.resolution_ts
    res_i = (int(np.searchsorted(ts, int(resolution_ts), side="left"))
             if not pd.isna(resolution_ts) else None)
    resolution_before_horizon = bool(res_i is not None and res_i < end)
    post_fav = np.array([], dtype=float)
    if resolution_before_horizon and res_i + 1 < end:
        post_fav = favorable[(res_i + 1 - start):]
    additional_after_pt = (max(float(post_fav.max()) if len(post_fav) else 1.25, 1.25) - 1.25
                           if bool(primary.pt_first) and resolution_before_horizon else np.nan)
    horizon_px = float(opens[horizon_i]) if horizon_available else np.nan
    horizon_pnl_atr = direction * (horizon_px - entry) / atr if horizon_available else np.nan
    horizon_net = (direction * (horizon_px - entry) * MULTIPLIER - COST
                   if horizon_available else np.nan)
    giveback = max_mfe - horizon_pnl_atr if horizon_available else np.nan
    reversal_before_2a = pd.NA
    entry_2a_same_bar_ambiguous = False
    if bool(primary.pt_first) and resolution_before_horizon:
        reversal_before_2a = False
        for i in range(res_i + 1, end):
            hit_2a = (highs[i] >= entry + 2 * atr if direction == 1
                      else lows[i] <= entry - 2 * atr)
            hit_entry = lows[i] <= entry if direction == 1 else highs[i] >= entry
            if hit_2a or hit_entry:
                if hit_2a and hit_entry:
                    reversal_before_2a = pd.NA
                    entry_2a_same_bar_ambiguous = True
                else:
                    reversal_before_2a = bool(hit_entry)
                break
    later_recovered = pd.NA
    if bool(primary.sl_first) and resolution_before_horizon:
        later = slice(res_i + 1, end)
        if direction == 1:
            later_recovered = bool(np.any(highs[later] >= entry + 1.25 * atr))
        else:
            later_recovered = bool(np.any(lows[later] <= entry - 1.25 * atr))
    return {"primary_outcome": primary.outcome, "primary_resolution_ts": resolution_ts,
        "horizon_ts": int(trade.scheduled_exit_decision_ts), "horizon_available": horizon_available,
        "primary_resolution_before_horizon": resolution_before_horizon,
        "additional_mfe_after_pt_atr": additional_after_pt, "max_total_mfe_atr": max_mfe,
        "max_total_mae_atr": max_mae, "reached_2a": bool(max_mfe >= 2.0),
        "reached_3a": bool(max_mfe >= 3.0), "reached_4a": bool(max_mfe >= 4.0),
        "eventual_regime_flip_pnl_atr": horizon_pnl_atr,
        "eventual_regime_flip_net_pnl_usd": horizon_net,
        "giveback_mfe_to_regime_exit_atr": giveback,
        "pt_first_then_large_runner": (bool(max_mfe >= 2.0)
            if bool(primary.pt_first) and resolution_before_horizon else pd.NA),
        "pt_first_then_immediate_reversal": reversal_before_2a,
        "pt_post_resolution_entry_2a_same_bar_ambiguous": entry_2a_same_bar_ambiguous,
        "sl_first_later_recovered_to_pt": later_recovered}


def split_definitions(population: pd.DataFrame) -> list[tuple[str, str, pd.Series]]:
    return [("combined", "ALL", pd.Series(True, index=population.index)),
            ("year", "2025", population.year == 2025),
            ("year", "2026", population.year == 2026),
            ("direction", "long_fade", population.entry_direction == 1),
            ("direction", "short_fade", population.entry_direction == -1),
            ("session", "ETH", population.session == "ETH"),
            ("session", "RTH", population.session == "RTH"),
            ("direction_session", "long_ETH", (population.entry_direction == 1) & (population.session == "ETH")),
            ("direction_session", "long_RTH", (population.entry_direction == 1) & (population.session == "RTH")),
            ("direction_session", "short_ETH", (population.entry_direction == -1) & (population.session == "ETH")),
            ("direction_session", "short_RTH", (population.entry_direction == -1) & (population.session == "RTH"))]


def cost_adjusted_breakeven_rate(average_gross_win: float,
                                 average_gross_loss: float) -> float:
    denominator = average_gross_win + average_gross_loss
    return ((average_gross_loss + COST) / denominator
            if denominator > 0 and np.isfinite(denominator) else np.nan)


def summarize(trade_diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = trade_diffs[["year", "trade_id", "entry_direction", "session"]].drop_duplicates("trade_id")
    for bracket in (1.0, 1.25, 1.5):
        for tie_policy in ("conservative", "decisive"):
            race = trade_diffs[(trade_diffs.bracket_atr == bracket)
                               & (trade_diffs.tie_policy == tie_policy)].set_index("trade_id")
            pop = base.set_index("trade_id").join(race, how="left", rsuffix="_race").reset_index()
            for split_type, split_value, mask in split_definitions(pop):
                g = pop[mask]
                resolved = g[g.outcome != "unresolved"]
                winners, losers = resolved[resolved.pt_first], resolved[resolved.sl_first]
                win_sum = float(winners.net_pnl_usd.sum())
                loss_sum = float(-losers.net_pnl_usd.sum())
                average_gross_win = float(winners.gross_bracket_value_usd.mean()) if len(winners) else np.nan
                average_gross_loss = float(losers.gross_bracket_value_usd.mean()) if len(losers) else np.nan
                breakeven = cost_adjusted_breakeven_rate(average_gross_win, average_gross_loss)
                pt_all = float(g.pt_first.mean()) if len(g) else np.nan
                pt_resolved = float(resolved.pt_first.mean()) if len(resolved) else np.nan
                rows.append({"bracket_atr": bracket, "tie_policy": tie_policy,
                    "split_type": split_type, "split_value": split_value,
                    "trade_count": len(g), "pt_first_count": int(g.pt_first.sum()),
                    "sl_first_count": int(g.sl_first.sum()),
                    "same_bar_tie_count": int(g.same_bar_tie.sum()),
                    "same_bar_tie_rate": float(g.same_bar_tie.mean()) if len(g) else np.nan,
                    "unresolved_count": int(g.outcome.eq("unresolved").sum()),
                    "pt_first_rate_all": pt_all, "pt_first_rate_resolved": pt_resolved,
                    "mean_net_pnl_usd": float(resolved.net_pnl_usd.mean()) if len(resolved) else np.nan,
                    "profit_factor": win_sum / loss_sum if loss_sum else np.nan,
                    "average_winner_usd": float(winners.net_pnl_usd.mean()) if len(winners) else np.nan,
                    "average_loser_usd": float(losers.net_pnl_usd.mean()) if len(losers) else np.nan,
                    "median_time_to_resolution_s": float(resolved.time_to_resolution_s.median()) if len(resolved) else np.nan,
                    "p25_time_to_resolution_s": float(resolved.time_to_resolution_s.quantile(.25)) if len(resolved) else np.nan,
                    "p75_time_to_resolution_s": float(resolved.time_to_resolution_s.quantile(.75)) if len(resolved) else np.nan,
                    "median_favorable_excursion_before_loss_atr": float(
                        losers.favorable_excursion_before_resolution_atr.median()) if len(losers) else np.nan,
                    "median_adverse_excursion_before_win_atr": float(
                        winners.adverse_excursion_before_resolution_atr.median()) if len(winners) else np.nan,
                    "average_gross_winner_bracket_usd": average_gross_win,
                    "average_gross_loser_bracket_usd": average_gross_loss,
                    "estimated_cost_adjusted_breakeven_rate": breakeven,
                    "edge_over_cost_adjusted_breakeven_pp": (pt_resolved - breakeven) * 100,
                    "net_expectancy_per_resolved_trade_usd": float(
                        resolved.net_pnl_usd.mean()) if len(resolved) else np.nan})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "config": sha256_file(CONFIG_PATH),
            "freeze": sha256_file(FREEZE_PATH), "audit": sha256_file(PRE_AUDIT),
            "authorization": sha256_file(PRE_AUTH), "raw_2025": sha256_file(RAW[2025]),
            "trades_2025": sha256_file(trade_path(2025))}


def require_2025_seal() -> None:
    path = WORK / "reconciliation_2025.json"
    if not path.exists():
        raise RuntimeError("2026 sealed until 2025 completes")
    seal = json.loads(path.read_text(encoding="utf-8"))
    if seal.get("blocking_errors") != 0 or seal.get("dependency_hashes_2025") != dependency_hashes_2025():
        raise RuntimeError("2025 seal mismatch")
    for name, digest in seal["artifact_sha256"].items():
        if sha256_file(WORK / name) != digest:
            raise RuntimeError("2025 artifact changed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=(2025, 2026), required=True)
    args = parser.parse_args()
    require_authorization()
    config = validate_contract()
    if args.year == 2026:
        require_2025_seal()
    raw = pd.read_parquet(RAW[args.year], columns=["open", "high", "low", "close", "volume"])
    validate_raw(raw)
    population = load_population(args.year, raw).copy()
    population["trade_id"] = [f"W4_{args.year}_{i:05d}" for i in range(1, len(population) + 1)]
    race_rows, primary_rows = [], []
    for t in population.itertuples(index=False):
        s = pd.Series(t._asdict())
        base = {"trade_id": t.trade_id, "year": args.year,
            "regime_start_ns": int(t.regime_start_ns), "confirm_flip_ns": int(t.confirm_flip_ns),
            "entry_direction": int(t.entry_direction),
            "direction": "long_fade" if int(t.entry_direction) == 1 else "short_fade",
            "session": t.session, "entry_fill_ts": int(t.entry_fill_ts),
            "entry_fill_open": float(t.entry_fill_open), "atr_at_checkpoint": float(t.atr_at_checkpoint),
            "scheduled_exit_decision_ts": int(t.scheduled_exit_decision_ts)}
        primary = None
        for bracket in config["sensitivity_brackets_atr"]:
            for tie_policy in config["tie_policies"]:
                result = first_touch(s, raw, float(bracket), tie_policy)
                row = {**base, **result}
                race_rows.append(row)
                if bracket == 1.25 and tie_policy == "conservative":
                    primary = pd.Series(row)
        primary_rows.append({**base, **tail_diagnostic(s, primary, raw)})
    races, tails = pd.DataFrame(race_rows), pd.DataFrame(primary_rows)
    paths = {f"trade_diffs_{args.year}.parquet": races,
             f"tail_diagnostics_{args.year}.parquet": tails}
    for name, frame in paths.items():
        frame.to_parquet(WORK / name, index=False)
    primary = races[(races.bracket_atr == 1.25) & (races.tie_policy == "conservative")]
    seal = {"year": args.year, "blocking_errors": 0, "population_count": len(population),
        "primary_resolved_count": int(primary.outcome.ne("unresolved").sum()),
        "dependency_hashes_2025": dependency_hashes_2025(),
        "artifact_sha256": {name: sha256_file(WORK / name) for name in paths}}
    (WORK / f"reconciliation_{args.year}.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    if args.year == 2026:
        races_all = pd.concat([pd.read_parquet(WORK / "trade_diffs_2025.parquet"), races],
                              ignore_index=True)
        tails_all = pd.concat([pd.read_parquet(WORK / "tail_diagnostics_2025.parquet"), tails],
                              ignore_index=True)
        outputs = {"w4_symmetric_bracket_results.parquet": summarize(races_all),
                   "w4_symmetric_bracket_trade_diffs.parquet": races_all,
                   "w4_symmetric_bracket_tail_diagnostics.parquet": tails_all}
        for name, frame in outputs.items():
            frame.to_parquet(RESULTS / name, index=False)
        manifest = {"status": "OUTPUTS_COMPLETE_PENDING_REPORT_AND_COMPLETION_AUDIT",
            "population_count": 4383, "runner_sha256": script_sha256(),
            "config_sha256": sha256_file(CONFIG_PATH), "freeze_sha256": sha256_file(FREEZE_PATH),
            "output_sha256": {name: sha256_file(RESULTS / name) for name in outputs}}
        (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(population):,} original W4 entries; "
          f"primary PT={int(primary.pt_first.sum()):,}, SL={int(primary.sl_first.sum()):,}, "
          f"ties={int(primary.same_bar_tie.sum()):,}, unresolved={int(primary.outcome.eq('unresolved').sum()):,}")


if __name__ == "__main__":
    main()
