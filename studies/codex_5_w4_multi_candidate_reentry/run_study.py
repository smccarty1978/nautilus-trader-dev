"""Collect and replay fixed W4 multi-candidate R0/R10/R30 policies."""
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
PRE_AUDIT, PRE_AUTH = AUDIT / "pre_execution_audit.md", AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
ISOLATION = ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
PRIOR_PR = ROOT / "studies" / "codex_5_w4_price_response_delayed_entry"
NS, TIMEOUT_NS = 1_000_000_000, 300_000_000_000
MULTIPLIER, COST = 20.0, 10.0
POLICY_A_ID = "POLICY_A_COMBINED_1P25_300S"

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file, year_atlas_path  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, load_checkpoint_stream,
    progress_window_counts, strict_threshold_cross, validate_raw_bars,
)

for directory in (RESULTS, WORK, AUDIT):
    directory.mkdir(parents=True, exist_ok=True)


def score_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def frozen_candidate_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_candidates.parquet"


def frozen_trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def require_authorization() -> None:
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists():
        raise RuntimeError("missing pre-execution authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    if not (re.search(r"^\*\*Status:\*\*\s+\*\*PASS(?:\s|\*|-|\u2014)", text, re.MULTILINE)
            and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                          text, re.MULTILINE)):
        raise RuntimeError("pre-execution audit is not a clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_sha256(),
                "config_sha256": sha256_file(CONFIG_PATH),
                "freeze_sha256": sha256_file(FREEZE_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(key) != value for key, value in expected.items()):
        raise RuntimeError("pre-execution authorization is stale")


def input_hashes() -> dict:
    return {
        "2025_raw": sha256_file(RAW_1S[2025]), "2026_raw": sha256_file(RAW_1S[2026]),
        "2025_atlas": sha256_file(year_atlas_path(2025)),
        "2026_atlas": sha256_file(year_atlas_path(2026)),
        "2025_scores": sha256_file(score_path(2025)), "2026_scores": sha256_file(score_path(2026)),
        "2025_frozen_candidates": sha256_file(frozen_candidate_path(2025)),
        "2026_frozen_candidates": sha256_file(frozen_candidate_path(2026)),
        "2025_frozen_trades": sha256_file(frozen_trade_path(2025)),
        "2026_frozen_trades": sha256_file(frozen_trade_path(2026)),
        "policy_a_isolation_diffs": sha256_file(ISOLATION / "results" / "isolation_trade_diffs.parquet"),
        "prior_pr_trade_diffs": sha256_file(PRIOR_PR / "results" / "price_response_trade_diffs.parquet"),
        "prior_pr_policy_results": sha256_file(PRIOR_PR / "results" / "price_response_policy_results.parquet"),
        "prior_pr_completion_audit": sha256_file(PRIOR_PR / "audit" / "completion_audit.md"),
        "prior_pr_manifest": sha256_file(PRIOR_PR / "results" / "run_manifest.json"),
        "upstream_candidate_runner": sha256_file(REPAIR / "CODEX_5_X_run_established_fade.py"),
        "upstream_policy": sha256_file(REPAIR / "CODEX_5_X_established_fade_policy.json"),
    }


def validate_contract() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_ANY_NEW_CODE_TEST_OR_EXECUTION":
        raise RuntimeError("inactive input freeze")
    if input_hashes() != freeze.get("input_sha256"):
        raise RuntimeError("frozen dependency mismatch")
    if (freeze.get("current_candidate_count") != 4767
            or freeze.get("current_policy_a_trade_count") != 4383
            or freeze.get("current_candidate_count_by_year") != {"2025": 3530, "2026": 1237}
            or freeze.get("current_policy_a_trade_count_by_year") != {"2025": 3246, "2026": 1137}):
        raise RuntimeError("frozen population cardinality changed")
    if [(p.get("policy_id"), p.get("delay_seconds")) for p in config.get("policies", [])] != [
            ("R0", 0), ("R10", 10), ("R30", 30)]:
        raise RuntimeError("unexpected policy set")
    fixed = {"virtual_directional_pnl_threshold_points": 0.0,
             "max_regime_age_seconds": 1800, "opportunity_reopen_after_filter_end": False,
             "crossings_during_confirmation_wait": "not_queued",
             "acceptance_consumes_opportunity_before_global_overlap": True,
             "timeout_anchor": "actual_accepted_entry", "timeout_seconds": 300,
             "preflip_stop_atr": 1.25, "postflip_stop_atr": 1.5,
             "atr_denominator": "atr_at_checkpoint"}
    if any(config.get(k) != v for k, v in fixed.items()):
        raise RuntimeError("execution contract changed")
    return config


def established_state(cp, progress: int, filt: dict) -> tuple[bool, float]:
    retained = float(cp.current_pnl) / float(cp.current_mfe) if cp.current_mfe > 0 else np.nan
    state = bool(float(cp.regime_age) >= filt["regime_age_s_min"]
                 and float(cp.current_mfe) >= filt["running_mfe_atr_min"]
                 and int(progress) >= filt["new_progress_windows_min"]
                 and retained >= filt["retained_mfe_ratio_min"])
    return state, retained


def collect_candidates(year: int, raw: pd.DataFrame, policy: dict,
                       max_age_seconds: int = 1800) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scalar causal collection; candidate 1 reproduces the frozen collector."""
    stream = load_checkpoint_stream(year, policy)
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[c].to_numpy(float) for c in ("open", "high", "low"))
    filt = policy["filter"]
    candidates, audit = [], []
    for regime_start, group in stream.groupby("regime_start_ns", sort=False):
        group = group.sort_values("observation_time", kind="stable")
        first = group.iloc[0]
        start_ts, regime_end = int(first.entry_ts_event), int(first.regime_end_ns)
        direction, atr_entry, anchor = int(first.direction), float(first.atr_at_entry), float(first.entry_open)
        a, b = int(np.searchsorted(ts, start_ts, side="left")), int(np.searchsorted(ts, regime_end, side="left"))
        if a >= b or int(ts[a]) != start_ts:
            raise RuntimeError(f"invalid regime raw path: {regime_start}")
        favorable = highs[a:b] - anchor if direction == 1 else anchor - lows[a:b]
        running = np.maximum.accumulate(np.maximum(favorable / atr_entry, 0.0))
        progress = progress_window_counts(running, ts[a:b])
        previous_score = None
        started, active, seq = False, False, 0
        opportunity_id = f"{year}_{int(regime_start)}"
        regime_candidate_indexes = []
        end_ts, end_reason = regime_end, "regime_ended"
        horizon_ts = int(regime_start) + max_age_seconds * NS

        for cp in group.itertuples(index=False):
            decision = int(cp.observation_time)
            score, threshold = float(cp.w4_score), float(cp.direction_threshold)
            crossed = strict_threshold_cross(previous_score, score, threshold)
            previous_score = score
            k = int(np.searchsorted(ts[a:b], decision, side="left") - 1)
            if k < 0 or decision >= regime_end:
                if crossed:
                    audit.append({"row_type": "strict_crossing", "year": year,
                        "regime_start_ns": int(regime_start), "decision_ts": decision,
                        "candidate_emitted": False, "generation_reason": "cross_not_before_flip"})
                continue
            if not np.isclose(float(running[k]), float(cp.current_mfe), rtol=0, atol=1e-9):
                raise RuntimeError(f"checkpoint/raw MFE mismatch: {decision}")
            established, retained = established_state(cp, int(progress[k]), filt)

            if started and active and decision > candidates[regime_candidate_indexes[0]]["candidate_time"]:
                if decision > horizon_ts:
                    active, end_ts, end_reason = False, horizon_ts, "score_horizon_ended"
                elif not established:
                    active, end_ts, end_reason = False, decision, "established_filter_ended"

            emitted = False
            reason = "no_strict_cross"
            if crossed:
                if not started and established:
                    started, active = True, True
                if started and active and established and decision <= horizon_ts:
                    seq += 1
                    fill_i = int(np.searchsorted(ts, decision, side="left"))
                    fill_ts = int(ts[fill_i]) if fill_i < len(ts) else None
                    fill_px = float(opens[fill_i]) if fill_i < len(ts) else np.nan
                    candidate_id = f"{opportunity_id}_c{seq:03d}"
                    row = {"year": year, "opportunity_id": opportunity_id,
                        "candidate_id": candidate_id, "candidate_seq": seq,
                        "regime_start_ns": int(regime_start), "confirm_flip_ns": regime_end,
                        "prevailing_direction": direction, "entry_direction": -direction,
                        "candidate_time": decision, "candidate_fill_time": fill_ts,
                        "candidate_fill_price": fill_px, "w4_score": score,
                        "threshold": threshold, "score_margin": score - threshold,
                        "atr_at_checkpoint": float(cp.atr_at_checkpoint),
                        "regime_age_s": float(cp.regime_age), "running_mfe_atr": float(cp.current_mfe),
                        "running_mae_atr": float(cp.current_mae),
                        "new_progress_windows": int(progress[k]), "retained_mfe_ratio": retained,
                        "direction": "long_fade" if -direction == 1 else "short_fade",
                        "session": "RTH" if fill_ts is not None and is_rth(fill_ts) else "ETH"}
                    candidates.append(row)
                    regime_candidate_indexes.append(len(candidates) - 1)
                    emitted, reason = True, "candidate"
                elif not started:
                    reason = "filter_fail_before_opportunity"
                else:
                    reason = "after_opportunity_end"
                audit.append({"row_type": "strict_crossing", "year": year,
                    "regime_start_ns": int(regime_start), "decision_ts": decision,
                    "opportunity_id": opportunity_id if started else None,
                    "candidate_emitted": emitted, "candidate_seq": seq if emitted else pd.NA,
                    "generation_reason": reason, "established_filter": established,
                    "w4_score": score, "threshold": threshold, "score_margin": score - threshold,
                    "regime_age_s": float(cp.regime_age), "running_mfe_atr": float(cp.current_mfe),
                    "new_progress_windows": int(progress[k]), "retained_mfe_ratio": retained})

        if started:
            if active:
                if horizon_ts < regime_end:
                    end_ts, end_reason = horizon_ts, "score_horizon_ended"
                else:
                    end_ts, end_reason = regime_end, "regime_ended"
            for idx in regime_candidate_indexes:
                candidates[idx]["opportunity_end_ts"] = int(end_ts)
                candidates[idx]["opportunity_end_reason"] = end_reason
                candidates[idx]["candidate_count_in_opportunity"] = seq
    frame = pd.DataFrame(candidates).sort_values(["candidate_time", "candidate_seq"]).reset_index(drop=True)
    if len(frame) and frame[["opportunity_id", "candidate_seq"]].duplicated().any():
        raise RuntimeError("duplicate candidate sequence")
    return frame, pd.DataFrame(audit)


def reconcile_first_candidates(year: int, candidates: pd.DataFrame, raw: pd.DataFrame) -> dict:
    first = candidates[candidates.candidate_seq == 1].sort_values("candidate_time").reset_index(drop=True)
    frozen = pd.read_parquet(frozen_candidate_path(year)).sort_values("decision_ts").reset_index(drop=True)
    if len(first) != len(frozen):
        raise RuntimeError("regenerated first-candidate count mismatch")
    expected_count = {2025: 3530, 2026: 1237}[year]
    if len(first) != expected_count or len(frozen) != expected_count:
        raise RuntimeError("frozen first-candidate cardinality invariant failed")
    exact = [("regime_start_ns", "regime_start_ns"), ("candidate_time", "decision_ts"),
             ("confirm_flip_ns", "confirm_flip_ns"), ("entry_direction", "entry_direction")]
    mismatches = sum(int((first[a].to_numpy() != frozen[b].to_numpy()).sum()) for a, b in exact)
    floats = [("w4_score", "w4_score"), ("threshold", "direction_threshold"),
              ("atr_at_checkpoint", "atr_at_checkpoint")]
    mismatches += sum(int((~np.isclose(first[a], frozen[b], rtol=0, atol=1e-12)).sum()) for a, b in floats)
    ts = raw.index.view(np.int64)
    opens = raw.open.to_numpy(float)
    fill_indexes = np.searchsorted(ts, frozen.decision_ts.to_numpy(np.int64), side="left")
    expected_fill_ts = ts[fill_indexes]
    expected_fill_px = opens[fill_indexes]
    fill_ts_mismatches = int((first.candidate_fill_time.to_numpy(np.int64) != expected_fill_ts).sum())
    fill_px_mismatches = int((~np.isclose(first.candidate_fill_price, expected_fill_px,
                                          rtol=0, atol=1e-12)).sum())
    direction_mismatches = int((first.direction.to_numpy() != np.where(
        frozen.entry_direction.to_numpy(int) == 1, "long_fade", "short_fade")).sum())
    session_mismatches = int((first.session.to_numpy() != np.array([
        "RTH" if is_rth(int(x)) else "ETH" for x in expected_fill_ts])).sum())
    mismatches += fill_ts_mismatches + fill_px_mismatches + direction_mismatches + session_mismatches
    if mismatches:
        raise RuntimeError(f"first-candidate field mismatch: {mismatches}")
    return {"old_first_crossing_candidate_count": len(frozen),
            "regenerated_first_candidate_count": len(first), "matched_entries": len(first),
            "unmatched_entries": 0, "timestamp_mismatches": 0,
            "fill_timestamp_mismatches": fill_ts_mismatches,
            "fill_price_mismatches": fill_px_mismatches,
            "direction_mismatches": direction_mismatches, "session_mismatches": session_mismatches,
            "field_mismatches": 0}


def select_candidates(candidates: pd.DataFrame, raw: pd.DataFrame,
                      policy_id: str, delay_seconds: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ts = raw.index.view(np.int64)
    opens, closes = raw.open.to_numpy(float), raw.close.to_numpy(float)
    eval_rows, selections = [], []
    for opportunity_id, group in candidates.groupby("opportunity_id", sort=False):
        group = group.sort_values("candidate_seq")
        evaluation_start = len(eval_rows)
        cursor = -1
        accepted = None
        terminal_reason = "all_candidates_exhausted"
        for c in group.itertuples(index=False):
            base = {"row_type": "candidate_evaluation", "policy_id": policy_id,
                    "year": int(c.year), "opportunity_id": opportunity_id,
                    "candidate_id": c.candidate_id, "candidate_seq": int(c.candidate_seq)}
            if accepted is not None:
                eval_rows.append({**base, "evaluated": False, "accepted": False,
                                  "evaluation_reason": "not_evaluated_after_acceptance"})
                continue
            if int(c.candidate_time) <= cursor:
                eval_rows.append({**base, "evaluated": False, "accepted": False,
                                  "evaluation_reason": "not_queued_during_confirmation_wait"})
                continue
            if c.candidate_fill_time is None or pd.isna(c.candidate_fill_time):
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                                  "evaluation_reason": "score_unavailable"})
                terminal_reason = "score_unavailable"
                break
            would_ts, would_px = int(c.candidate_fill_time), float(c.candidate_fill_price)
            if delay_seconds == 0:
                if would_ts >= int(c.confirm_flip_ns):
                    eval_rows.append({**base, "evaluated": True, "accepted": False,
                        "evaluation_reason": "aligning_flip_before_delayed_entry"})
                    terminal_reason = "aligning_flip_before_delayed_entry"
                    break
                accepted = {**c._asdict(), "policy_id": policy_id,
                            "actual_entry_fill_ts": would_ts, "actual_entry_fill_price": would_px,
                            "gate_decision_ts": int(c.candidate_time),
                            "virtual_directional_pnl_points": 0.0,
                            "directional_fill_change_points": 0.0}
                eval_rows.append({**base, "evaluated": True, "accepted": True,
                                  "evaluation_reason": "accepted", "gate_decision_ts": int(c.candidate_time),
                                  "actual_entry_fill_ts": would_ts, "actual_entry_fill_price": would_px})
                terminal_reason = "accepted"
                continue

            gate_ts = would_ts + delay_seconds * NS
            cursor = gate_ts
            if int(c.confirm_flip_ns) <= gate_ts:
                reason = "regime_ended_before_confirmation"
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                                  "evaluation_reason": reason, "gate_decision_ts": gate_ts})
                terminal_reason = reason
                break
            if int(c.opportunity_end_ts) <= gate_ts:
                reason = ("score_unavailable" if c.opportunity_end_reason == "score_horizon_ended"
                          else "opportunity_ended")
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                                  "evaluation_reason": reason, "gate_decision_ts": gate_ts})
                terminal_reason = reason
                break
            mark_i = int(np.searchsorted(ts, gate_ts, side="left")) - 1
            if mark_i < 0 or int(ts[mark_i]) + NS > gate_ts:
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                    "evaluation_reason": "score_unavailable", "gate_decision_ts": gate_ts})
                terminal_reason = "score_unavailable"
                break
            virtual = int(c.entry_direction) * (float(closes[mark_i]) - would_px)
            if virtual < 0:
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                    "evaluation_reason": "adverse_virtual_response", "gate_decision_ts": gate_ts,
                    "confirmation_mark_ts": int(ts[mark_i]),
                    "virtual_directional_pnl_points": virtual})
                terminal_reason = "all_candidates_exhausted"
                continue
            entry_i = int(np.searchsorted(ts, gate_ts, side="right"))
            if entry_i >= len(ts):
                reason = "score_unavailable"
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                                  "evaluation_reason": reason, "gate_decision_ts": gate_ts})
                terminal_reason = reason
                break
            actual_ts, actual_px = int(ts[entry_i]), float(opens[entry_i])
            if actual_ts >= int(c.confirm_flip_ns):
                reason = "aligning_flip_before_delayed_entry"
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                                  "evaluation_reason": reason, "gate_decision_ts": gate_ts,
                                  "virtual_directional_pnl_points": virtual})
                terminal_reason = reason
                break
            if actual_ts >= int(c.opportunity_end_ts):
                reason = ("score_unavailable" if c.opportunity_end_reason == "score_horizon_ended"
                          else "opportunity_ended")
                eval_rows.append({**base, "evaluated": True, "accepted": False,
                                  "evaluation_reason": reason, "gate_decision_ts": gate_ts,
                                  "virtual_directional_pnl_points": virtual})
                terminal_reason = reason
                break
            fill_change = int(c.entry_direction) * (actual_px - would_px)
            accepted = {**c._asdict(), "policy_id": policy_id,
                        "actual_entry_fill_ts": actual_ts, "actual_entry_fill_price": actual_px,
                        "gate_decision_ts": gate_ts, "virtual_directional_pnl_points": virtual,
                        "directional_fill_change_points": fill_change}
            eval_rows.append({**base, "evaluated": True, "accepted": True,
                "evaluation_reason": "accepted", "gate_decision_ts": gate_ts,
                "confirmation_mark_ts": int(ts[mark_i]),
                "virtual_directional_pnl_points": virtual,
                "actual_entry_fill_ts": actual_ts, "actual_entry_fill_price": actual_px,
                "directional_fill_change_points": fill_change})
            terminal_reason = "accepted"
        first = group.iloc[0]
        opportunity_evaluations = eval_rows[evaluation_start:]
        selection = {"policy_id": policy_id, "year": int(first.year),
            "opportunity_id": opportunity_id, "direction": first.direction,
            "opportunity_session": first.session, "candidate_count": len(group),
            "evaluated_count": sum(r.get("evaluated", False) for r in opportunity_evaluations),
            "rejected_count": sum(r.get("evaluated", False) and not r.get("accepted", False)
                                  for r in opportunity_evaluations),
            "selection_reason": terminal_reason, "candidate_accepted": accepted is not None}
        if accepted is not None:
            selection.update(accepted)
        selections.append(selection)
    return pd.DataFrame(selections), pd.DataFrame(eval_rows)


def touched_stop(direction: int, stop: float, high: float, low: float) -> bool:
    return low <= stop if direction == 1 else high >= stop


def stop_fill(direction: int, stop: float, open_px: float) -> float:
    gap = open_px <= stop if direction == 1 else open_px >= stop
    return open_px if gap else stop


def simulate_trade(c: pd.Series, raw: pd.DataFrame, scheduled_decision: int) -> dict:
    ts = raw.index.view(np.int64)
    opens, highs, lows = (raw[x].to_numpy(float) for x in ("open", "high", "low"))
    entry_ts, entry = int(c.actual_entry_fill_ts), float(c.actual_entry_fill_price)
    direction, atr, align_ts = int(c.entry_direction), float(c.atr_at_checkpoint), int(c.confirm_flip_ns)
    timeout_ts = entry_ts + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled_decision, side="left"))
    if start >= len(ts) or int(ts[start]) != entry_ts or scheduled_i >= len(ts):
        raise RuntimeError("invalid entry or scheduled exit boundary")
    scheduled_fill_ts = int(ts[scheduled_i])
    pre_stop, post_stop = entry - direction * 1.25 * atr, entry - direction * 1.5 * atr
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
        stop = post_stop if aligned else pre_stop
        stop_reason = "original_stop_after_aligned_flip" if aligned else "preflip_policy_stop"
        if touched_stop(direction, stop, highs[i], lows[i]):
            exit_ts, exit_px, reason = now, stop_fill(direction, stop, opens[i]), stop_reason
            break
    if exit_ts is None:
        raise RuntimeError("trade replay ended without exit")
    points = direction * (float(exit_px) - entry)
    return {"executed": True, "actual_entry_session": "RTH" if is_rth(entry_ts) else "ETH",
            "entry_fill_ts": entry_ts, "entry_fill_px": entry,
            "stop_submission_ts": entry_ts, "stop_active_entry_bar": True,
            "timeout_ts": timeout_ts, "reached_aligning_flip": aligned,
            "exit_fill_ts": int(exit_ts), "exit_fill_px": float(exit_px), "exit_reason": reason,
            "gross_pnl_pts": points, "gross_pnl_usd": points * MULTIPLIER,
            "net_pnl_usd": points * MULTIPLIER - COST}


def execute_policy(year: int, selections: pd.DataFrame, raw: pd.DataFrame,
                   policy_id: str) -> pd.DataFrame:
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
    rows, busy_until = [], -1
    frozen_allowed = set()
    if policy_id == "R0":
        frozen_trades = pd.read_parquet(frozen_trade_path(year), columns=["regime_start_ns"])
        frozen_allowed = set(frozen_trades.regime_start_ns.astype(np.int64))
        if len(frozen_allowed) != {2025: 3246, 2026: 1137}[year]:
            raise RuntimeError("invalid frozen R0 executable opportunity set")
    selected = selections[selections.candidate_accepted].sort_values("actual_entry_fill_ts")
    selected_ids = set(selected.opportunity_id)
    for c in selected.itertuples(index=False):
        base = c._asdict()
        entry_ts = int(c.actual_entry_fill_ts)
        # Current Policy A replayed management independently over the original
        # frozen executable entries. R0 retains that population exactly.
        if policy_id == "R0" and int(c.regime_start_ns) not in frozen_allowed:
            rows.append({**base, "executed": False,
                         "execution_reason": "frozen_upstream_position_overlap",
                         "net_pnl_usd": 0.0})
            continue
        if policy_id != "R0" and entry_ts < busy_until:
            rows.append({**base, "executed": False, "execution_reason": "position_open_at_entry",
                         "net_pnl_usd": 0.0})
            continue
        value = next_ends.get(int(c.confirm_flip_ns))
        if value is None:
            raise RuntimeError("confirming regime lacks opposing flip")
        result = simulate_trade(pd.Series(base), raw, int(value))
        rows.append({**base, "execution_reason": "executed", **result})
        if policy_id != "R0":
            busy_until = (int(result["exit_fill_ts"]) + NS if "stop" in result["exit_reason"]
                          else int(result["exit_fill_ts"]))
    by_id = {r["opportunity_id"]: r for r in rows}
    complete = []
    for s in selections.itertuples(index=False):
        if s.opportunity_id in by_id:
            complete.append(by_id[s.opportunity_id])
        elif s.opportunity_id not in selected_ids:
            complete.append({**s._asdict(), "executed": False,
                             "execution_reason": "no_candidate_accepted", "net_pnl_usd": 0.0})
    return pd.DataFrame(complete).sort_values("opportunity_id").reset_index(drop=True)


def reconcile_r0(year: int, results: pd.DataFrame) -> dict:
    executed = results[results.executed].sort_values("entry_fill_ts").reset_index(drop=True)
    prior = pd.read_parquet(ISOLATION / "results" / "isolation_trade_diffs.parquet")
    prior = prior[(prior.policy_id == POLICY_A_ID) & (prior.year == year)].sort_values("entry_fill_ts").reset_index(drop=True)
    frozen_trades = pd.read_parquet(frozen_trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
    if len(executed) != len(prior):
        raise RuntimeError("R0/Policy A trade count mismatch")
    expected_count = {2025: 3246, 2026: 1137}[year]
    if len(executed) != expected_count or len(prior) != expected_count or len(frozen_trades) != expected_count:
        raise RuntimeError("frozen Policy A trade cardinality invariant failed")
    mismatches = int((executed.entry_fill_ts.to_numpy(np.int64) != prior.entry_fill_ts.to_numpy(np.int64)).sum())
    mismatches += int((executed.exit_fill_ts.to_numpy(np.int64) != prior.new_exit_fill_ts.to_numpy(np.int64)).sum())
    mismatches += int((~np.isclose(executed.net_pnl_usd, prior.new_net_pnl_usd, rtol=0, atol=1e-8)).sum())
    entry_price_mismatches = int((~np.isclose(executed.entry_fill_px, frozen_trades.entry_fill_open,
                                               rtol=0, atol=1e-12)).sum())
    exit_price_mismatches = int((~np.isclose(executed.exit_fill_px, prior.new_exit_fill_px,
                                              rtol=0, atol=1e-12)).sum())
    exit_reason_mismatches = int((executed.exit_reason.to_numpy() != prior.new_exit_reason.to_numpy()).sum())
    direction_mismatches = int((executed.entry_direction.to_numpy(int)
                                != frozen_trades.entry_direction.to_numpy(int)).sum())
    session_mismatches = int((executed.actual_entry_session.to_numpy()
                              != frozen_trades.session.to_numpy()).sum())
    mismatches += (entry_price_mismatches + exit_price_mismatches + exit_reason_mismatches
                   + direction_mismatches + session_mismatches)
    if mismatches:
        raise RuntimeError(f"R0/Policy A reconciliation mismatch: {mismatches}")
    return {"policy_a_trade_count": len(prior), "r0_trade_count": len(executed),
            "entry_timestamp_mismatches": 0, "exit_timestamp_mismatches": 0,
            "entry_price_mismatches": entry_price_mismatches,
            "exit_price_mismatches": exit_price_mismatches,
            "exit_reason_mismatches": exit_reason_mismatches,
            "direction_mismatches": direction_mismatches, "session_mismatches": session_mismatches,
            "pnl_mismatches": 0, "policy_a_total_net_pnl_usd": float(prior.new_net_pnl_usd.sum()),
            "r0_total_net_pnl_usd": float(executed.net_pnl_usd.sum())}


def build_skip_forever_diagnostic(year: int, candidates: pd.DataFrame,
                                  r0_results: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Regenerate prior candidate-1-only PR10/PR30 semantics row by row."""
    ts = raw.index.view(np.int64)
    opens, closes = raw.open.to_numpy(float), raw.close.to_numpy(float)
    first = candidates[candidates.candidate_seq == 1].set_index("opportunity_id")
    r0 = r0_results[r0_results.executed].sort_values("entry_fill_ts")
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
    prior_all = pd.read_parquet(PRIOR_PR / "results" / "price_response_trade_diffs.parquet")
    rows = []
    for policy_id, delay in (("R10", 10), ("R30", 30)):
        prior_id = policy_id.replace("R", "PR")
        prior = prior_all[(prior_all.policy_id == prior_id) & (prior_all.year == year)].copy()
        if len(prior) != len(r0):
            raise RuntimeError("prior skip-forever cardinality mismatch")
        prior = prior.set_index("original_entry_fill_ts", verify_integrity=True)
        for base in r0.itertuples(index=False):
            c = first.loc[base.opportunity_id]
            would_ts, would_px = int(c.candidate_fill_time), float(c.candidate_fill_price)
            gate_ts = would_ts + delay * NS
            approved, skip_reason = False, "adverse_virtual_response"
            actual_ts, actual_px = pd.NA, np.nan
            virtual = np.nan
            result = {"exit_fill_ts": pd.NA, "exit_fill_px": np.nan,
                      "exit_reason": "skipped", "net_pnl_usd": 0.0}
            if int(c.confirm_flip_ns) <= gate_ts:
                skip_reason = "regime_ended_by_confirmation"
            else:
                mark_i = int(np.searchsorted(ts, gate_ts, side="left")) - 1
                if mark_i < 0 or int(ts[mark_i]) + NS > gate_ts:
                    raise RuntimeError("skip-forever diagnostic lacks completed mark")
                virtual = int(c.entry_direction) * (float(closes[mark_i]) - would_px)
                if virtual >= 0:
                    entry_i = int(np.searchsorted(ts, gate_ts, side="right"))
                    if entry_i >= len(ts):
                        skip_reason = "no_later_entry_open"
                    elif int(ts[entry_i]) >= int(c.confirm_flip_ns):
                        skip_reason = "aligning_flip_before_delayed_entry"
                    else:
                        approved, skip_reason = True, "executed"
                        actual_ts, actual_px = int(ts[entry_i]), float(opens[entry_i])
                        scheduled = next_ends.get(int(c.confirm_flip_ns))
                        if scheduled is None:
                            raise RuntimeError("skip-forever diagnostic lacks opposing flip")
                        state = c.copy()
                        state["actual_entry_fill_ts"] = actual_ts
                        state["actual_entry_fill_price"] = actual_px
                        result = simulate_trade(state, raw, int(scheduled))
            p = prior.loc[int(base.entry_fill_ts)]
            mismatches = int(bool(approved) != bool(p.approved))
            mismatches += int(str(skip_reason) != str(p.skip_reason))
            if approved:
                mismatches += int(int(actual_ts) != int(p.delayed_entry_fill_ts))
                mismatches += int(not np.isclose(actual_px, float(p.delayed_entry_fill_open), rtol=0, atol=1e-12))
                mismatches += int(int(result["exit_fill_ts"]) != int(p.new_exit_fill_ts))
                mismatches += int(not np.isclose(result["exit_fill_px"], float(p.new_exit_fill_px), rtol=0, atol=1e-12))
                mismatches += int(str(result["exit_reason"]) != str(p.new_exit_reason))
            mismatches += int(not np.isclose(result["net_pnl_usd"], float(p.new_net_pnl_usd), rtol=0, atol=1e-8))
            if mismatches:
                raise RuntimeError(f"skip-forever row mismatch: {policy_id} {base.opportunity_id}")
            rows.append({"row_type": "skip_forever_diagnostic", "policy_id": policy_id,
                "year": year, "opportunity_id": base.opportunity_id,
                "candidate_id": c.candidate_id, "candidate_seq": 1,
                "direction": c.direction, "opportunity_session": c.session,
                "candidate_time": int(c.candidate_time), "candidate_fill_time": would_ts,
                "candidate_fill_price": would_px, "gate_decision_ts": gate_ts,
                "virtual_directional_pnl_points": virtual, "approved": approved,
                "executed": approved, "skip_reason": skip_reason,
                "actual_entry_fill_ts": actual_ts, "actual_entry_fill_price": actual_px,
                "exit_fill_ts": result["exit_fill_ts"], "exit_fill_px": result["exit_fill_px"],
                "exit_reason": result["exit_reason"], "net_pnl_usd": result["net_pnl_usd"],
                "prior_trade_id": p.trade_id, "prior_row_reconciled": True})
    diagnostic = pd.DataFrame(rows)
    for column in ("actual_entry_fill_ts", "exit_fill_ts"):
        diagnostic[column] = pd.array(diagnostic[column], dtype="Int64")
    return diagnostic


def add_baseline(opportunities: pd.DataFrame) -> pd.DataFrame:
    r0 = opportunities[opportunities.policy_id == "R0"][
        ["opportunity_id", "executed", "net_pnl_usd", "exit_reason", "candidate_seq"]].rename(columns={
            "executed": "r0_executed", "net_pnl_usd": "r0_net_pnl_usd",
            "exit_reason": "r0_exit_reason", "candidate_seq": "r0_candidate_seq"})
    out = opportunities.merge(r0, on="opportunity_id", how="left", validate="many_to_one")
    out["net_change_vs_r0_usd"] = out.net_pnl_usd - out.r0_net_pnl_usd
    out["accepted_sequence_bucket"] = np.where(out.get("candidate_seq", pd.Series(index=out.index)).fillna(0) >= 4,
                                                "seq_4_plus", "seq_" + out.get("candidate_seq", pd.Series(index=out.index)).fillna(0).astype(int).astype(str))
    return out


def profit_factor(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def drawdown(pnl: pd.Series) -> float:
    equity = np.concatenate(([0.0], pnl.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(equity) - equity))


def split_specs(frame: pd.DataFrame):
    interaction = frame.direction.str.replace("_fade", "", regex=False) + "_" + frame.opportunity_session
    return [("combined", pd.Series("ALL", index=frame.index)), ("year", frame.year.astype(str)),
            ("direction", frame.direction), ("session", frame.opportunity_session),
            ("direction_session", interaction)]


def summarize(opportunities: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy_id, policy in opportunities.groupby("policy_id", sort=False):
        policy = policy.sort_values(["year", "candidate_time"])
        for split_type, labels in split_specs(policy):
            for split_value, g in policy.assign(_split=labels).groupby("_split", sort=False):
                trades = g[g.executed]
                pnl, opp_pnl = trades.net_pnl_usd, g.net_pnl_usd
                rows.append({"policy_id": policy_id, "split_type": split_type,
                    "split_value": str(split_value), "opportunities": len(g),
                    "trades_executed": len(trades), "no_trade_opportunities": len(g) - len(trades),
                    "total_net_pnl_usd": float(opp_pnl.sum()),
                    "mean_pnl_per_opportunity_usd": float(opp_pnl.mean()),
                    "mean_pnl_per_executed_trade_usd": float(pnl.mean()) if len(pnl) else np.nan,
                    "profit_factor": profit_factor(pnl),
                    "win_rate_executed": float((pnl > 0).mean()) if len(pnl) else np.nan,
                    "win_rate_opportunity": float((opp_pnl > 0).mean()),
                    "stop_rate": float(trades.exit_reason.str.contains("stop").mean()) if len(trades) else np.nan,
                    "timeout_rate": float((trades.exit_reason == "confirmation_timeout_exit").mean()) if len(trades) else np.nan,
                    "average_winner_usd": float(pnl[pnl > 0].mean()) if (pnl > 0).any() else np.nan,
                    "average_loser_usd": float(pnl[pnl < 0].mean()) if (pnl < 0).any() else np.nan,
                    "max_closed_trade_sequence_drawdown_usd": drawdown(opp_pnl)})
    return pd.DataFrame(rows)


def trade_diffs(opportunities: pd.DataFrame) -> pd.DataFrame:
    out = opportunities.copy()
    out["opportunity_improved"] = out.net_change_vs_r0_usd > 1e-9
    out["opportunity_worsened"] = out.net_change_vs_r0_usd < -1e-9
    later = out.candidate_accepted & (out.candidate_seq > 1)
    out["first_entry_loser_replaced_by_later_winner"] = later & out.r0_executed & (out.r0_net_pnl_usd < 0) & out.executed & (out.net_pnl_usd > 0)
    first_executed = out.executed & out.candidate_seq.eq(1)
    out["first_entry_winner_missed"] = (out.r0_executed & (out.r0_net_pnl_usd > 0)
                                         & ~first_executed & (out.net_pnl_usd <= 0))
    out["first_entry_stop_before_loss_avoided"] = (out.r0_exit_reason == "preflip_policy_stop") & (out.net_change_vs_r0_usd > 0)
    planned_winner = ((out.r0_exit_reason == "original_opposing_flip_exit")
                      & (out.r0_net_pnl_usd > 0))
    out["first_entry_planned_winner_lost"] = planned_winner & (out.net_pnl_usd <= 0)
    out["first_entry_planned_winner_clipped"] = (planned_winner & (out.net_pnl_usd > 0)
                                                   & (out.net_change_vs_r0_usd < 0))
    out["later_candidate_winner_created"] = later & out.executed & (out.net_pnl_usd > 0)
    out["later_candidate_loser_created"] = later & out.executed & (out.net_pnl_usd < 0)
    return out


def accounting(opportunities: pd.DataFrame, evaluations: pd.DataFrame,
               skip_forever: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy_id, g in opportunities.groupby("policy_id", sort=False):
        ev = evaluations[evaluations.policy_id == policy_id]
        ev_evaluated = ev.evaluated.fillna(False).astype(bool)
        ev_accepted = ev.accepted.fillna(False).astype(bool)
        rows.append({"policy_id": policy_id, "level": "candidate", "class": "all_generated",
                     "count": int(g.candidate_count.sum())})
        rows.append({"policy_id": policy_id, "level": "candidate", "class": "evaluated",
                     "count": int(ev_evaluated.sum())})
        rows.append({"policy_id": policy_id, "level": "candidate", "class": "accepted",
                     "count": int(ev_accepted.sum())})
        rejected = ev[ev_evaluated & ~ev_accepted]
        rows.append({"policy_id": policy_id, "level": "candidate", "class": "rejected",
                     "count": len(rejected)})
        rejection_reasons = ["adverse_virtual_response", "regime_ended_before_confirmation",
            "aligning_flip_before_delayed_entry", "score_unavailable", "opportunity_ended"]
        for reason in rejection_reasons:
            rows.append({"policy_id": policy_id, "level": "candidate", "class": f"rejected_{reason}",
                         "count": int((rejected.evaluation_reason == reason).sum())})
        accepted = g[g.candidate_accepted]
        for bucket in ["seq_1", "seq_2", "seq_3", "seq_4_plus"]:
            rows.append({"policy_id": policy_id, "level": "candidate", "class": f"accepted_{bucket}",
                         "count": int((accepted.accepted_sequence_bucket == bucket).sum())})
        for label, mask in [("fill_improved", accepted.directional_fill_change_points < -1e-12),
                            ("fill_worsened", accepted.directional_fill_change_points > 1e-12),
                            ("fill_unchanged", accepted.directional_fill_change_points.abs() <= 1e-12)]:
            x = accepted[mask]
            rows.append({"policy_id": policy_id, "level": "candidate", "class": label,
                         "count": len(x), "mean_fill_change_points": float(x.directional_fill_change_points.mean()) if len(x) else np.nan})
        status_masks = [("no_trade", ~g.executed),
                        ("trade_on_first_candidate", g.executed & g.candidate_seq.eq(1)),
                        ("trade_on_later_candidate", g.executed & (g.candidate_seq > 1))]
        for label, mask in status_masks:
            x = g[mask]
            rows.append({"policy_id": policy_id, "level": "opportunity", "class": label,
                "count": len(x), "r0_total_net_pnl_usd": float(x.r0_net_pnl_usd.sum()),
                "policy_total_net_pnl_usd": float(x.net_pnl_usd.sum()),
                "net_change_usd": float(x.net_change_vs_r0_usd.sum()),
                "average_change_usd": float(x.net_change_vs_r0_usd.mean()) if len(x) else np.nan})
        executed = g[g.executed]
        rejected_buckets = pd.cut(executed.rejected_count, bins=[-1, 0, 1, 2, 3, np.inf],
                                  labels=["0", "1", "2", "3", "4_plus"])
        for bucket in ["0", "1", "2", "3", "4_plus"]:
            rows.append({"policy_id": policy_id, "level": "opportunity",
                "class": f"executed_rejected_before_accept_{bucket}",
                "count": int((rejected_buckets == bucket).sum())})
        classes = ["opportunity_improved", "opportunity_worsened",
            "first_entry_loser_replaced_by_later_winner", "first_entry_winner_missed",
            "first_entry_stop_before_loss_avoided", "first_entry_planned_winner_lost",
            "first_entry_planned_winner_clipped",
            "later_candidate_winner_created", "later_candidate_loser_created"]
        for col in classes:
            x = g[g[col]]
            rows.append({"policy_id": policy_id, "level": "opportunity", "class": col,
                "count": len(x), "r0_total_net_pnl_usd": float(x.r0_net_pnl_usd.sum()),
                "policy_total_net_pnl_usd": float(x.net_pnl_usd.sum()),
                "net_change_usd": float(x.net_change_vs_r0_usd.sum()),
                "average_change_usd": float(x.net_change_vs_r0_usd.mean()) if len(x) else np.nan})
    for policy_id in ("R10", "R30"):
        old = skip_forever[skip_forever.policy_id == policy_id]
        old_executed = old.executed.fillna(False).astype(bool)
        new = opportunities[opportunities.policy_id == policy_id]
        trades = new[new.executed]
        later = new[new.executed & (new.candidate_seq > 1)]
        rows.append({"policy_id": policy_id, "level": "prior_comparison", "class": "allow_later_candidates",
            "prior_approved_count": int(old_executed.sum()),
            "new_accepted_opportunity_count": int(new.candidate_accepted.sum()),
            "new_trade_count": len(trades),
            "prior_skipped_forever_count": int((~old_executed).sum()), "later_entry_recovery_count": len(later),
            "prior_total_net_pnl_usd": float(old.net_pnl_usd.sum()),
            "policy_total_net_pnl_usd": float(trades.net_pnl_usd.sum()),
            "net_change_usd": float(trades.net_pnl_usd.sum() - old.net_pnl_usd.sum()),
            "prior_win_rate": float((old.loc[old_executed, "net_pnl_usd"] > 0).mean()),
            "policy_win_rate": float((trades.net_pnl_usd > 0).mean()) if len(trades) else np.nan,
            "win_rate_difference": (float((trades.net_pnl_usd > 0).mean())
                                    - float((old.loc[old_executed, "net_pnl_usd"] > 0).mean()))
                                    if len(trades) else np.nan,
            "prior_short_fade_pnl_usd": float(old.loc[old.direction == "short_fade", "net_pnl_usd"].sum()),
            "new_short_fade_pnl_usd": float(new.loc[new.direction == "short_fade", "net_pnl_usd"].sum()),
            "short_fade_pnl_recovery_usd": float(
                new.loc[new.direction == "short_fade", "net_pnl_usd"].sum()
                - old.loc[old.direction == "short_fade", "net_pnl_usd"].sum()),
            "prior_long_eth_pnl_usd": float(old.loc[(old.direction == "long_fade")
                                                      & (old.opportunity_session == "ETH"), "net_pnl_usd"].sum()),
            "new_long_eth_pnl_usd": float(new.loc[(new.direction == "long_fade")
                                                    & (new.opportunity_session == "ETH"), "net_pnl_usd"].sum()),
            "long_eth_pnl_retention_change_usd": float(
                new.loc[(new.direction == "long_fade") & (new.opportunity_session == "ETH"), "net_pnl_usd"].sum()
                - old.loc[(old.direction == "long_fade")
                          & (old.opportunity_session == "ETH"), "net_pnl_usd"].sum())})
    return pd.DataFrame(rows)


def dependency_hashes_2025() -> dict:
    return {"runner": script_sha256(), "config": sha256_file(CONFIG_PATH),
            "freeze": sha256_file(FREEZE_PATH), "audit": sha256_file(PRE_AUDIT),
            "authorization": sha256_file(PRE_AUTH), "raw": sha256_file(RAW_1S[2025]),
            "atlas": sha256_file(year_atlas_path(2025)), "scores": sha256_file(score_path(2025))}


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
    policy = json.loads((REPAIR / "CODEX_5_X_established_fade_policy.json").read_text(encoding="utf-8"))
    raw = pd.read_parquet(RAW_1S[args.year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    candidates, crossing_audit = collect_candidates(args.year, raw, policy, config["max_regime_age_seconds"])
    first_rec = reconcile_first_candidates(args.year, candidates, raw)
    expected_first_count = {2025: 3530, 2026: 1237}[args.year]
    if int((candidates.candidate_seq == 1).sum()) != expected_first_count:
        raise RuntimeError("explicit regenerated first-candidate count failure")
    all_results, all_evals = [], []
    for p in config["policies"]:
        selections, evaluations = select_candidates(candidates, raw, p["policy_id"], p["delay_seconds"])
        results = execute_policy(args.year, selections, raw, p["policy_id"])
        all_results.append(results)
        all_evals.append(evaluations)
    opportunities = add_baseline(pd.concat(all_results, ignore_index=True))
    diffs = trade_diffs(opportunities)
    evaluations = pd.concat(all_evals, ignore_index=True)
    r0_rec = reconcile_r0(args.year, opportunities[opportunities.policy_id == "R0"])
    expected_r0_count = {2025: 3246, 2026: 1137}[args.year]
    if int(opportunities[(opportunities.policy_id == "R0") & opportunities.executed].shape[0]) != expected_r0_count:
        raise RuntimeError("explicit R0 trade count failure")
    skip_forever = build_skip_forever_diagnostic(
        args.year, candidates, opportunities[opportunities.policy_id == "R0"], raw)
    evaluation_audit = evaluations.assign(row_type="candidate_evaluation")
    candidate_records = candidates.assign(row_type="emitted_candidate")
    generation_audit = pd.concat([crossing_audit, candidate_records, evaluation_audit, skip_forever],
                                 ignore_index=True, sort=False)
    paths = {
        f"candidates_{args.year}.parquet": candidates,
        f"generation_audit_{args.year}.parquet": generation_audit,
        f"opportunity_results_{args.year}.parquet": opportunities,
        f"trade_diffs_{args.year}.parquet": diffs,
        f"skip_forever_{args.year}.parquet": skip_forever,
    }
    for name, frame in paths.items():
        frame.to_parquet(WORK / name, index=False)
    seal = {"year": args.year, "blocking_errors": 0, "candidate_count": len(candidates),
        "opportunity_count": int(candidates.opportunity_id.nunique()),
        "expected_frozen_first_candidate_count": {2025: 3530, 2026: 1237}[args.year],
        "actual_regenerated_first_candidate_count": int((candidates.candidate_seq == 1).sum()),
        "expected_frozen_policy_a_trade_count": {2025: 3246, 2026: 1137}[args.year],
        "actual_r0_trade_count": int(opportunities[(opportunities.policy_id == "R0")
                                                     & opportunities.executed].shape[0]),
        "first_candidate_reconciliation": first_rec, "r0_reconciliation": r0_rec,
        "dependency_hashes_2025": dependency_hashes_2025(),
        "artifact_sha256": {name: sha256_file(WORK / name) for name in paths}}
    (WORK / f"reconciliation_{args.year}.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    if args.year == 2026:
        combined = {}
        for key in ("generation_audit", "opportunity_results", "trade_diffs"):
            combined[key] = pd.concat([pd.read_parquet(WORK / f"{key}_2025.parquet"),
                                       pd.read_parquet(WORK / f"{key}_2026.parquet")], ignore_index=True)
        opportunities_all = combined["opportunity_results"]
        evals_all = combined["generation_audit"]
        skip_forever_all = evals_all[evals_all.row_type == "skip_forever_diagnostic"]
        evals_all = evals_all[evals_all.row_type == "candidate_evaluation"]
        outputs = {
            "multi_candidate_generation_audit.parquet": combined["generation_audit"],
            "multi_candidate_policy_results.parquet": summarize(opportunities_all),
            "multi_candidate_opportunity_results.parquet": opportunities_all,
            "multi_candidate_trade_diffs.parquet": combined["trade_diffs"],
            "multi_candidate_reentry_accounting.parquet": accounting(
                combined["trade_diffs"], evals_all, skip_forever_all),
        }
        for name, frame in outputs.items():
            frame.to_parquet(RESULTS / name, index=False)
        manifest = {"status": "OUTPUTS_COMPLETE_PENDING_REPORT_AND_COMPLETION_AUDIT",
            "policies": ["R0", "R10", "R30"],
            "opportunity_count": int(opportunities_all.opportunity_id.nunique()),
            "runner_sha256": script_sha256(), "config_sha256": sha256_file(CONFIG_PATH),
            "freeze_sha256": sha256_file(FREEZE_PATH),
            "output_sha256": {name: sha256_file(RESULTS / name) for name in outputs}}
        (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{args.year}: {candidates.opportunity_id.nunique():,} opportunities, {len(candidates):,} candidates")


if __name__ == "__main__":
    main()
