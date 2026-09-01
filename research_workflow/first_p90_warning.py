"""Canonical deterministic extraction for frozen first-P90 warning follow-up.

Pure state logic shared by the NT diagnostic adapter and offline analysis.  It
does not derive thresholds, emit Stage-1 candidates, or inspect future data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

import pandas as pd

NS = 1_000_000_000


@dataclass(frozen=True)
class FirstP90Warning:
    regime_id: str
    direction: str
    warning_ts: int
    score: float
    threshold: float


def first_inclusive_p90_warning(rows: Iterable[Mapping[str, Any]], thresholds: Mapping[str, float]):
    """Return exactly the earliest eligible score >= frozen P90 per regime."""
    chosen = {}
    for row in sorted(rows, key=lambda r: (int(r["ts"]), str(r["regime_id"]))):
        rid = str(row["regime_id"])
        direction = str(row["direction"])
        if rid in chosen or not bool(row.get("eligible", False)):
            continue
        score = row.get("score")
        threshold = float(thresholds[direction])
        if score is not None and float(score) >= threshold:
            chosen[rid] = FirstP90Warning(rid, direction, int(row["ts"]), float(score), threshold)
    return tuple(chosen.values())


def followup_terminal(warning: FirstP90Warning, rows: Iterable[Mapping[str, Any]], *, rth_close_ts: int):
    """Continue scheduled scores to first accepted flip, +600s, close, or censor.

    Missing scheduled score before terminal censors only the score path.  Market
    status remains independently observed when a terminal close/flip is present.
    """
    terminal_limit = min(warning.warning_ts + 600 * NS, int(rth_close_ts))
    path = []
    score_censored = False
    market_status = "OBSERVED"
    terminal = terminal_limit
    accepted_flip = None
    for row in sorted(rows, key=lambda r: int(r["ts"])):
        ts = int(row["ts"])
        if ts <= warning.warning_ts or ts > terminal_limit:
            continue
        if bool(row.get("accepted_opposing_flip", False)):
            terminal, accepted_flip = ts, ts
            break
        if bool(row.get("market_censored", False)):
            terminal, market_status = ts, "CENSORED"
            break
        if bool(row.get("scheduled_score", False)):
            if row.get("score") is None:
                score_censored = True
            else:
                path.append({"ts": ts, "score": float(row["score"])})
    score_status = "CENSORED" if score_censored else "OBSERVED"
    return {"warning_ts": warning.warning_ts, "terminal_ts": terminal,
            "accepted_flip_ts": accepted_flip, "time_to_flip_seconds": None if accepted_flip is None else (accepted_flip-warning.warning_ts)/NS,
            "market_outcome_status": market_status, "score_path_status": score_status,
            "scores": path, "terminal_reason": "FLIP" if accepted_flip else ("MARKET_CENSOR" if market_status == "CENSORED" else ("RTH_CLOSE" if terminal == rth_close_ts else "HORIZON_600S"))}


def warning_subtype(followup: Mapping[str, Any], threshold: float) -> str:
    """Frozen subtype precedence; SESSION_CENSORED dominates unobserved paths."""
    if followup["market_outcome_status"] == "CENSORED" or followup["score_path_status"] == "CENSORED":
        return "SESSION_CENSORED"
    t = followup.get("time_to_flip_seconds")
    if t is not None:
        return "FAST" if t <= 180 else "LATE" if t <= 300 else "SLOW"
    return ("FAILED_WARNING_SCORE_COLLAPSE" if any(s["score"] < threshold for s in followup["scores"])
            else "FAILED_WARNING_PERSISTENT_HIGH")


def control_cell(row: Mapping[str, Any], *, rth_open_ts: int) -> tuple[str, str]:
    age = float(row["age_seconds"])
    bucket = "[300,600)" if age < 600 else "[600,900)" if age < 900 else "[900,1800)" if age < 1800 else ">=1800"
    elapsed = (int(row["ts"]) - rth_open_ts) / NS
    tod = "final_30m" if elapsed >= 360 * 60 else f"{int(elapsed // 3600):02d}:00"
    return bucket, tod


def select_control(rows: Iterable[Mapping[str, Any]], warning: FirstP90Warning, *, rth_open_ts: int):
    """Latest valid below-P90 same-cell checkpoint, strictly pre-fire where applicable."""
    target = control_cell(next(r for r in rows if str(r["regime_id"]) == warning.regime_id and int(r["ts"]) == warning.warning_ts), rth_open_ts=rth_open_ts)
    candidates = [r for r in rows if bool(r.get("valid", False)) and r.get("score") is not None
                  and float(r["score"]) < warning.threshold and control_cell(r, rth_open_ts=rth_open_ts) == target
                  and int(r["ts"]) < warning.warning_ts]
    return max(candidates, key=lambda r: int(r["ts"])) if candidates else None


# These names are deliberately the March reference vocabulary.  A projection may
# carry fewer columns when the source did not emit an optional identity component,
# but it never invents one (in particular it does not manufacture a 180 second
# result from the 600 second terminal stream).
MARCH_IDENTITY_FIELDS = (
    "direction", "regime_id", "regime_start_ns", "checkpoint_index", "anchor_ts",
    "scheduled_ts", "research_first_P90_ts", "nt_first_P90_ts",
)
MARCH_OUTCOME_FIELDS = (
    "target_flip_within_horizon", "flip_ts", "time_to_flip_seconds", "censored",
    "censor_reason", "disposition",
)


def project_first_p90_march(diagnostic: pd.DataFrame, observations: pd.DataFrame | None = None) -> pd.DataFrame:
    """Project canonical diagnostic records into one exact first-fire/180s record.

    The diagnostic collector records a 600s follow-up grid.  This function uses its
    *observed terminal* and only labels 180s when the market was observable through
    180 seconds.  A terminal before 180 is censoring, never a negative.
    """
    required = {"regime_start_ns", "direction", "anchor_ts", "scheduled_ts", "terminal_ts",
                "terminal_reason", "market_path_status"}
    missing = required - set(diagnostic.columns)
    if missing:
        raise ValueError(f"FIRST_P90_DIAGNOSTIC_SCHEMA_MISSING: {sorted(missing)}")
    diag = diagnostic.copy()
    diag["regime_start_ns"] = diag["regime_start_ns"].astype("int64")
    diag["anchor_ts"] = diag["anchor_ts"].astype("int64")
    # The records for one anchor must report one terminal state; otherwise the
    # extractor cannot know which market observation is authoritative.
    group_cols = ["regime_start_ns", "direction", "anchor_ts"]
    for _, group in diag.groupby(group_cols, dropna=False, sort=True):
        if group[["terminal_ts", "terminal_reason", "market_path_status"]].drop_duplicates().shape[0] != 1:
            raise ValueError("FIRST_P90_TERMINAL_INCONSISTENT")
    source = diag.sort_values(["regime_start_ns", "anchor_ts", "scheduled_ts"]).groupby(group_cols, as_index=False).first()
    if observations is not None and not observations.empty:
        obs = observations.copy()
        # Preserve the reference's identity values where the regular collection has
        # them. The join is only on canonical anchor identity, never a temporal guess.
        join = [c for c in ("regime_start_ns", "direction", "anchor_ts") if c in obs]
        if len(join) == 3:
            extra = [c for c in MARCH_IDENTITY_FIELDS if c in obs and c not in join]
            if extra:
                source = source.merge(obs[join + extra].drop_duplicates(join), on=join, how="left", validate="one_to_one")
    rows = []
    for row in source.to_dict("records"):
        anchor, terminal = int(row["anchor_ts"]), int(row["terminal_ts"])
        horizon = anchor + 180 * NS
        reason = str(row["terminal_reason"])
        market_censored = str(row["market_path_status"]) == "CENSORED"
        is_flip = reason == "ACCEPTED_OPPOSING_FLIP"
        flip_ts = terminal if is_flip else None
        if is_flip and terminal <= horizon:
            label, censored, censor_reason, disposition = 1, False, None, "LABELED_POSITIVE"
        elif market_censored or terminal < horizon:
            label, censored, censor_reason, disposition = None, True, ("MARKET_OR_DATA_CENSOR" if market_censored else reason), "CENSORED"
        else:
            label, censored, censor_reason, disposition = 0, False, None, "LABELED_NEGATIVE"
        out = dict(row)
        out.setdefault("regime_id", row["regime_start_ns"])
        out.setdefault("scheduled_ts", anchor)
        out.setdefault("research_first_P90_ts", anchor)
        out.setdefault("nt_first_P90_ts", anchor)
        out.update({"target_flip_within_horizon": label, "flip_ts": flip_ts,
                    "time_to_flip_seconds": ((terminal-anchor)/NS if is_flip else None),
                    "censored": censored, "censor_reason": censor_reason, "disposition": disposition})
        rows.append(out)
    return pd.DataFrame(rows)
