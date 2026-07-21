"""Run the repaired W4 established-regime fade under explicit 1s OHLC semantics.

This is a causal research replay, not NT-native executable validation. Databento
1-second bars are open-labelled: the range at ts_event=t describes [t, t+1s).
A score at observation_time=t uses only data before t, so the first eligible
fill is the first available 1-second open with ts_event >= t.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from CODEX_5_X_common import (
    BUNDLE_PATH, FIRST_2026_OPEN_PATH, MANIFEST_PATH, NS, RAW_1S, RESULTS,
    ROOT, STUDY, sha256_file, year_atlas_path,
)

POLICY_PATH = STUDY / "CODEX_5_X_established_fade_policy.json"
PRE_POLICY_AUDIT = STUDY / "audit" / "CODEX_5_X_pre_policy_audit.md"
PRE_EXEC_AUDIT = STUDY / "audit" / "CODEX_5_X_policy_pre_execution_audit.md"
PRE_EXEC_AUTH = STUDY / "audit" / "CODEX_5_X_policy_pre_execution_authorization.json"
INPUT_CONTRACT_PATH = STUDY / "CODEX_5_X_policy_input_contract.json"
NQ_MULTIPLIER = 20.0


def score_path(year: int) -> Path:
    return RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def policy_sha256() -> str:
    return hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def load_policy() -> dict:
    p = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    valid = (
        p.get("frozen_before_policy_execution") is True
        and p.get("research_contract") == "EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT"
        and p.get("stop_atr") == 1.5
        and p.get("optional_secondary_exit") == "not implemented"
        and p.get("nq_multiplier_usd_per_point") == NQ_MULTIPLIER
    )
    if not valid:
        raise RuntimeError("invalid or unfrozen policy contract")
    return p


def require_passed_audits() -> None:
    for path in (PRE_POLICY_AUDIT, PRE_EXEC_AUDIT):
        if not path.exists():
            raise RuntimeError(f"missing mandatory audit: {path.name}")
        text = path.read_text(encoding="utf-8")
        status_pass = re.search(r"^\*\*Status:\*\*\s+\*\*PASS(?:\s|\*|-|\u2014)", text, re.MULTILINE)
        findings_clean = re.search(
            r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
            text, re.MULTILINE,
        )
        if status_pass is None or findings_clean is None:
            raise RuntimeError(f"mandatory audit is not an exact clean PASS: {path.name}")
    if not PRE_EXEC_AUTH.exists():
        raise RuntimeError("missing auditor-signed policy authorization")
    auth = json.loads(PRE_EXEC_AUTH.read_text(encoding="utf-8"))
    expected = {
        "status": "PASS",
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "policy_sha256": sha256_file(POLICY_PATH),
        "input_contract_sha256": sha256_file(INPUT_CONTRACT_PATH),
        "audit_sha256": sha256_file(PRE_EXEC_AUDIT),
    }
    if any(auth.get(key) != value for key, value in expected.items()):
        raise RuntimeError("policy audit authorization is stale or invalid")


def current_input_hashes(year: int) -> dict[str, dict[str, str]]:
    return {
        str(year): {
            "raw": sha256_file(RAW_1S[year]),
            "atlas": sha256_file(year_atlas_path(year)),
            "scores": sha256_file(score_path(year)),
        },
        "common": {
            "manifest": sha256_file(MANIFEST_PATH),
            "bundle": sha256_file(BUNDLE_PATH),
            "first_open": sha256_file(FIRST_2026_OPEN_PATH),
        },
    }


def validate_hash_map(expected: dict, current: dict) -> None:
    if expected != current:
        raise RuntimeError("frozen policy input hash mismatch")


def validate_frozen_input_contract(year: int) -> dict[str, dict[str, str]]:
    frozen = json.loads(INPUT_CONTRACT_PATH.read_text(encoding="utf-8"))
    if frozen.get("status") != "FROZEN_BEFORE_POLICY_EXECUTION":
        raise RuntimeError("policy input contract is not frozen")
    expected = {str(year): frozen[str(year)], "common": frozen["common"]}
    current = current_input_hashes(year)
    validate_hash_map(expected, current)
    return current


def dependency_hashes_2025() -> dict[str, str]:
    return {
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "policy_sha256": sha256_file(POLICY_PATH),
        "raw_2025_sha256": sha256_file(RAW_1S[2025]),
        "atlas_2025_sha256": sha256_file(year_atlas_path(2025)),
        "scores_2025_sha256": sha256_file(score_path(2025)),
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "bundle_sha256": sha256_file(BUNDLE_PATH),
        "pre_policy_audit_sha256": sha256_file(PRE_POLICY_AUDIT),
        "pre_execution_audit_sha256": sha256_file(PRE_EXEC_AUDIT),
        "pre_execution_authorization_sha256": sha256_file(PRE_EXEC_AUTH),
        "input_contract_sha256": sha256_file(INPUT_CONTRACT_PATH),
    }


def validate_2025_dependency_seal(record: dict, current: dict[str, str]) -> None:
    stored = record.get("dependency_hashes_2025")
    if stored != current:
        raise RuntimeError("2026 policy test sealed: runner or 2025 input hash mismatch")


def require_clean_2025_predecessor() -> None:
    path = RESULTS / "CODEX_5_X_established_fade_reconciliation_2025.json"
    if not path.exists():
        raise RuntimeError("2026 policy test sealed until 2025 reconciliation is clean")
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("policy_sha256") != policy_sha256():
        raise RuntimeError("2026 policy test sealed: 2025 policy hash mismatch")
    if rec.get("blocking_errors") != 0 or rec.get("closure_residual") != 0:
        raise RuntimeError("2026 policy test sealed: 2025 reconciliation is not clean")
    validate_2025_dependency_seal(rec, dependency_hashes_2025())
    if not FIRST_2026_OPEN_PATH.exists():
        raise RuntimeError("2026 policy test sealed: frozen first-open ledger is missing")


def is_rth(ts_ns: int) -> bool:
    t = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
    minute = t.hour * 60 + t.minute
    return 8 * 60 + 30 <= minute < 15 * 60


def validate_raw_bars(raw: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        raise RuntimeError("raw 1s bars missing required columns")
    if (not isinstance(raw.index, pd.DatetimeIndex) or not raw.index.is_monotonic_increasing
            or not raw.index.is_unique):
        raise RuntimeError("raw 1s ts_event index must be ordered and unique")
    values = raw[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(values).all():
        raise RuntimeError("raw 1s OHLC contains non-finite values")
    o, h, l, c = (values[:, i] for i in range(4))
    if np.any(h < np.maximum(o, c)) or np.any(l > np.minimum(o, c)) or np.any(h < l):
        raise RuntimeError("raw 1s OHLC geometry is invalid")


def progress_window_counts(running_mfe: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Preserve the prior causal definition of distinct progress windows."""
    out = np.zeros(len(ts), dtype=np.int16)
    count = 0
    last_extreme_ts: int | None = None
    previous_extreme = -np.inf
    for i, value in enumerate(running_mfe):
        if value > previous_extreme + 1e-12:
            if last_extreme_ts is None or int(ts[i]) - last_extreme_ts >= 120 * NS:
                count += 1
            last_extreme_ts = int(ts[i])
            previous_extreme = float(value)
        out[i] = count
    return out


def strict_threshold_cross(previous: float | None, score: float, threshold: float) -> bool:
    return previous is not None and previous < threshold <= score


def load_checkpoint_stream(year: int, policy: dict) -> pd.DataFrame:
    cols = [
        "observation_time", "regime_start_ns", "regime_end_ns", "direction",
        "entry_ts_event", "entry_open", "atr_at_entry", "atr_at_checkpoint",
        "regime_age", "current_pnl", "current_mfe", "current_mae",
        "running_mfe", "running_mae",
    ]
    atlas = pd.read_parquet(year_atlas_path(year), columns=cols)
    scores = pd.read_parquet(score_path(year))
    key = ["observation_time", "regime_start_ns", "direction"]
    score_cols = key + ["w4_score", "direction_threshold", "score_valid"]
    stream = atlas.merge(scores[score_cols], on=key, how="left", validate="one_to_one")
    if not stream["score_valid"].fillna(False).all() or not stream["w4_score"].notna().all():
        raise RuntimeError("invalid or missing frozen W4 scores")
    if not np.allclose(stream["current_mfe"], stream["running_mfe"], rtol=0, atol=1e-12):
        raise RuntimeError("current_mfe/running_mfe alias violation")
    if not np.allclose(stream["current_mae"], stream["running_mae"], rtol=0, atol=1e-12):
        raise RuntimeError("current_mae/running_mae alias violation")
    if not (stream[["current_mfe", "current_mae"]] >= -1e-12).all().all():
        raise RuntimeError("negative repaired excursion")
    expected = stream["direction"].map({
        1: float(policy["direction_thresholds"]["1"]),
        -1: float(policy["direction_thresholds"]["-1"]),
    })
    if not np.allclose(stream["direction_threshold"], expected, rtol=0, atol=1e-15):
        raise RuntimeError("score threshold differs from frozen direction threshold")
    return stream.sort_values(["regime_start_ns", "observation_time"]).reset_index(drop=True)


def build_candidates(year: int, policy: dict, raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stream = load_checkpoint_stream(year, policy)
    ts = raw.index.view(np.int64)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    filt = policy["filter"]
    rows: list[dict] = []
    audit: list[dict] = []

    for regime_start, group in stream.groupby("regime_start_ns", sort=False):
        group = group.sort_values("observation_time")
        first = group.iloc[0]
        entry_ts = int(first.entry_ts_event)
        regime_end = int(first.regime_end_ns)
        direction = int(first.direction)
        atr_entry = float(first.atr_at_entry)
        anchor = float(first.entry_open)
        a = int(np.searchsorted(ts, entry_ts, side="left"))
        b = int(np.searchsorted(ts, regime_end, side="left"))
        if a >= b or int(ts[a]) != entry_ts or not np.isfinite(atr_entry) or atr_entry <= 0:
            raise AssertionError(f"invalid raw regime path at {regime_start}")
        favorable = (highs[a:b] - anchor) if direction == 1 else (anchor - lows[a:b])
        running = np.maximum.accumulate(np.maximum(favorable / atr_entry, 0.0))
        progress = progress_window_counts(running, ts[a:b])

        previous_score: float | None = None
        for cp in group.itertuples(index=False):
            score = float(cp.w4_score)
            threshold = float(cp.direction_threshold)
            crossed = strict_threshold_cross(previous_score, score, threshold)
            previous_score = score
            if not crossed:
                continue
            decision = int(cp.observation_time)
            k = int(np.searchsorted(ts[a:b], decision, side="left") - 1)
            if k < 0 or decision >= regime_end:
                audit.append({"year": year, "regime_start_ns": int(regime_start),
                              "decision_ts": decision, "reason": "cross_not_before_flip"})
                continue
            raw_mfe = float(running[k])
            if not np.isclose(raw_mfe, float(cp.current_mfe), rtol=0, atol=1e-9):
                raise AssertionError(f"checkpoint/raw MFE mismatch at {decision}")
            retained = float(cp.current_pnl) / float(cp.current_mfe) if cp.current_mfe > 0 else np.nan
            established = bool(
                float(cp.regime_age) >= filt["regime_age_s_min"]
                and float(cp.current_mfe) >= filt["running_mfe_atr_min"]
                and int(progress[k]) >= filt["new_progress_windows_min"]
                and retained >= filt["retained_mfe_ratio_min"]
            )
            audit.append({
                "year": year, "regime_start_ns": int(regime_start),
                "decision_ts": decision, "reason": "eligible" if established else "filter_fail",
                "prevailing_direction": direction, "w4_score": score,
                "direction_threshold": threshold, "regime_age_s": float(cp.regime_age),
                "running_mfe_atr": float(cp.current_mfe),
                "running_mae_atr": float(cp.current_mae),
                "new_progress_windows": int(progress[k]), "retained_mfe_ratio": retained,
            })
            if established:
                atr_checkpoint = float(cp.atr_at_checkpoint)
                if not np.isfinite(atr_checkpoint) or atr_checkpoint <= 0:
                    raise AssertionError(f"invalid checkpoint ATR at {decision}")
                rows.append({
                    "year": year, "regime_start_ns": int(regime_start),
                    "confirm_flip_ns": regime_end, "prevailing_direction": direction,
                    "entry_direction": -direction, "decision_ts": decision,
                    "score_observation_ts": int(cp.observation_time), "w4_score": score,
                    "direction_threshold": threshold, "atr_at_entry": atr_entry,
                    "atr_at_checkpoint": atr_checkpoint, "regime_age_s": float(cp.regime_age),
                    "running_mfe_atr": float(cp.current_mfe),
                    "running_mae_atr": float(cp.current_mae),
                    "new_progress_windows": int(progress[k]), "retained_mfe_ratio": retained,
                    "decision_session": "RTH" if is_rth(decision) else "ETH",
                })
                break
    candidates = pd.DataFrame(rows)
    if len(candidates):
        candidates = candidates.sort_values("decision_ts").reset_index(drop=True)
        if candidates["regime_start_ns"].duplicated().any():
            raise RuntimeError("duplicate candidate regime")
    return candidates, pd.DataFrame(audit)


def timeline_from_flips(starts: np.ndarray, directions: np.ndarray) -> pd.DataFrame:
    if len(starts) == 0 or len(starts) != len(directions):
        raise RuntimeError("invalid canonical flip vectors")
    if np.any(np.diff(starts) <= 0):
        raise RuntimeError("canonical flips must be strictly increasing")
    if not np.isin(directions, (-1, 1)).all() or np.any(directions[1:] == directions[:-1]):
        raise RuntimeError("canonical directions must alternate as exact +/-1")
    ends = np.empty(len(starts), dtype=object)
    ends[:-1] = starts[1:]
    ends[-1] = None
    return pd.DataFrame({"regime_start_ns": starts, "direction": directions,
                         "regime_end_ns": ends,
                         "end_censored": np.arange(len(starts)) == len(starts) - 1})


def canonical_regime_timeline(year: int, raw: pd.DataFrame) -> pd.DataFrame:
    """Fresh complete causal flip timeline, including the true trailing regime."""
    import sys

    upstream = str(ROOT / "studies" / "regime_sequence_chop_context")
    if upstream not in sys.path:
        sys.path.insert(0, upstream)
    from reproduce_regimes import aggregate_and_run_regimes

    minute = aggregate_and_run_regimes(raw, "1m").sort_values("close_ts")
    previous = minute["regime"].shift(1).fillna(0).astype(int)
    flips = minute[
        (minute["regime"] != 0) & (previous != 0) & (minute["regime"] != previous)
    ][["close_ts", "regime"]].copy()
    starts = flips["close_ts"].to_numpy(np.int64)
    directions = flips["regime"].to_numpy(np.int8)
    timeline = timeline_from_flips(starts, directions)
    if timeline["regime_start_ns"].duplicated().any():
        raise RuntimeError("duplicate canonical regime starts")

    represented = pd.read_parquet(
        year_atlas_path(year), columns=["regime_start_ns", "regime_end_ns", "direction"]
    ).drop_duplicates()
    parity = represented.merge(timeline, on="regime_start_ns", how="left", suffixes=("_atlas", "_canonical"))
    if parity["direction_canonical"].isna().any():
        raise RuntimeError("atlas regime missing from canonical timeline")
    if (parity["direction_atlas"] != parity["direction_canonical"]).any():
        raise RuntimeError("atlas/canonical direction mismatch")
    if any(int(a) != int(c) for a, c in zip(parity["regime_end_ns_atlas"],
                                             parity["regime_end_ns_canonical"])):
        raise RuntimeError("atlas/canonical regime-end mismatch")
    return timeline


def simulate(year: int, candidates: pd.DataFrame, raw: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    timeline = canonical_regime_timeline(year, raw)
    ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
    trades: list[dict] = []
    skipped: list[dict] = []
    busy_until = -1

    for c in candidates.itertuples(index=False):
        if c.decision_ts < busy_until:
            skipped.append({"regime_start_ns": c.regime_start_ns, "decision_ts": c.decision_ts,
                            "reason": "decision_while_position_open"})
            continue
        entry_i = int(np.searchsorted(ts, c.decision_ts, side="left"))
        if entry_i >= len(ts):
            skipped.append({"regime_start_ns": c.regime_start_ns, "decision_ts": c.decision_ts,
                            "reason": "no_next_available_open"})
            continue
        entry_ts = int(ts[entry_i])
        if entry_ts >= c.confirm_flip_ns:
            skipped.append({"regime_start_ns": c.regime_start_ns, "decision_ts": c.decision_ts,
                            "reason": "next_open_at_or_after_confirming_flip"})
            continue

        # If present, the confirming regime's end is the next flip against the trade.
        if int(c.confirm_flip_ns) not in ends:
            raise RuntimeError("confirming flip absent from complete canonical timeline")
        exit_value = ends[int(c.confirm_flip_ns)]
        exit_decision = None if exit_value is None else int(exit_value)
        exit_i = len(ts) if exit_decision is None else int(np.searchsorted(ts, exit_decision, side="left"))
        entry_px = float(opens[entry_i])
        stop_px = entry_px - c.entry_direction * policy["stop_atr"] * c.atr_at_checkpoint
        exit_ts: int | None = None
        exit_px = np.nan
        exit_reason = "data_end_censored"
        aligned_flip_seen = False
        for i in range(entry_i, min(exit_i, len(ts))):
            if ts[i] >= c.confirm_flip_ns:
                aligned_flip_seen = True
            touched = lows[i] <= stop_px if c.entry_direction == 1 else highs[i] >= stop_px
            if touched:
                gap = opens[i] <= stop_px if c.entry_direction == 1 else opens[i] >= stop_px
                exit_ts = int(ts[i])
                exit_px = float(opens[i]) if gap else float(stop_px)
                exit_reason = "stop_after_aligned_flip" if aligned_flip_seen else "stop_before_aligned_flip"
                break
        if exit_ts is None and exit_decision is not None and exit_i < len(ts):
            exit_ts = int(ts[exit_i])
            exit_px = float(opens[exit_i])
            exit_reason = "opposite_flip_against_countertrade"

        if exit_ts is None:
            busy_until = int(ts[-1] + NS)
        elif exit_reason.startswith("stop"):
            busy_until = int(exit_ts + NS)
        else:
            busy_until = int(exit_ts)
        gross_pts = ((exit_px - entry_px) * c.entry_direction
                     if np.isfinite(exit_px) else np.nan)
        gross_usd = gross_pts * NQ_MULTIPLIER if np.isfinite(gross_pts) else np.nan
        trades.append({
            **c._asdict(), "entry_fill_ts": entry_ts, "entry_fill_open": entry_px,
            "session": "RTH" if is_rth(entry_ts) else "ETH",
            "entry_fill_delay_s": (entry_ts - c.decision_ts) / NS,
            "stop_submission_ts": entry_ts, "stop_px": stop_px,
            "stop_active_entry_bar": True,
            "entry_bar_crosses_stop": bool(
                lows[entry_i] <= stop_px if c.entry_direction == 1 else highs[entry_i] >= stop_px),
            "realized_stop_atr_checkpoint": abs(entry_px - stop_px) / c.atr_at_checkpoint,
            "scheduled_exit_decision_ts": exit_decision, "exit_fill_ts": exit_ts,
            "exit_fill_px": exit_px, "exit_reason": exit_reason,
            "gross_pnl_pts": gross_pts, "gross_pnl_usd": gross_usd,
            "net_pnl_usd": gross_usd - policy["cost_rt_usd"] if np.isfinite(gross_usd) else np.nan,
            "hold_s": (exit_ts - entry_ts) / NS if exit_ts is not None else np.nan,
            "research_contract": policy["research_contract"], "policy_sha256": policy_sha256(),
        })
    return pd.DataFrame(trades), pd.DataFrame(skipped)


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    complete = trades[trades["net_pnl_usd"].notna()].copy()
    rows: list[dict] = []
    groupings = [
        ("all", []), ("direction", ["entry_direction"]), ("session", ["session"]),
        ("direction_session", ["entry_direction", "session"]), ("exit_reason", ["exit_reason"]),
    ]
    for split, cols in groupings:
        iterator = [((), complete)] if not cols else complete.groupby(cols, dropna=False)
        for key, g in iterator:
            keys = key if isinstance(key, tuple) else (key,)
            pnl = g["net_pnl_usd"]
            wins = pnl[pnl > 0].sum()
            losses = -pnl[pnl < 0].sum()
            row = {"split": split, "trade_count": len(g), "mean_net_pnl_usd": pnl.mean(),
                   "total_net_pnl_usd": pnl.sum(), "win_rate": (pnl > 0).mean(),
                   "profit_factor": wins / losses if losses > 0 else np.nan,
                   "stop_out_rate": g["exit_reason"].str.startswith("stop").mean(),
                   "median_hold_s": g["hold_s"].median()}
            for name, value in zip(cols, keys):
                row[name] = value
            rows.append(row)
    return pd.DataFrame(rows)


def reconcile(year: int, candidates: pd.DataFrame, trades: pd.DataFrame,
              skipped: pd.DataFrame, policy: dict,
              input_hashes: dict[str, dict[str, str]]) -> dict:
    closure = len(candidates) - len(trades) - len(skipped)
    errors = abs(closure)
    if len(trades):
        errors += int(trades["regime_start_ns"].duplicated().sum())
        errors += int((trades["entry_fill_delay_s"] < 0).sum())
        errors += int((trades["entry_fill_ts"] >= trades["confirm_flip_ns"]).sum())
        errors += int((trades["research_contract"] != policy["research_contract"]).sum())
        errors += int((~np.isclose(trades["realized_stop_atr_checkpoint"], 1.5,
                                  rtol=0, atol=1e-9)).sum())
        errors += int(((trades["exit_fill_ts"].notna()) &
                       (trades["exit_fill_ts"] < trades["entry_fill_ts"])).sum())
        errors += int((((trades["exit_reason"] == "data_end_censored") & trades["exit_fill_ts"].notna()) |
                       ((trades["exit_reason"] != "data_end_censored") & trades["exit_fill_ts"].isna())).sum())
    return {"year": year, "policy_sha256": policy_sha256(),
            "dependency_hashes_2025": dependency_hashes_2025(),
            "input_hashes_current_year": input_hashes,
            "candidate_count": len(candidates),
            "trade_count": len(trades), "skip_count": len(skipped), "closure_residual": closure,
            "blocking_errors": int(errors)}


def require_clean_reconciliation(rec: dict) -> None:
    if rec.get("closure_residual") != 0 or rec.get("blocking_errors") != 0:
        raise RuntimeError(f"blocking reconciliation failure: {rec}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True, choices=(2025, 2026))
    args = parser.parse_args()
    require_passed_audits()
    input_hashes = validate_frozen_input_contract(args.year)
    if args.year == 2026:
        require_clean_2025_predecessor()
    policy = load_policy()
    raw = pd.read_parquet(RAW_1S[args.year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    candidates, trigger_audit = build_candidates(args.year, policy, raw)
    trades, skipped = simulate(args.year, candidates, raw, policy)
    rec = reconcile(args.year, candidates, trades, skipped, policy, input_hashes)
    require_clean_reconciliation(rec)
    prefix = f"CODEX_5_X_established_fade_{args.year}"
    candidates.to_parquet(RESULTS / f"{prefix}_candidates.parquet", index=False)
    trigger_audit.to_parquet(RESULTS / f"{prefix}_trigger_audit.parquet", index=False)
    trades.to_parquet(RESULTS / f"{prefix}_trades.parquet", index=False)
    skipped.to_parquet(RESULTS / f"{prefix}_skipped.parquet", index=False)
    summarize(trades).to_parquet(RESULTS / f"{prefix}_summary.parquet", index=False)
    (RESULTS / f"CODEX_5_X_established_fade_reconciliation_{args.year}.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(candidates)} candidates, {len(trades)} trades, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
