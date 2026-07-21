"""Replay frozen W4 candidates as a causal one-position streaming lifecycle."""
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
MULTI = ROOT / "studies" / "codex_5_w4_multi_candidate_reentry"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
NS, TIMEOUT_NS, MULTIPLIER, COST = 1_000_000_000, 300_000_000_000, 20.0, 10.0

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file, year_atlas_path  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, validate_raw_bars,
)

for directory in (RESULTS, WORK, AUDIT):
    directory.mkdir(parents=True, exist_ok=True)


def candidate_path(year: int) -> Path:
    return MULTI / "_work" / f"candidates_{year}.parquet"


def score_path(year: int) -> Path:
    return REPAIR / "results" / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def input_hashes() -> dict:
    return {
        "candidates_2025": sha256_file(candidate_path(2025)),
        "candidates_2026": sha256_file(candidate_path(2026)),
        "multi_candidate_opportunities": sha256_file(
            MULTI / "results" / "multi_candidate_opportunity_results.parquet"),
        "multi_candidate_policy_results": sha256_file(
            MULTI / "results" / "multi_candidate_policy_results.parquet"),
        "multi_candidate_runner": sha256_file(MULTI / "run_study.py"),
        "multi_candidate_completion_audit": sha256_file(MULTI / "audit" / "completion_audit.md"),
        "multi_candidate_manifest": sha256_file(MULTI / "results" / "run_manifest.json"),
        "common_helper": sha256_file(REPAIR / "CODEX_5_X_common.py"),
        "established_fade_helper": sha256_file(REPAIR / "CODEX_5_X_run_established_fade.py"),
        "regime_reproduction_helper": sha256_file(
            ROOT / "studies" / "regime_sequence_chop_context" / "reproduce_regimes.py"),
        "repaired_atlas_2025": sha256_file(year_atlas_path(2025)),
        "repaired_atlas_2026": sha256_file(year_atlas_path(2026)),
        "w4_scores_2025": sha256_file(score_path(2025)),
        "w4_scores_2026": sha256_file(score_path(2026)),
        "raw_2025": sha256_file(RAW_1S[2025]),
        "raw_2026": sha256_file(RAW_1S[2026]),
    }


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def require_authorization() -> None:
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists():
        raise RuntimeError("missing pre-execution lookahead authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    clean = (re.search(r"^\*\*Status:\*\*\s+\*\*PASS", text, re.MULTILINE)
             and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                           text, re.MULTILINE))
    if not clean:
        raise RuntimeError("pre-execution audit is not a clean PASS")
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
    if input_hashes() != freeze.get("input_sha256"):
        raise RuntimeError("frozen input hash mismatch")
    fixed_counts = (freeze.get("candidate_count") == 11812
                    and freeze.get("opportunity_count") == 4767
                    and freeze.get("baseline_trade_count") == 4383
                    and freeze.get("candidate_count_by_year") == {"2025": 8682, "2026": 3130}
                    and freeze.get("opportunity_count_by_year") == {"2025": 3530, "2026": 1237}
                    and freeze.get("baseline_trade_count_by_year") == {"2025": 3246, "2026": 1137})
    if not fixed_counts:
        raise RuntimeError("frozen cardinality mismatch")
    expected_policies = [("BASELINE", 0, "frozen_policy_a"),
                         ("S1", 0, "original_opposing_flip"),
                         ("S2", 0, "w4_exit_only"),
                         ("S3", 0, "w4_reverse"),
                         ("S4", 10, "original_opposing_flip")]
    actual = [(p.get("policy_id"), p.get("entry_delay_seconds"), p.get("lifecycle_exit"))
              for p in config.get("policies", [])]
    if actual != expected_policies:
        raise RuntimeError("policy set changed")
    fixed = {"virtual_directional_pnl_threshold_points": 0.0,
             "crossings_while_position_open": "consumed_not_queued",
             "crossings_during_confirmation_wait": "consumed_not_queued",
             "resume_scan_boundary": "strictly_after_exit_timestamp",
             "maximum_net_positions": 1, "timeout_seconds": 300,
             "preflip_stop_atr": 1.25, "postflip_stop_atr": 1.5,
             "atr_denominator": "atr_at_checkpoint", "multiplier_usd_per_point": 20.0,
             "cost_rt_usd": 10.0, "development_year": 2025,
             "selection_isolated_year": 2026}
    if any(config.get(k) != v for k, v in fixed.items()):
        raise RuntimeError("execution contract changed")
    return config


def load_candidates(year: int) -> pd.DataFrame:
    frame = pd.read_parquet(candidate_path(year)).sort_values(
        ["candidate_time", "candidate_seq"], kind="stable").reset_index(drop=True)
    expected = {2025: (8682, 3530), 2026: (3130, 1237)}[year]
    if len(frame) != expected[0] or frame.opportunity_id.nunique() != expected[1]:
        raise RuntimeError("candidate population mismatch")
    if frame[["opportunity_id", "candidate_seq"]].duplicated().any():
        raise RuntimeError("duplicate candidate sequence")
    first = frame.groupby("opportunity_id", sort=False).candidate_seq.min()
    if not first.eq(1).all():
        raise RuntimeError("opportunity lacks sequence one")
    return frame


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def stop_fill(direction: int, stop: float, open_px: float) -> float:
    gap = open_px <= stop if direction == 1 else open_px >= stop
    return open_px if gap else stop


def gate_candidate(candidate: pd.Series, raw: pd.DataFrame, delay_seconds: int) -> dict:
    """Causally evaluate an immediate or fixed +10-second entry candidate."""
    ts = raw.index.view(np.int64)
    opens, closes = raw.open.to_numpy(float), raw.close.to_numpy(float)
    fill_ts, fill_px = int(candidate.candidate_fill_time), float(candidate.candidate_fill_price)
    align_ts, end_ts = int(candidate.confirm_flip_ns), int(candidate.opportunity_end_ts)
    base = {"candidate_id": candidate.candidate_id, "candidate_time": int(candidate.candidate_time),
            "would_fill_ts": fill_ts, "would_fill_px": fill_px}
    if delay_seconds == 0:
        if fill_ts >= align_ts:
            return {**base, "accepted": False, "reason": "aligning_flip_before_entry",
                    "consume_through_ts": fill_ts}
        return {**base, "accepted": True, "reason": "accepted",
                "gate_decision_ts": int(candidate.candidate_time),
                "entry_fill_ts": fill_ts, "entry_fill_px": fill_px,
                "virtual_directional_pnl_points": 0.0, "fill_change_points": 0.0,
                "consume_through_ts": fill_ts}
    gate_ts = fill_ts + delay_seconds * NS
    if align_ts <= gate_ts:
        return {**base, "accepted": False, "reason": "regime_ended_before_confirmation",
                "gate_decision_ts": gate_ts, "consume_through_ts": gate_ts}
    if end_ts <= gate_ts:
        return {**base, "accepted": False, "reason": "opportunity_ended_before_confirmation",
                "gate_decision_ts": gate_ts, "consume_through_ts": gate_ts}
    mark_i = int(np.searchsorted(ts, gate_ts, side="left")) - 1
    if mark_i < 0 or int(ts[mark_i]) + NS > gate_ts:
        return {**base, "accepted": False, "reason": "confirmation_mark_unavailable",
                "gate_decision_ts": gate_ts, "consume_through_ts": gate_ts}
    virtual = int(candidate.entry_direction) * (float(closes[mark_i]) - fill_px)
    if virtual < 0:
        return {**base, "accepted": False, "reason": "adverse_virtual_response",
                "gate_decision_ts": gate_ts, "confirmation_mark_ts": int(ts[mark_i]),
                "virtual_directional_pnl_points": virtual, "consume_through_ts": gate_ts}
    entry_i = int(np.searchsorted(ts, gate_ts, side="right"))
    if entry_i >= len(ts):
        return {**base, "accepted": False, "reason": "delayed_fill_unavailable",
                "gate_decision_ts": gate_ts, "consume_through_ts": gate_ts}
    actual_ts, actual_px = int(ts[entry_i]), float(opens[entry_i])
    if actual_ts >= align_ts:
        return {**base, "accepted": False, "reason": "aligning_flip_before_delayed_entry",
                "gate_decision_ts": gate_ts, "consume_through_ts": actual_ts}
    if actual_ts >= end_ts:
        return {**base, "accepted": False, "reason": "opportunity_ended_before_delayed_entry",
                "gate_decision_ts": gate_ts, "consume_through_ts": actual_ts}
    fill_change = int(candidate.entry_direction) * (actual_px - fill_px)
    return {**base, "accepted": True, "reason": "accepted",
            "gate_decision_ts": gate_ts, "confirmation_mark_ts": int(ts[mark_i]),
            "entry_fill_ts": actual_ts, "entry_fill_px": actual_px,
            "virtual_directional_pnl_points": virtual, "fill_change_points": fill_change,
            "consume_through_ts": actual_ts}


def opposite_w4_candidate(position_direction: int, align_ts: int, scheduled_ts: int,
                          candidates: pd.DataFrame) -> pd.Series | None:
    eligible = candidates[(candidates.regime_start_ns == align_ts)
                          & (candidates.entry_direction == -position_direction)
                          & (candidates.candidate_time >= align_ts)
                          & (candidates.candidate_fill_time < scheduled_ts)]
    if eligible.empty:
        return None
    return eligible.sort_values(["candidate_time", "candidate_seq"], kind="stable").iloc[0]


def simulate_path(candidate: pd.Series, entry_ts: int, entry_px: float, raw: pd.DataFrame,
                  scheduled_decision: int, w4_signal: pd.Series | None = None) -> dict:
    """Run one fill-anchored position path under the declared OHLC ordering."""
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[x].to_numpy(float) for x in ("open", "high", "low"))
    direction, atr = int(candidate.entry_direction), float(candidate.atr_at_checkpoint)
    align_ts, timeout_ts = int(candidate.confirm_flip_ns), int(entry_ts) + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled_decision, side="left"))
    if start >= len(ts) or int(ts[start]) != entry_ts or scheduled_i >= len(ts):
        raise RuntimeError("invalid trade boundary")
    scheduled_fill_ts = int(ts[scheduled_i])
    w4_fill_ts = int(w4_signal.candidate_fill_time) if w4_signal is not None else None
    pre_stop = entry_px - direction * 1.25 * atr
    post_stop = entry_px - direction * 1.5 * atr
    aligned, timeout_pending = False, False
    exit_ts = exit_px = reason = None
    for i in range(start, scheduled_i + 1):
        now = int(ts[i])
        if not aligned and now >= align_ts and align_ts <= timeout_ts:
            aligned = True
        if timeout_pending and now > timeout_ts:
            exit_ts, exit_px, reason = now, float(opens[i]), "confirmation_timeout_exit"
            break
        if not aligned and now > timeout_ts:
            exit_ts, exit_px, reason = now, float(opens[i]), "confirmation_timeout_exit"
            break
        if aligned and w4_fill_ts is not None and now >= w4_fill_ts:
            exit_ts, exit_px, reason = now, float(opens[i]), "opposite_w4_signal_exit"
            break
        if now >= scheduled_fill_ts:
            exit_ts, exit_px, reason = now, float(opens[i]), "original_opposing_flip_exit"
            break
        if now == timeout_ts and not aligned:
            timeout_pending = True
        stop = post_stop if aligned else pre_stop
        stop_reason = "stop_after_aligned_flip" if aligned else "stop_before_aligned_flip"
        if touched_stop(direction, stop, float(highs[i]), float(lows[i])):
            exit_ts, exit_px, reason = now, stop_fill(direction, stop, float(opens[i])), stop_reason
            break
    if exit_ts is None:
        raise RuntimeError("position ended without an exit")
    points = direction * (float(exit_px) - float(entry_px))
    return {"reached_aligning_flip": bool(aligned), "aligning_flip_ts": align_ts,
            "timeout_ts": timeout_ts, "preflip_stop_px": pre_stop, "postflip_stop_px": post_stop,
            "exit_fill_ts": int(exit_ts), "exit_fill_px": float(exit_px), "exit_reason": reason,
            "gross_pnl_pts": points, "gross_pnl_usd": points * MULTIPLIER,
            "net_pnl_usd": points * MULTIPLIER - COST}


def simulate_position(candidate: pd.Series, gate: dict, raw: pd.DataFrame,
                      scheduled_decision: int, candidates: pd.DataFrame,
                      lifecycle_exit: str) -> dict:
    entry_ts, entry_px = int(gate["entry_fill_ts"]), float(gate["entry_fill_px"])
    signal = None
    if lifecycle_exit in ("w4_exit_only", "w4_reverse"):
        signal = opposite_w4_candidate(int(candidate.entry_direction), int(candidate.confirm_flip_ns),
                                       scheduled_decision, candidates)
    actual = simulate_path(candidate, entry_ts, entry_px, raw, scheduled_decision, signal)
    out = {**actual, "w4_signal_candidate_id": None, "w4_signal_time": pd.NA,
           "w4_signal_fill_ts": pd.NA, "counterfactual_regime_exit_pnl_usd": np.nan,
           "w4_exit_change_usd": np.nan}
    if actual["exit_reason"] == "opposite_w4_signal_exit":
        counterfactual = simulate_path(candidate, entry_ts, entry_px, raw, scheduled_decision, None)
        out.update({"w4_signal_candidate_id": signal.candidate_id,
                    "w4_signal_time": int(signal.candidate_time),
                    "w4_signal_fill_ts": int(signal.candidate_fill_time),
                    "counterfactual_regime_exit_ts": int(counterfactual["exit_fill_ts"]),
                    "counterfactual_regime_exit_reason": counterfactual["exit_reason"],
                    "counterfactual_regime_exit_pnl_usd": float(counterfactual["net_pnl_usd"]),
                    "w4_exit_change_usd": float(actual["net_pnl_usd"]
                                                - counterfactual["net_pnl_usd"])})
    return out


def baseline_log(year: int) -> pd.DataFrame:
    prior = pd.read_parquet(MULTI / "results" / "multi_candidate_opportunity_results.parquet")
    prior = prior[(prior.policy_id == "R0") & (prior.year == year) & prior.executed].copy()
    expected = {2025: 3246, 2026: 1137}[year]
    if len(prior) != expected:
        raise RuntimeError("baseline trade count mismatch")
    rows = []
    for n, t in enumerate(prior.sort_values("entry_fill_ts").itertuples(index=False), 1):
        rows.append({"policy_id": "BASELINE", "year": year, "trade_id": f"BASELINE_{year}_{n:05d}",
            "opportunity_id": t.opportunity_id, "candidate_id": t.candidate_id,
            "candidate_seq": int(t.candidate_seq), "attempt_number": 1,
            "entry_direction": int(t.entry_direction), "direction": t.direction,
            "opportunity_session": t.opportunity_session, "actual_entry_session": t.actual_entry_session,
            "entry_signal_ts": int(t.candidate_time), "entry_fill_ts": int(t.entry_fill_ts),
            "entry_fill_px": float(t.entry_fill_px), "atr_at_entry_signal": float(t.atr_at_checkpoint),
            "gate_delay_seconds": 0, "gate_decision_ts": int(t.candidate_time),
            "virtual_directional_pnl_points": 0.0, "fill_change_points": 0.0,
            "stop_submission_ts": int(t.entry_fill_ts), "stop_active_entry_bar": True,
            "reached_aligning_flip": bool(t.reached_aligning_flip),
            "aligning_flip_ts": int(t.confirm_flip_ns), "timeout_ts": int(t.timeout_ts),
            "exit_fill_ts": int(t.exit_fill_ts), "exit_fill_px": float(t.exit_fill_px),
            "exit_reason": t.exit_reason, "gross_pnl_pts": float(t.gross_pnl_pts),
            "gross_pnl_usd": float(t.gross_pnl_usd), "net_pnl_usd": float(t.net_pnl_usd),
            "round_trip_cost_usd": COST, "w4_signal_candidate_id": None,
            "w4_signal_time": pd.NA, "w4_signal_fill_ts": pd.NA,
            "counterfactual_regime_exit_pnl_usd": np.nan, "w4_exit_change_usd": np.nan,
            "reversal_source_candidate_id": None})
    return pd.DataFrame(rows)


def replay_stream(year: int, raw: pd.DataFrame, candidates: pd.DataFrame,
                  policy_id: str, delay_seconds: int, lifecycle_exit: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
    candidate_times = candidates.candidate_time.to_numpy(np.int64)
    by_id = candidates.set_index("candidate_id", drop=False)
    attempts: dict[str, int] = {}
    trades, evaluations = [], []
    idx, pending_reverse, trade_number = 0, None, 0
    while idx < len(candidates) or pending_reverse is not None:
        reversal_source = None
        if pending_reverse is not None:
            c = pending_reverse
            pending_reverse = None
            reversal_source = c.candidate_id
            gate = {"accepted": True, "reason": "accepted_same_fill_reversal",
                    "gate_decision_ts": int(c.candidate_time),
                    "entry_fill_ts": int(c.candidate_fill_time),
                    "entry_fill_px": float(c.candidate_fill_price),
                    "virtual_directional_pnl_points": 0.0, "fill_change_points": 0.0,
                    "consume_through_ts": int(c.candidate_fill_time)}
        else:
            c = candidates.iloc[idx]
            idx += 1
            gate = gate_candidate(c, raw, delay_seconds)
            evaluations.append({"policy_id": policy_id, "year": year,
                "candidate_id": c.candidate_id, "opportunity_id": c.opportunity_id,
                "candidate_seq": int(c.candidate_seq), "candidate_time": int(c.candidate_time), **gate})
            if delay_seconds:
                idx = max(idx, int(np.searchsorted(candidate_times,
                    int(gate["consume_through_ts"]), side="right")))
            if not gate["accepted"]:
                continue
        align_ts = int(c.confirm_flip_ns)
        scheduled = next_ends.get(align_ts)
        if scheduled is None:
            evaluations.append({"policy_id": policy_id, "year": year,
                "candidate_id": c.candidate_id, "opportunity_id": c.opportunity_id,
                "candidate_seq": int(c.candidate_seq), "candidate_time": int(c.candidate_time),
                "accepted": False, "reason": "confirming_regime_has_no_terminal_flip"})
            continue
        attempts[c.opportunity_id] = attempts.get(c.opportunity_id, 0) + 1
        attempt = attempts[c.opportunity_id]
        result = simulate_position(c, gate, raw, int(scheduled), candidates, lifecycle_exit)
        trade_number += 1
        row = {"policy_id": policy_id, "year": year,
            "trade_id": f"{policy_id}_{year}_{trade_number:05d}",
            "opportunity_id": c.opportunity_id, "candidate_id": c.candidate_id,
            "candidate_seq": int(c.candidate_seq), "attempt_number": attempt,
            "entry_direction": int(c.entry_direction), "direction": c.direction,
            "opportunity_session": c.session,
            "actual_entry_session": "RTH" if is_rth(int(gate["entry_fill_ts"])) else "ETH",
            "entry_signal_ts": int(c.candidate_time), "entry_fill_ts": int(gate["entry_fill_ts"]),
            "entry_fill_px": float(gate["entry_fill_px"]),
            "atr_at_entry_signal": float(c.atr_at_checkpoint),
            "gate_delay_seconds": delay_seconds, "gate_decision_ts": int(gate["gate_decision_ts"]),
            "virtual_directional_pnl_points": float(gate["virtual_directional_pnl_points"]),
            "fill_change_points": float(gate["fill_change_points"]),
            "stop_submission_ts": int(gate["entry_fill_ts"]), "stop_active_entry_bar": True,
            "round_trip_cost_usd": COST, "reversal_source_candidate_id": reversal_source,
            **result}
        trades.append(row)
        consume_through = int(result["exit_fill_ts"])
        if result["exit_reason"] == "opposite_w4_signal_exit":
            signal_id = result["w4_signal_candidate_id"]
            signal = by_id.loc[signal_id]
            consume_through = max(consume_through, int(signal.candidate_fill_time))
            if lifecycle_exit == "w4_reverse":
                pending_reverse = signal
        idx = max(idx, int(np.searchsorted(candidate_times, consume_through, side="right")))
    out = pd.DataFrame(trades)
    if not out.empty:
        ordered = out.sort_values(["entry_fill_ts", "exit_fill_ts"], kind="stable")
        if (ordered.entry_fill_ts.iloc[1:].to_numpy(np.int64)
                < ordered.exit_fill_ts.iloc[:-1].to_numpy(np.int64)).any():
            raise RuntimeError("one-position constraint violated")
    return out, pd.DataFrame(evaluations)


def opportunity_metadata(candidates: pd.DataFrame) -> pd.DataFrame:
    first = candidates[candidates.candidate_seq == 1].copy()
    return first[["year", "opportunity_id", "direction", "session", "regime_start_ns",
                  "confirm_flip_ns", "candidate_time"]].rename(columns={"session": "opportunity_session"})


def max_drawdown(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    pnl = trades.sort_values(["exit_fill_ts", "entry_fill_ts"], kind="stable").net_pnl_usd.to_numpy(float)
    equity = np.cumsum(pnl)
    peaks = np.maximum.accumulate(np.r_[0.0, equity])[:-1]
    return float(np.max(peaks - equity))


def metric_row(policy_id: str, split_type: str, split_value: str,
               opp: pd.DataFrame, trades: pd.DataFrame) -> dict:
    ids = set(opp.opportunity_id)
    t = trades[trades.opportunity_id.isin(ids)].copy()
    pnl_by_opp = t.groupby("opportunity_id").net_pnl_usd.sum().reindex(opp.opportunity_id, fill_value=0.0)
    wins, losses = t[t.net_pnl_usd > 0], t[t.net_pnl_usd < 0]
    gross_win, gross_loss = float(wins.net_pnl_usd.sum()), float(-losses.net_pnl_usd.sum())
    aligned_attempts = t[t.reached_aligning_flip].sort_values("attempt_number").groupby("opportunity_id").first()
    return {"policy_id": policy_id, "split_type": split_type, "split_value": split_value,
        "opportunities": len(opp), "total_trades": len(t),
        "total_net_pnl_usd": float(t.net_pnl_usd.sum()),
        "mean_pnl_per_opportunity_usd": float(t.net_pnl_usd.sum() / len(opp)) if len(opp) else np.nan,
        "mean_pnl_per_trade_usd": float(t.net_pnl_usd.mean()) if len(t) else np.nan,
        "profit_factor": gross_win / gross_loss if gross_loss else np.nan,
        "win_rate_per_trade": float((t.net_pnl_usd > 0).mean()) if len(t) else np.nan,
        "win_rate_per_opportunity": float((pnl_by_opp > 0).mean()) if len(opp) else np.nan,
        "stop_rate": float(t.exit_reason.str.contains("stop").mean()) if len(t) else np.nan,
        "timeout_rate": float(t.exit_reason.eq("confirmation_timeout_exit").mean()) if len(t) else np.nan,
        "w4_exit_count": int(t.exit_reason.eq("opposite_w4_signal_exit").sum()),
        "w4_reversal_count": int(t.reversal_source_candidate_id.notna().sum()),
        "average_winner_usd": float(wins.net_pnl_usd.mean()) if len(wins) else np.nan,
        "average_loser_usd": float(losses.net_pnl_usd.mean()) if len(losses) else np.nan,
        "max_closed_trade_sequence_drawdown_usd": max_drawdown(t),
        "average_trades_per_opportunity": len(t) / len(opp) if len(opp) else np.nan,
        "average_attempts_before_alignment": float(aligned_attempts.attempt_number.mean())
            if len(aligned_attempts) else np.nan,
        "max_attempts_in_any_opportunity": int(t.groupby("opportunity_id").attempt_number.max().max())
            if len(t) else 0,
        "total_round_trip_costs_usd": float(len(t) * COST)}


def summarize(trades: pd.DataFrame, opportunities: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy_id in ["BASELINE", "S1", "S2", "S3", "S4"]:
        t = trades[trades.policy_id == policy_id]
        splits = [("combined", "ALL", opportunities)]
        splits += [("year", str(y), opportunities[opportunities.year == y]) for y in (2025, 2026)]
        splits += [("direction", d, opportunities[opportunities.direction == d])
                   for d in ("long_fade", "short_fade")]
        splits += [("session", s, opportunities[opportunities.opportunity_session == s])
                   for s in ("ETH", "RTH")]
        splits += [("direction_session", f"{d}_{s}", opportunities[
            (opportunities.direction == f"{d}_fade") & (opportunities.opportunity_session == s)])
            for d in ("long", "short") for s in ("ETH", "RTH")]
        for split_type, split_value, opp in splits:
            rows.append(metric_row(policy_id, split_type, split_value, opp, t))
    return pd.DataFrame(rows)


def attempt_accounting(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy_id in ["BASELINE", "S1", "S2", "S3", "S4"]:
        p = trades[trades.policy_id == policy_id]
        for split, subset in [("combined", p), ("2025", p[p.year == 2025]),
                              ("2026", p[p.year == 2026])]:
            successful = subset[subset.reached_aligning_flip].sort_values(
                ["opportunity_id", "attempt_number"]).groupby("opportunity_id").first()
            pre_success_by_bucket = {"attempt_1": 0.0, "attempt_2": 0.0,
                                     "attempt_3": 0.0, "attempt_4_plus": 0.0}
            for opp_id, success in successful.iterrows():
                n = int(success.attempt_number)
                bucket = f"attempt_{n}" if n <= 3 else "attempt_4_plus"
                pre_success_by_bucket[bucket] += subset[(subset.opportunity_id == opp_id)
                    & (subset.attempt_number < n)].net_pnl_usd.sum()
            recovered_by_bucket = {"attempt_1": 0, "attempt_2": 0,
                                   "attempt_3": 0, "attempt_4_plus": 0}
            for _, group in subset.groupby("opportunity_id"):
                group = group.sort_values("attempt_number")
                early_stop = group.exit_reason.isin(
                    ["stop_before_aligned_flip", "preflip_policy_stop"])
                if early_stop.any():
                    first_stop_attempt = int(group.loc[early_stop, "attempt_number"].min())
                    cumulative = group.net_pnl_usd.cumsum()
                    recovered = group[(group.attempt_number > first_stop_attempt) & (cumulative > 0)]
                    if len(recovered):
                        n = int(recovered.attempt_number.iloc[0])
                        bucket = f"attempt_{n}" if n <= 3 else "attempt_4_plus"
                        recovered_by_bucket[bucket] += 1
            recovered_total = int(sum(recovered_by_bucket.values()))
            for bucket, mask in [("attempt_1", subset.attempt_number == 1),
                                 ("attempt_2", subset.attempt_number == 2),
                                 ("attempt_3", subset.attempt_number == 3),
                                 ("attempt_4_plus", subset.attempt_number >= 4)]:
                g = subset[mask]
                rows.append({"policy_id": policy_id, "split": split, "attempt_bucket": bucket,
                    "attempt_count": len(g), "total_net_pnl_usd": float(g.net_pnl_usd.sum()),
                    "win_rate": float((g.net_pnl_usd > 0).mean()) if len(g) else np.nan,
                    "stopped_before_alignment_count": int(g.exit_reason.isin(
                        ["stop_before_aligned_flip", "preflip_policy_stop"]).sum()),
                    "successful_alignment_count": int(g.reached_aligning_flip.sum()),
                    "successful_alignment_rate": float(g.reached_aligning_flip.mean()) if len(g) else np.nan,
                    "cumulative_pnl_before_final_success_usd": float(pre_success_by_bucket[bucket]),
                    "opportunities_early_stop_recovered_by_this_attempt": recovered_by_bucket[bucket],
                    "opportunities_early_stop_recovered_total": recovered_total})
    return pd.DataFrame(rows)


def lifecycle_accounting(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy_id in ("S2", "S3"):
        p = trades[trades.policy_id == policy_id]
        by_source = p[p.reversal_source_candidate_id.notna()].set_index("reversal_source_candidate_id")
        for t in p[p.exit_reason == "opposite_w4_signal_exit"].itertuples(index=False):
            reverse = by_source.loc[t.w4_signal_candidate_id] if t.w4_signal_candidate_id in by_source.index else None
            change = float(t.w4_exit_change_usd)
            cf = float(t.counterfactual_regime_exit_pnl_usd)
            rows.append({"row_type": "trade", "policy_id": policy_id, "year": int(t.year),
                "trade_id": t.trade_id, "opportunity_id": t.opportunity_id,
                "w4_signal_candidate_id": t.w4_signal_candidate_id,
                "w4_exit_fill_ts": int(t.exit_fill_ts), "pnl_at_w4_exit_usd": float(t.net_pnl_usd),
                "baseline_regime_exit_pnl_usd": cf, "w4_exit_change_usd": change,
                "winner_protected": bool(t.net_pnl_usd > 0 and change > 0),
                "runner_clipped": bool(cf > t.net_pnl_usd and cf > 0),
                "planned_loser_avoided": bool(cf < 0 and change > 0),
                "reverse_entry_executed": reverse is not None,
                "reverse_entry_net_pnl_usd": float(reverse.net_pnl_usd) if reverse is not None else np.nan,
                "reverse_entry_won": bool(reverse.net_pnl_usd > 0) if reverse is not None else False,
                "reverse_entry_lost": bool(reverse.net_pnl_usd < 0) if reverse is not None else False})
    detail = pd.DataFrame(rows)
    summaries = []
    for policy_id in ("S2", "S3"):
        g = detail[detail.policy_id == policy_id] if len(detail) else detail
        summaries.append({"row_type": "summary", "policy_id": policy_id, "year": pd.NA,
            "aligned_trades_exited_by_w4": len(g),
            "total_pnl_at_w4_exit_usd": float(g.pnl_at_w4_exit_usd.sum()) if len(g) else 0.0,
            "total_baseline_regime_exit_pnl_usd": float(g.baseline_regime_exit_pnl_usd.sum()) if len(g) else 0.0,
            "total_w4_exit_change_usd": float(g.w4_exit_change_usd.sum()) if len(g) else 0.0,
            "winners_protected": int(g.winner_protected.sum()) if len(g) else 0,
            "runners_clipped": int(g.runner_clipped.sum()) if len(g) else 0,
            "planned_losers_avoided": int(g.planned_loser_avoided.sum()) if len(g) else 0,
            "reverse_entries": int(g.reverse_entry_executed.sum()) if len(g) else 0,
            "reverse_winners": int(g.reverse_entry_won.sum()) if len(g) else 0,
            "reverse_losers": int(g.reverse_entry_lost.sum()) if len(g) else 0})
    return pd.concat([detail, pd.DataFrame(summaries)], ignore_index=True, sort=False)


def independent_first_candidate_replay(year: int, raw: pd.DataFrame,
                                       candidates: pd.DataFrame) -> pd.DataFrame:
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
    rows = []
    for c in candidates[candidates.candidate_seq == 1].itertuples(index=False):
        c = pd.Series(c._asdict())
        gate = gate_candidate(c, raw, 0)
        scheduled = next_ends.get(int(c.confirm_flip_ns))
        if not gate["accepted"] or scheduled is None:
            continue
        result = simulate_path(c, int(gate["entry_fill_ts"]), float(gate["entry_fill_px"]),
                               raw, int(scheduled), None)
        rows.append({"year": year, "opportunity_id": c.opportunity_id,
            "candidate_id": c.candidate_id, "entry_direction": int(c.entry_direction),
            "entry_fill_ts": int(gate["entry_fill_ts"]), **result})
    return pd.DataFrame(rows)


def overlap_audit(year: int, raw: pd.DataFrame, candidates: pd.DataFrame,
                  baseline: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ordered = baseline.sort_values("entry_fill_ts").reset_index(drop=True)
    starts = ordered.entry_fill_ts.to_numpy(np.int64)
    during, opposite = 0, 0
    for c in candidates.itertuples(index=False):
        j = int(np.searchsorted(starts, int(c.candidate_time), side="right")) - 1
        if j >= 0 and int(c.candidate_time) < int(ordered.iloc[j].exit_fill_ts):
            if c.candidate_id != ordered.iloc[j].candidate_id:
                during += 1
                is_opposite = int(c.entry_direction) == -int(ordered.iloc[j].entry_direction)
                opposite += int(is_opposite)
                rows.append({"row_type": "candidate_during_baseline_position", "year": year,
                    "candidate_id": c.candidate_id, "open_trade_id": ordered.iloc[j].trade_id,
                    "candidate_time": int(c.candidate_time), "opposite_existing_position": is_opposite})
    independent = independent_first_candidate_replay(year, raw, candidates)
    events = []
    for t in independent.itertuples(index=False):
        events.append((int(t.entry_fill_ts), 1, int(t.entry_direction)))
        events.append((int(t.exit_fill_ts), 0, -int(t.entry_direction)))
    gross = net = max_gross = max_abs_net = 0
    offsetting_events = 0
    for event_ts, entry_order, direction_change in sorted(events, key=lambda x: (x[0], x[1])):
        if entry_order == 0:
            gross -= 1
        else:
            gross += 1
        net += direction_change
        max_gross, max_abs_net = max(max_gross, gross), max(max_abs_net, abs(net))
        if gross > abs(net):
            offsetting_events += 1
    rows.append({"row_type": "summary", "year": year,
        "new_candidate_while_baseline_open_count": during,
        "opposite_candidate_while_baseline_open_count": opposite,
        "current_accounting_treats_as_independent": False,
        "current_rule": "frozen_overlap_suppression_and_busy_until",
        "independent_first_candidate_trade_count": len(independent),
        "one_position_baseline_trade_count": len(baseline),
        "maximum_simultaneous_theoretical_positions": max_gross,
        "maximum_absolute_netted_position_units": max_abs_net,
        "offsetting_exposure_event_count": offsetting_events,
        "independent_total_net_pnl_usd": float(independent.net_pnl_usd.sum()),
        "one_position_total_net_pnl_usd": float(baseline.net_pnl_usd.sum()),
        "independent_minus_one_position_pnl_usd": float(independent.net_pnl_usd.sum()
                                                       - baseline.net_pnl_usd.sum())})
    return pd.DataFrame(rows)


def reconciliation(year: int, candidates: pd.DataFrame, trades: pd.DataFrame,
                   summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    baseline = trades[(trades.policy_id == "BASELINE") & (trades.year == year)]
    prior_opp = pd.read_parquet(MULTI / "results" / "multi_candidate_opportunity_results.parquet")
    prior_r0 = prior_opp[(prior_opp.policy_id == "R0") & (prior_opp.year == year) & prior_opp.executed]
    rows.append({"year": year, "check": "baseline_policy_a_exact",
        "expected_count": len(prior_r0), "actual_count": len(baseline),
        "expected_pnl_usd": float(prior_r0.net_pnl_usd.sum()),
        "actual_pnl_usd": float(baseline.net_pnl_usd.sum()),
        "difference_usd": float(baseline.net_pnl_usd.sum() - prior_r0.net_pnl_usd.sum())})
    rows.append({"year": year, "check": "multi_candidate_count_exact",
        "expected_count": {2025: 8682, 2026: 3130}[year], "actual_count": len(candidates)})
    rows.append({"year": year, "check": "opportunity_count_exact",
        "expected_count": {2025: 3530, 2026: 1237}[year],
        "actual_count": candidates.opportunity_id.nunique()})
    combined_prior = pd.read_parquet(MULTI / "results" / "multi_candidate_policy_results.parquet")
    for policy_id, prior_id in (("S1", "R0"), ("S4", "R10")):
        new = summary[(summary.policy_id == policy_id) & (summary.split_type == "year")
                      & (summary.split_value == str(year))].iloc[0]
        old = combined_prior[(combined_prior.policy_id == prior_id) & (combined_prior.split_type == "year")
                             & (combined_prior.split_value == str(year))].iloc[0]
        rows.append({"year": year, "check": f"{policy_id}_versus_prior_{prior_id}",
            "expected_count": int(old.trades_executed), "actual_count": int(new.total_trades),
            "expected_pnl_usd": float(old.total_net_pnl_usd),
            "actual_pnl_usd": float(new.total_net_pnl_usd),
            "difference_usd": float(new.total_net_pnl_usd - old.total_net_pnl_usd),
            "attribution": "streaming_reentry_and_one_position_lifecycle"})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "config": sha256_file(CONFIG_PATH),
            "freeze": sha256_file(FREEZE_PATH), "audit": sha256_file(PRE_AUDIT),
            "authorization": sha256_file(PRE_AUTH), "raw_2025": sha256_file(RAW_1S[2025]),
            "candidates_2025": sha256_file(candidate_path(2025))}


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
    raw = pd.read_parquet(RAW_1S[args.year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    candidates = load_candidates(args.year)
    opportunities = opportunity_metadata(candidates)
    logs = [baseline_log(args.year)]
    evals = []
    for p in config["policies"][1:]:
        trades, evaluations = replay_stream(args.year, raw, candidates, p["policy_id"],
                                             int(p["entry_delay_seconds"]), p["lifecycle_exit"])
        logs.append(trades)
        evals.append(evaluations)
    trade_log = pd.concat(logs, ignore_index=True, sort=False)
    candidate_evals = pd.concat(evals, ignore_index=True, sort=False)
    year_summary = summarize(trade_log, opportunities)
    paths = {
        f"trade_log_{args.year}.parquet": trade_log,
        f"candidate_evaluations_{args.year}.parquet": candidate_evals,
        f"opportunities_{args.year}.parquet": opportunities,
        f"overlap_audit_{args.year}.parquet": overlap_audit(
            args.year, raw, candidates, logs[0]),
        f"policy_results_{args.year}.parquet": year_summary,
    }
    for name, frame in paths.items():
        frame.to_parquet(WORK / name, index=False)
    seal = {"year": args.year, "blocking_errors": 0,
        "candidate_count": len(candidates), "opportunity_count": len(opportunities),
        "trade_count_by_policy": trade_log.groupby("policy_id").size().astype(int).to_dict(),
        "dependency_hashes_2025": dependency_hashes_2025(),
        "artifact_sha256": {name: sha256_file(WORK / name) for name in paths}}
    (WORK / f"reconciliation_{args.year}.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    if args.year == 2026:
        trades_all = pd.concat([pd.read_parquet(WORK / "trade_log_2025.parquet"),
                                pd.read_parquet(WORK / "trade_log_2026.parquet")], ignore_index=True)
        opp_all = pd.concat([pd.read_parquet(WORK / "opportunities_2025.parquet"),
                            pd.read_parquet(WORK / "opportunities_2026.parquet")], ignore_index=True)
        overlap_all = pd.concat([pd.read_parquet(WORK / "overlap_audit_2025.parquet"),
                                pd.read_parquet(WORK / "overlap_audit_2026.parquet")], ignore_index=True)
        results = summarize(trades_all, opp_all)
        outputs = {
            "streaming_portfolio_policy_results.parquet": results,
            "streaming_portfolio_trade_log.parquet": trades_all,
            "streaming_portfolio_attempt_accounting.parquet": attempt_accounting(trades_all),
            "streaming_portfolio_lifecycle_exit_accounting.parquet": lifecycle_accounting(trades_all),
            "streaming_portfolio_overlap_audit.parquet": overlap_all,
            "streaming_portfolio_reconciliation.parquet": pd.concat([
                reconciliation(2025, load_candidates(2025), trades_all, results),
                reconciliation(2026, candidates, trades_all, results)], ignore_index=True),
        }
        for name, frame in outputs.items():
            frame.to_parquet(RESULTS / name, index=False)
        manifest = {"status": "OUTPUTS_COMPLETE_PENDING_REPORT_AND_COMPLETION_AUDIT",
            "policies": ["BASELINE", "S1", "S2", "S3", "S4"],
            "opportunity_count": len(opp_all), "runner_sha256": script_sha256(),
            "config_sha256": sha256_file(CONFIG_PATH), "freeze_sha256": sha256_file(FREEZE_PATH),
            "output_sha256": {name: sha256_file(RESULTS / name) for name in outputs}}
        (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(candidates):,} candidates; "
          f"{dict(trade_log.groupby('policy_id').size())}")


if __name__ == "__main__":
    main()
