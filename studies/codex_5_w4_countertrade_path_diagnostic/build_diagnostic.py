"""Build causal path diagnostics for frozen CODEX 5.X countertrades.

This script is descriptive only. It does not alter entries, stops, exits,
thresholds, or any frozen trading artifact.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
AUDIT = STUDY / "audit"
CONFIG_PATH = STUDY / "config.json"
PRE_EXEC_AUDIT = AUDIT / "pre_execution_audit.md"
PRE_EXEC_AUTH = AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
NS = 1_000_000_000

sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file, year_atlas_path  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, validate_raw_bars,
)

RESULTS.mkdir(parents=True, exist_ok=True)
AUDIT.mkdir(parents=True, exist_ok=True)


def trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def score_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def policy_path() -> Path:
    return REPAIR / "CODEX_5_X_established_fade_policy.json"


def script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def validate_hash_contract(expected: dict, current: dict) -> None:
    if current != expected:
        raise RuntimeError("frozen diagnostic input hash mismatch")


def validate_frozen_inputs(config: dict) -> None:
    current = {
        "policy": sha256_file(policy_path()),
        "code_dependencies": {
            "repair_runner": sha256_file(REPAIR / "CODEX_5_X_run_established_fade.py"),
            "repair_common": sha256_file(REPAIR / "CODEX_5_X_common.py"),
            "reproduce_regimes": sha256_file(
                ROOT / "studies" / "regime_sequence_chop_context" / "reproduce_regimes.py"),
        },
    }
    for year in (2025, 2026):
        current[str(year)] = {
            "trades": sha256_file(trade_path(year)),
            "scores": sha256_file(score_path(year)),
            "raw": sha256_file(RAW_1S[year]),
            "atlas": sha256_file(year_atlas_path(year)),
        }
    validate_hash_contract(config["input_sha256"], current)


def require_pre_execution_authorization() -> None:
    if not PRE_EXEC_AUDIT.exists() or not PRE_EXEC_AUTH.exists():
        raise RuntimeError("missing mandatory pre-execution audit authorization")
    text = PRE_EXEC_AUDIT.read_text(encoding="utf-8")
    status = re.search(r"^\*\*Status:\*\*\s+\*\*PASS(?:\s|\*|-|\u2014)", text, re.MULTILINE)
    findings = re.search(
        r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
        text, re.MULTILINE,
    )
    if status is None or findings is None:
        raise RuntimeError("pre-execution audit is not an exact clean PASS")
    auth = json.loads(PRE_EXEC_AUTH.read_text(encoding="utf-8"))
    expected = {
        "status": "PASS",
        "script_sha256": script_sha256(),
        "config_sha256": sha256_file(CONFIG_PATH),
        "spec_sha256": sha256_file(STUDY / "SPEC.md"),
        "audit_sha256": sha256_file(PRE_EXEC_AUDIT),
    }
    if any(auth.get(k) != v for k, v in expected.items()):
        raise RuntimeError("pre-execution authorization is stale or invalid")


def outcome_group(row: pd.Series) -> str:
    reason = row["exit_reason"]
    if reason == "stop_before_aligned_flip":
        return reason
    if reason == "stop_after_aligned_flip":
        return reason
    if reason != "opposite_flip_against_countertrade":
        raise RuntimeError(f"unexpected frozen exit reason: {reason}")
    return "opposite_flip_exit_winner" if row["net_pnl_usd"] > 0 else "opposite_flip_exit_loser"


def w4_exit_boundary(trade: pd.Series) -> int:
    if trade["exit_reason"] == "opposite_flip_against_countertrade":
        return int(trade["scheduled_exit_decision_ts"])
    return int(trade["exit_fill_ts"])


@dataclass(frozen=True)
class ScorePoint:
    score: float
    threshold: float
    observation_time: int


class ScoreLookup:
    def __init__(self, scores: pd.DataFrame, max_staleness_s: int):
        self.max_staleness_ns = max_staleness_s * NS
        self.groups: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        valid = scores[scores["score_valid"] & scores["w4_score"].notna()].copy()
        for key, group in valid.groupby("regime_start_ns", sort=False):
            group = group.sort_values("observation_time")
            self.groups[int(key)] = (
                group["observation_time"].to_numpy(np.int64),
                group["w4_score"].to_numpy(float),
                group["direction_threshold"].to_numpy(float),
            )

    def latest(self, regime_start: int, boundary: int) -> ScorePoint | None:
        group = self.groups.get(int(regime_start))
        if group is None:
            return None
        ts, values, thresholds = group
        i = int(np.searchsorted(ts, boundary, side="right") - 1)
        if i < 0 or boundary - int(ts[i]) > self.max_staleness_ns:
            return None
        return ScorePoint(float(values[i]), float(thresholds[i]), int(ts[i]))

    def first_at_or_above(self, regime_start: int, start: int, end: int) -> ScorePoint | None:
        group = self.groups.get(int(regime_start))
        if group is None:
            return None
        ts, values, thresholds = group
        a = int(np.searchsorted(ts, start, side="left"))
        b = int(np.searchsorted(ts, end, side="left"))
        candidates = np.flatnonzero(values[a:b] >= thresholds[a:b])
        if not len(candidates):
            return None
        i = a + int(candidates[0])
        return ScorePoint(float(values[i]), float(thresholds[i]), int(ts[i]))


def active_regime_start(timeline_starts: np.ndarray, boundary: int) -> int | None:
    i = int(np.searchsorted(timeline_starts, boundary, side="right") - 1)
    return None if i < 0 else int(timeline_starts[i])


def mark_before(raw_ts: np.ndarray, closes: np.ndarray, boundary: int,
                fallback_open: float) -> float:
    i = int(np.searchsorted(raw_ts, boundary, side="left") - 1)
    return fallback_open if i < 0 else float(closes[i])


def boundary_open(raw_ts: np.ndarray, opens: np.ndarray, boundary: int) -> tuple[int, float]:
    i = int(np.searchsorted(raw_ts, boundary, side="left"))
    if i >= len(raw_ts):
        raise RuntimeError("no raw open at or after boundary")
    return int(raw_ts[i]), float(opens[i])


def path_extrema(direction: int, entry: float, highs: np.ndarray,
                 lows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if direction == 1:
        favorable = highs - entry
        adverse = entry - lows
    elif direction == -1:
        favorable = entry - lows
        adverse = highs - entry
    else:
        raise RuntimeError("trade direction must be exact +/-1")
    return np.maximum(favorable, 0.0), np.maximum(adverse, 0.0)


def prevailing_new_extreme(direction: int, baseline: float, highs: np.ndarray,
                           lows: np.ndarray, discrete_mark: float | None = None) -> bool:
    if direction == 1:
        path_extreme = float(highs.max()) if len(highs) else -np.inf
        if discrete_mark is not None:
            path_extreme = max(path_extreme, float(discrete_mark))
        return path_extreme > baseline
    if direction == -1:
        path_extreme = float(lows.min()) if len(lows) else np.inf
        if discrete_mark is not None:
            path_extreme = min(path_extreme, float(discrete_mark))
        return path_extreme < baseline
    raise RuntimeError("prevailing direction must be exact +/-1")


def held_peak(raw_ts: np.ndarray, highs: np.ndarray, lows: np.ndarray,
              entry_ts: int, exit_ts: int, direction: int, entry: float,
              stop_exit: bool, exit_fill: float) -> tuple[float, int | None, int, str, float]:
    a = int(np.searchsorted(raw_ts, entry_ts, side="left"))
    b = int(np.searchsorted(raw_ts, exit_ts, side="left"))
    fav, _ = path_extrema(direction, entry, highs[a:b], lows[a:b])
    if not len(fav) or float(fav.max()) <= 0:
        peak, peak_bar_ts, peak_available_ts, source = 0.0, None, entry_ts, "entry_zero"
    else:
        k = int(np.argmax(fav))
        peak_bar_ts = int(raw_ts[a + k])
        peak, peak_available_ts, source = float(fav[k]), peak_bar_ts + NS, "1s_ohlc_range"
    upper = peak
    if stop_exit:
        stop_i = int(np.searchsorted(raw_ts, exit_ts, side="left"))
        if stop_i < len(raw_ts) and int(raw_ts[stop_i]) == exit_ts:
            bar_fav, _ = path_extrema(
                direction, entry, highs[stop_i:stop_i + 1], lows[stop_i:stop_i + 1])
            upper = max(upper, float(bar_fav[0]))
    else:
        exit_favorable = max(direction * (exit_fill - entry), 0.0)
        if exit_favorable > peak:
            peak, peak_bar_ts = exit_favorable, None
            peak_available_ts, source = exit_ts, "scheduled_exit_open"
        upper = peak
    return peak, peak_bar_ts, peak_available_ts, source, upper


def pnl_at_boundary(raw_ts: np.ndarray, opens: np.ndarray, closes: np.ndarray,
                    boundary: int, entry: float, direction: int) -> tuple[int, float]:
    fill_ts, fill_open = boundary_open(raw_ts, opens, boundary)
    return fill_ts, direction * (fill_open - entry)


def checkpoint_mark(raw_ts: np.ndarray, opens: np.ndarray, closes: np.ndarray,
                    boundary: int, entry_ts: int, align_ts: int, exit_ts: int,
                    entry_px: float, exit_px: float) -> tuple[int, float, str]:
    if boundary == entry_ts:
        return entry_ts, entry_px, "entry_fill_open"
    if boundary == align_ts:
        mark_ts, mark = boundary_open(raw_ts, opens, align_ts)
        return mark_ts, mark, "aligning_flip_next_open"
    if boundary == exit_ts:
        return exit_ts, exit_px, "stored_exit_fill"
    return boundary, mark_before(raw_ts, closes, boundary, entry_px), "last_completed_1s_close"


def include_discrete_mark(running_mfe: float, running_mae: float,
                          pnl_at_mark: float) -> tuple[float, float]:
    return max(running_mfe, pnl_at_mark, 0.0), max(running_mae, -pnl_at_mark, 0.0)


def named_times(trade: pd.Series, peak_available_ts: int, config: dict,
                data_end: int) -> tuple[np.ndarray, dict[int, list[str]]]:
    entry = int(trade.entry_fill_ts)
    align = int(trade.confirm_flip_ns)
    exit_ts = int(trade.exit_fill_ts)
    horizon = min(data_end, max(
        entry + max(config["entry_offsets_seconds"]) * NS,
        align + max(config["post_flip_offsets_seconds"]) * NS,
        exit_ts,
    ))
    grid = np.arange(entry, horizon + 1, config["grid_seconds"] * NS, dtype=np.int64)
    names: dict[int, list[str]] = {}

    def add(boundary: int, label: str) -> None:
        names.setdefault(boundary, []).append(label)

    add(entry, "entry")
    add(align, "aligning_flip")
    add(peak_available_ts, "countertrade_peak_mfe")
    add(exit_ts, "final_exit")
    for seconds in config["entry_offsets_seconds"]:
        t = entry + seconds * NS
        if t <= data_end:
            add(t, f"plus_{seconds}s")
    for seconds in config["post_flip_offsets_seconds"]:
        t = align + seconds * NS
        if t <= data_end:
            add(t, f"aligning_flip_plus_{seconds}s")
    times = np.unique(np.concatenate([grid, np.fromiter(names, dtype=np.int64)]))
    times = times[times <= data_end]
    return times, names


def score_fields(lookup: ScoreLookup, timeline_starts: np.ndarray, boundary: int,
                 entry_score: float, entry_regime: int, config: dict) -> dict:
    regime = active_regime_start(timeline_starts, boundary)
    current = None if regime is None else lookup.latest(regime, boundary)
    out = {
        "active_regime_start_ns": regime,
        "w4_score": np.nan if current is None else current.score,
        "w4_threshold": np.nan if current is None else current.threshold,
        "w4_observation_time": None if current is None else current.observation_time,
        "w4_change_from_entry": np.nan if current is None else current.score - entry_score,
        "w4_above_threshold": None if current is None else bool(current.score >= current.threshold),
        "w4_same_regime_as_entry": regime == entry_regime,
    }
    for seconds in config["w4_slope_windows_seconds"]:
        prior = None if regime is None else lookup.latest(regime, boundary - seconds * NS)
        slope = np.nan
        if current is not None and prior is not None:
            elapsed = (current.observation_time - prior.observation_time) / NS
            if elapsed >= seconds:
                slope = (current.score - prior.score) / elapsed
        out[f"w4_slope_{seconds}s"] = slope
    return out


def build_trade(year: int, trade_id: str, trade: pd.Series, raw: pd.DataFrame,
                atlas_entry: dict[int, int], timeline: pd.DataFrame,
                lookup: ScoreLookup, config: dict) -> tuple[list[dict], dict]:
    raw_ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    closes = raw["close"].to_numpy(float)
    timeline_starts = timeline["regime_start_ns"].to_numpy(np.int64)
    entry_ts = int(trade.entry_fill_ts)
    exit_ts = int(trade.exit_fill_ts)
    align_ts = int(trade.confirm_flip_ns)
    entry_px = float(trade.entry_fill_open)
    direction = int(trade.entry_direction)
    atr = float(trade.atr_at_checkpoint)
    stop_exit = str(trade.exit_reason).startswith("stop")
    score_end = w4_exit_boundary(trade)
    peak_pts, peak_bar_ts, peak_available_ts, peak_source, stop_bar_upper_pts = held_peak(
        raw_ts, highs, lows, entry_ts, exit_ts, direction, entry_px, stop_exit,
        float(trade.exit_fill_px))
    times, names = named_times(trade, peak_available_ts, config, int(raw_ts[-1] + NS))

    regime_entry_ts = atlas_entry[int(trade.regime_start_ns)]
    ra = int(np.searchsorted(raw_ts, regime_entry_ts, side="left"))
    re = int(np.searchsorted(raw_ts, entry_ts, side="left"))
    if re <= ra:
        raise RuntimeError("empty prevailing-regime pre-entry path")
    if int(trade.prevailing_direction) == 1:
        old_baseline = float(highs[ra:re].max())
    else:
        old_baseline = float(lows[ra:re].min())

    a = int(np.searchsorted(raw_ts, entry_ts, side="left"))
    path_rows: list[dict] = []
    for boundary in times:
        boundary = int(boundary)
        b = int(np.searchsorted(raw_ts, boundary, side="left"))
        fav, adv = path_extrema(direction, entry_px, highs[a:b], lows[a:b])
        running_mfe = float(fav.max()) / atr if len(fav) else 0.0
        running_mae = float(adv.max()) / atr if len(adv) else 0.0
        price_mark_time, mark, price_mark_source = checkpoint_mark(
            raw_ts, opens, closes, boundary, entry_ts, align_ts, exit_ts,
            entry_px, float(trade.exit_fill_px),
        )
        if boundary == exit_ts:
            if stop_exit:
                running_mae = max(running_mae, -direction * (mark - entry_px) / atr)
        pnl = direction * (mark - entry_px) / atr
        # A discrete boundary mark is a known reached price even when no 1s
        # range exists at that exact boundary (for example, a gap to the next
        # available open). Keep row PnL inside its own running-extrema envelope.
        running_mfe, running_mae = include_discrete_mark(running_mfe, running_mae, pnl)
        old_new = prevailing_new_extreme(
            int(trade.prevailing_direction), old_baseline, highs[a:b], lows[a:b], mark)
        sf = score_fields(
            lookup, timeline_starts, boundary, float(trade.w4_score),
            int(trade.regime_start_ns), config,
        )
        labels = names.get(boundary, [])
        if (boundary - entry_ts) % (config["grid_seconds"] * NS) == 0:
            labels = ["grid_5s", *labels]
        path_rows.append({
            "trade_id": trade_id, "year": year, "outcome_group": outcome_group(trade),
            "trade_direction": "long_fade" if direction == 1 else "short_fade",
            "session": trade.session, "checkpoint_time": boundary,
            "price_mark_time": price_mark_time, "price_mark_source": price_mark_source,
            "checkpoint_labels": "|".join(dict.fromkeys(labels)),
            "time_since_entry_s": (boundary - entry_ts) / NS,
            "aligning_flip_occurred": boundary >= align_ts,
            "time_since_aligning_flip_s": ((boundary - align_ts) / NS if boundary >= align_ts else np.nan),
            "trade_active": entry_ts <= boundary < exit_ts,
            "counterfactual_after_exit": boundary > exit_ts,
            "countertrade_unrealized_pnl_atr": pnl,
            "countertrade_running_mfe_atr": running_mfe,
            "countertrade_running_mae_atr": running_mae,
            "old_prevailing_new_favorable_extreme": old_new,
            **sf,
        })

    align_fill_ts, align_pnl_pts = pnl_at_boundary(
        raw_ts, opens, closes, align_ts, entry_px, direction)
    reached_align = exit_ts >= align_fill_ts and trade.exit_reason != "stop_before_aligned_flip"
    post_peak_pts = np.nan
    post_peak_bar_ts = None
    post_peak_available_ts = None
    post_peak_source = None
    if reached_align:
        pa = int(np.searchsorted(raw_ts, align_fill_ts, side="left"))
        pb = int(np.searchsorted(raw_ts, exit_ts, side="left"))
        post_fav, _ = path_extrema(direction, entry_px, highs[pa:pb], lows[pa:pb])
        if len(post_fav):
            k = int(np.argmax(post_fav))
            post_peak_pts = float(post_fav[k])
            post_peak_bar_ts = int(raw_ts[pa + k])
            post_peak_available_ts = post_peak_bar_ts + NS
            post_peak_source = "1s_ohlc_range"
        else:
            post_peak_pts, post_peak_available_ts = max(0.0, align_pnl_pts), align_fill_ts
            post_peak_source = "aligning_flip_open"
        if not stop_exit:
            exit_favorable = max(direction * (float(trade.exit_fill_px) - entry_px), 0.0)
            if exit_favorable > float(post_peak_pts):
                post_peak_pts, post_peak_bar_ts = exit_favorable, None
                post_peak_available_ts, post_peak_source = exit_ts, "scheduled_exit_open"

    warning = None
    warning_pnl_atr = np.nan
    aligned_first = aligned_last = aligned_max = aligned_change = aligned_above_rate = np.nan
    if reached_align:
        warning = lookup.first_at_or_above(int(trade.confirm_flip_ns), align_ts, score_end)
        if warning is not None:
            warning_mark = mark_before(raw_ts, closes, warning.observation_time, entry_px)
            warning_pnl_atr = direction * (warning_mark - entry_px) / atr
        aligned_group = lookup.groups.get(int(trade.confirm_flip_ns))
        if aligned_group is not None:
            ats, aval, athr = aligned_group
            aa = int(np.searchsorted(ats, align_ts, side="left"))
            ab = int(np.searchsorted(ats, score_end, side="left"))
            if ab > aa:
                aligned_first = float(aval[aa])
                aligned_last = float(aval[ab - 1])
                aligned_max = float(aval[aa:ab].max())
                aligned_change = aligned_last - aligned_first
                aligned_above_rate = float(np.mean(aval[aa:ab] >= athr[aa:ab]))

    hb = int(np.searchsorted(raw_ts, exit_ts, side="left"))
    old_new_held = prevailing_new_extreme(
        int(trade.prevailing_direction), old_baseline, highs[a:hb], lows[a:hb],
        float(trade.exit_fill_px))
    last_pre_exit_regime = (int(trade.regime_start_ns) if not reached_align
                            else int(trade.confirm_flip_ns))
    last_w4 = lookup.latest(last_pre_exit_regime, score_end)
    realized_atr = float(trade.gross_pnl_pts) / atr
    diagnostic = {
        "trade_id": trade_id, "year": year, "outcome_group": outcome_group(trade),
        "trade_direction": "long_fade" if direction == 1 else "short_fade",
        "session": trade.session, "entry_fill_ts": entry_ts, "aligning_flip_ts": align_ts,
        "aligning_flip_fill_ts": align_fill_ts, "exit_fill_ts": exit_ts,
        "hold_s": float(trade.hold_s), "atr_at_checkpoint": atr,
        "entry_w4_score": float(trade.w4_score), "entry_w4_threshold": float(trade.direction_threshold),
        "realized_gross_pnl_atr": realized_atr, "realized_net_pnl_usd": float(trade.net_pnl_usd),
        "aligning_flip_pnl_atr": align_pnl_pts / atr if reached_align else np.nan,
        "holding_peak_mfe_atr": peak_pts / atr,
        "holding_peak_bar_ts_event": peak_bar_ts,
        "holding_peak_available_ts": peak_available_ts,
        "holding_peak_source": peak_source,
        "holding_peak_time_s": (peak_available_ts - entry_ts) / NS,
        "peak_to_exit_s": (exit_ts - peak_available_ts) / NS,
        "stop_bar_mfe_upper_bound_atr": stop_bar_upper_pts / atr if stop_exit else np.nan,
        "mfe_ge_0p25_before_stop": (peak_pts / atr >= 0.25) if stop_exit else None,
        "mfe_ge_0p50_before_stop": (peak_pts / atr >= 0.50) if stop_exit else None,
        "mfe_ge_0p75_before_stop": (peak_pts / atr >= 0.75) if stop_exit else None,
        "mfe_ge_1p00_before_stop": (peak_pts / atr >= 1.00) if stop_exit else None,
        "old_prevailing_new_favorable_extreme_during_hold": old_new_held,
        "last_w4_before_exit": np.nan if last_w4 is None else last_w4.score,
        "last_w4_change_from_entry": (np.nan if last_w4 is None else
                                        last_w4.score - float(trade.w4_score)),
        "last_w4_above_threshold": None if last_w4 is None else bool(last_w4.score >= last_w4.threshold),
        "aligned_regime_first_w4": aligned_first,
        "aligned_regime_last_w4": aligned_last,
        "aligned_regime_max_w4": aligned_max,
        "aligned_regime_w4_change": aligned_change,
        "aligned_regime_w4_above_threshold_rate": aligned_above_rate,
        "post_flip_peak_mfe_atr": post_peak_pts / atr if reached_align else np.nan,
        "post_flip_peak_bar_ts_event": post_peak_bar_ts,
        "post_flip_peak_available_ts": post_peak_available_ts,
        "post_flip_peak_source": post_peak_source,
        "post_flip_peak_time_from_entry_s": ((post_peak_available_ts - entry_ts) / NS
                                               if post_peak_available_ts is not None else np.nan),
        "post_flip_peak_time_from_flip_s": ((post_peak_available_ts - align_ts) / NS
                                              if post_peak_available_ts is not None else np.nan),
        "post_flip_peak_giveback_to_exit_atr": ((post_peak_pts / atr - realized_atr)
                                                  if reached_align else np.nan),
        "realized_capture_ratio": (realized_atr / (peak_pts / atr)
                                     if peak_pts > 0 else np.nan),
        "first_post_flip_w4_warning_ts": None if warning is None else warning.observation_time,
        "first_post_flip_w4_warning_time_from_flip_s": (np.nan if warning is None else
                                                          (warning.observation_time - align_ts) / NS),
        "pnl_at_first_post_flip_w4_warning_atr": warning_pnl_atr,
        "post_flip_w4_warning_before_exit": warning is not None,
    }
    return path_rows, diagnostic


def aggregate_diagnostics(diag: pd.DataFrame) -> pd.DataFrame:
    splits = [("overall", pd.Series("ALL", index=diag.index)),
              ("year", diag["year"].astype(str)),
              ("trade_direction", diag["trade_direction"]),
              ("session", diag["session"])]
    rows: list[dict] = []
    numeric = [
        "realized_gross_pnl_atr", "realized_net_pnl_usd", "aligning_flip_pnl_atr",
        "holding_peak_mfe_atr", "holding_peak_time_s", "peak_to_exit_s",
        "post_flip_peak_mfe_atr", "post_flip_peak_time_from_flip_s",
        "post_flip_peak_giveback_to_exit_atr", "realized_capture_ratio",
        "first_post_flip_w4_warning_time_from_flip_s",
        "pnl_at_first_post_flip_w4_warning_atr",
        "last_w4_before_exit", "last_w4_change_from_entry",
        "aligned_regime_first_w4", "aligned_regime_last_w4",
        "aligned_regime_max_w4", "aligned_regime_w4_change",
        "aligned_regime_w4_above_threshold_rate",
    ]
    booleans = [
        "mfe_ge_0p25_before_stop", "mfe_ge_0p50_before_stop",
        "mfe_ge_0p75_before_stop", "mfe_ge_1p00_before_stop",
        "old_prevailing_new_favorable_extreme_during_hold",
        "last_w4_above_threshold", "post_flip_w4_warning_before_exit",
    ]
    for split_type, labels in splits:
        frame = diag.assign(_split=labels)
        for (split_value, outcome), group in frame.groupby(["_split", "outcome_group"], dropna=False):
            row = {"split_type": split_type, "split_value": split_value,
                   "outcome_group": outcome, "trade_count": len(group)}
            for col in numeric:
                values = pd.to_numeric(group[col], errors="coerce").dropna()
                row[f"{col}_mean"] = values.mean() if len(values) else np.nan
                row[f"{col}_median"] = values.median() if len(values) else np.nan
            for col in booleans:
                values = pd.to_numeric(group[col], errors="coerce").dropna()
                row[f"{col}_rate"] = values.mean() if len(values) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def aggregate_early(path: pd.DataFrame) -> pd.DataFrame:
    early = path[path["checkpoint_labels"].str.contains(
        r"(?:^|\|)plus_(?:60|120)s(?:\||$)", regex=True)].copy()
    early["window_s"] = early["time_since_entry_s"].astype(int)
    splits = [("overall", pd.Series("ALL", index=early.index)),
              ("year", early["year"].astype(str)),
              ("trade_direction", early["trade_direction"]),
              ("session", early["session"])]
    rows: list[dict] = []
    metrics = ["countertrade_unrealized_pnl_atr", "countertrade_running_mfe_atr",
               "countertrade_running_mae_atr", "w4_change_from_entry"]
    for split_type, labels in splits:
        frame = early.assign(_split=labels)
        for (value, outcome, window), group in frame.groupby(
                ["_split", "outcome_group", "window_s"], dropna=False):
            row = {"split_type": split_type, "split_value": value,
                   "outcome_group": outcome, "window_s": window,
                   "trade_count": len(group), "active_trade_rate": group["trade_active"].mean()}
            for col in metrics:
                values = pd.to_numeric(group[col], errors="coerce").dropna()
                row[f"{col}_mean"] = values.mean() if len(values) else np.nan
                row[f"{col}_median"] = values.median() if len(values) else np.nan
            row["already_flipped_rate"] = group["aligning_flip_occurred"].mean()
            row["old_prevailing_new_favorable_extreme_rate"] = group[
                "old_prevailing_new_favorable_extreme"].mean()
            row["w4_above_threshold_rate"] = pd.to_numeric(
                group["w4_above_threshold"], errors="coerce").mean()
            row["w4_available_rate"] = group["w4_score"].notna().mean()
            rows.append(row)
    return pd.DataFrame(rows)


def records_frame(records: list[dict], optional_ns: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in optional_ns:
        if column in frame:
            # Build from original Python objects, not a potentially rounded
            # intermediate float64 column.
            frame[column] = pd.array([row.get(column) for row in records], dtype="Int64")
    return frame


def validate_outputs(path: pd.DataFrame, diag: pd.DataFrame, trades: pd.DataFrame,
                     config: dict) -> None:
    if diag["trade_id"].duplicated().any() or len(diag) != len(trades):
        raise RuntimeError("trade diagnostic cardinality failure")
    expected_ids = set(trades["trade_id"])
    if set(diag["trade_id"]) != expected_ids or set(path["trade_id"]) != expected_ids:
        raise RuntimeError("exact trade-ID coverage failure")
    if path.duplicated(["trade_id", "checkpoint_time"]).any():
        raise RuntimeError("duplicate trade checkpoint time")
    required = {"entry", "aligning_flip", "final_exit", "countertrade_peak_mfe"}
    required.update(f"plus_{s}s" for s in config["entry_offsets_seconds"])
    required.update(f"aligning_flip_plus_{s}s" for s in config["post_flip_offsets_seconds"])
    exit_by_trade = diag.set_index("trade_id")["exit_fill_ts"].to_dict()
    diagnostic_by_trade = diag.set_index("trade_id")
    for trade_id, group in path.groupby("trade_id", sort=False):
        if not group["checkpoint_time"].is_monotonic_increasing:
            raise RuntimeError(f"non-monotonic path for {trade_id}")
        grid = group[group["checkpoint_labels"].str.contains(r"(?:^|\|)grid_5s(?:\||$)")][
            "checkpoint_time"].to_numpy(np.int64)
        drow = diagnostic_by_trade.loc[trade_id]
        entry_ts = int(drow.entry_fill_ts)
        align_ts = int(drow.aligning_flip_ts)
        exit_ts = int(drow.exit_fill_ts)
        horizon = max(entry_ts + max(config["entry_offsets_seconds"]) * NS,
                      align_ts + max(config["post_flip_offsets_seconds"]) * NS,
                      exit_ts)
        grid_end = entry_ts + ((horizon - entry_ts) //
                               (config["grid_seconds"] * NS)) * config["grid_seconds"] * NS
        expected_grid = np.arange(entry_ts, grid_end + 1,
                                  config["grid_seconds"] * NS, dtype=np.int64)
        if not np.array_equal(grid, expected_grid):
            raise RuntimeError(f"incomplete 5-second grid for {trade_id}")
        expected_named = {
            "entry": entry_ts, "aligning_flip": align_ts, "final_exit": exit_ts,
            "countertrade_peak_mfe": int(drow.holding_peak_available_ts),
            **{f"plus_{s}s": entry_ts + s * NS for s in config["entry_offsets_seconds"]},
            **{f"aligning_flip_plus_{s}s": align_ts + s * NS
               for s in config["post_flip_offsets_seconds"]},
        }
        for label, expected_time in expected_named.items():
            matched = group[group["checkpoint_labels"].str.split("|").apply(lambda x: label in x)]
            if len(matched) != 1 or int(matched.iloc[0].checkpoint_time) != expected_time:
                raise RuntimeError(f"misplaced named checkpoint {label} for {trade_id}")
        expected_counterfactual = group["checkpoint_time"] > int(exit_by_trade[trade_id])
        if not np.array_equal(group["counterfactual_after_exit"].to_numpy(bool),
                              expected_counterfactual.to_numpy(bool)):
            raise RuntimeError(f"after-exit label mismatch for {trade_id}")
    if (path["w4_observation_time"].dropna() > path.loc[
            path["w4_observation_time"].notna(), "checkpoint_time"]).any():
        raise RuntimeError("forward W4 join detected")


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not config.get("exploratory_only") or not config.get("no_policy_backtest"):
        raise RuntimeError("diagnostic guardrail missing")
    require_pre_execution_authorization()
    validate_frozen_inputs(config)
    all_path: list[pd.DataFrame] = []
    all_diag: list[pd.DataFrame] = []
    all_trades: list[pd.DataFrame] = []
    for year in (2025, 2026):
        raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
        validate_raw_bars(raw)
        timeline = canonical_regime_timeline(year, raw)
        scores = pd.read_parquet(score_path(year))
        lookup = ScoreLookup(scores, config["w4_max_staleness_seconds"])
        atlas = pd.read_parquet(year_atlas_path(year), columns=["regime_start_ns", "entry_ts_event"])
        atlas_entry = dict(atlas.drop_duplicates().itertuples(index=False, name=None))
        trades = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
        trades["trade_id"] = [f"{year}_{i:05d}" for i in range(len(trades))]
        rows: list[dict] = []
        diagnostics: list[dict] = []
        for trade in trades.itertuples(index=False):
            series = pd.Series(trade._asdict())
            path_rows, diagnostic = build_trade(
                year, trade.trade_id, series, raw, atlas_entry, timeline, lookup, config)
            rows.extend(path_rows)
            diagnostics.append(diagnostic)
        year_path = records_frame(rows, ("active_regime_start_ns", "w4_observation_time"))
        year_diag = records_frame(
            diagnostics,
            ("holding_peak_bar_ts_event", "post_flip_peak_bar_ts_event",
             "post_flip_peak_available_ts", "first_post_flip_w4_warning_ts"),
        )
        validate_outputs(year_path, year_diag, trades, config)
        all_path.append(year_path)
        all_diag.append(year_diag)
        all_trades.append(trades)
        print(f"{year}: {len(trades):,} trades, {len(year_path):,} path checkpoints")
    path = pd.concat(all_path, ignore_index=True)
    diag = pd.concat(all_diag, ignore_index=True)
    trades = pd.concat(all_trades, ignore_index=True)
    validate_outputs(path, diag, trades, config)
    outcome = aggregate_diagnostics(diag)
    early = aggregate_early(path)
    post = diag[diag["outcome_group"] != "stop_before_aligned_flip"].copy()
    path.to_parquet(RESULTS / "path_checkpoints.parquet", index=False)
    outcome.to_parquet(RESULTS / "outcome_group_summary.parquet", index=False)
    early.to_parquet(RESULTS / "early_window_summary.parquet", index=False)
    post.to_parquet(RESULTS / "post_flip_exit_diagnostic.parquet", index=False)
    manifest = {
        "status": "DIAGNOSTIC_OUTPUTS_COMPLETE",
        "script_sha256": script_sha256(), "config_sha256": sha256_file(CONFIG_PATH),
        "trade_count": len(diag), "path_row_count": len(path),
        "outcome_counts": diag["outcome_group"].value_counts().to_dict(),
        "output_sha256": {
            name: sha256_file(RESULTS / name) for name in (
                "path_checkpoints.parquet", "outcome_group_summary.parquet",
                "early_window_summary.parquet", "post_flip_exit_diagnostic.parquet")
        },
    }
    (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
