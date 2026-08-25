"""Bounded real-data infrastructure smoke for the forward-outcome module.

This proves the plumbing on real bars: it is not a study and produces no research
finding. The anchors are a mechanical time grid, not a signal, and nothing here reads
or writes any existing study's artifacts.

The verification that matters is :func:`bruteforce_outcomes` -- an intentionally naive
re-implementation that scans the raw bar list for each entry. The streaming tracker and
the brute-force scan share no code, so agreement between them is evidence about the
streaming implementation rather than a restatement of it.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd

from research_workflow.forward_outcomes.contracts import (
    NS,
    Direction,
    ForwardOutcomeSpec,
    OutcomeStatus,
    ProposedEntry,
    ReferencePrice,
)
from research_workflow.forward_outcomes.governance import (
    reconcile_outcome_artifacts,
    write_outcome_artifacts,
)
from research_workflow.forward_outcomes.partition import (
    assert_partition_parity,
    build_outcome_partitions,
    merge_outcome_partitions,
)
from research_workflow.forward_outcomes.tracker import ForwardOutcomeTracker

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
DEFAULT_BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
ATR_PERIOD_BARS = 300


def load_bar_tuples(
    catalog_path: Path, bar_type: str, date: str
) -> list[tuple[int, int, float, float, float]]:
    """Load one bounded day of 1s bars as ``(ts_open, ts_close, high, low, close)``."""
    from utils.runner.data import CausalDataLoader

    start = pd.Timestamp(date, tz="UTC")
    end = start + pd.Timedelta(days=1)
    bars = CausalDataLoader(catalog_path).load_bars(bar_type, start, end)
    out: list[tuple[int, int, float, float, float]] = []
    for bar in bars:
        out.append((
            int(bar.ts_event), int(bar.ts_init),
            float(bar.high), float(bar.low), float(bar.close),
        ))
    out.sort(key=lambda b: b[1])
    return out


def _causal_atr(true_ranges: deque) -> Optional[float]:
    """Mean true range over completed prior bars only. Never sees the current bar."""
    if len(true_ranges) < ATR_PERIOD_BARS:
        return None
    value = sum(true_ranges) / len(true_ranges)
    return value if value > 0 else None


def build_grid_anchors(
    bars: Sequence[tuple[int, int, float, float, float]],
    *,
    study_id: str,
    source_period: str,
    step_seconds: int,
    session: str,
    authorization_sha256: str,
    source_freeze_sha256: str,
) -> dict[int, ProposedEntry]:
    """Mechanical anchors on a fixed cadence, keyed by the bar close they are decided on.

    Direction alternates so both sign conventions are exercised on the same tape. The
    ATR stamped on each anchor is computed from strictly prior bars, which is the
    property the ATR-normalised outcome columns depend on.
    """
    from utils.session_boundaries import is_in_session

    anchors: dict[int, ProposedEntry] = {}
    true_ranges: deque = deque(maxlen=ATR_PERIOD_BARS)
    prev_close: Optional[float] = None
    next_anchor_ts: Optional[int] = None
    index = 0

    for _ts_open, ts_close, high, low, close in bars:
        atr = _causal_atr(true_ranges)
        in_session = session == "ALL" or is_in_session(ts_close, session)
        if next_anchor_ts is None:
            next_anchor_ts = ts_close
        if in_session and atr is not None and ts_close >= next_anchor_ts:
            direction = Direction.LONG if index % 2 == 0 else Direction.SHORT
            anchors[ts_close] = ProposedEntry(
                study_id=study_id,
                source_period=source_period,
                candidate_key=f"grid-{index:05d}",
                decision_ts=ts_close,
                entry_ts=ts_close,
                direction=direction,
                entry_price=close,
                reference_price=ReferencePrice.DECISION_CLOSE,
                authorization_sha256=authorization_sha256,
                source_freeze_sha256=source_freeze_sha256,
                entry_atr=atr,
                selector_id="infra_smoke_time_grid",
                metadata={"anchor_index": index, "atr_period_bars": ATR_PERIOD_BARS},
            )
            index += 1
            next_anchor_ts = ts_close + step_seconds * NS

        tr = high - low if prev_close is None else max(
            high - low, abs(high - prev_close), abs(low - prev_close)
        )
        true_ranges.append(tr)
        prev_close = close
    return anchors


def stream_outcomes(
    bars: Sequence[tuple[int, int, float, float, float]],
    anchors: dict[int, ProposedEntry],
    spec: ForwardOutcomeSpec,
    *,
    primary_interval: Optional[tuple[int, int]] = None,
) -> list[dict[str, Any]]:
    """Single causal pass: an anchor is registered only after its own bar is consumed."""
    tracker = ForwardOutcomeTracker(spec, primary_interval=primary_interval)
    for bar in bars:
        tracker.on_bar(*bar)
        entry = anchors.get(bar[1])
        if entry is not None:
            tracker.add_entry(entry)
    return tracker.finalize()


def bruteforce_outcomes(
    bars: Sequence[tuple[int, int, float, float, float]],
    entry: ProposedEntry,
    spec: ForwardOutcomeSpec,
) -> dict[str, Any]:
    """Naive reference scan for one entry. Shares no code with the tracker."""
    sign = 1 if entry.direction is Direction.LONG else -1
    horizon_end = entry.entry_ts + spec.max_tracking_ns
    session_close = entry.session_close_ts
    if session_close is None and spec.session_end_censoring and spec.session != "ALL":
        from utils.session_boundaries import session_close_ns

        session_close = session_close_ns(entry.entry_ts, spec.session)

    mfe = mae = None
    last_close = None
    horizon_price: dict[int, float] = {}
    count = 0
    for ts_open, ts_close, high, low, close in bars:
        if ts_open < entry.entry_ts or ts_close > horizon_end:
            continue
        if spec.session_end_censoring and session_close is not None and ts_close > session_close:
            break
        favorable = (high - entry.entry_price) if sign > 0 else (entry.entry_price - low)
        adverse = (entry.entry_price - low) if sign > 0 else (high - entry.entry_price)
        mfe = favorable if mfe is None else max(mfe, favorable)
        mae = adverse if mae is None else max(mae, adverse)
        last_close = close
        count += 1
        for seconds in spec.horizons_seconds:
            if ts_close <= entry.entry_ts + seconds * NS:
                horizon_price[seconds] = close
    return {
        "max_mfe": mfe,
        "max_mae": mae,
        "bars_observed": count,
        "final_price": last_close,
        "horizon_price": horizon_price,
    }


def run_infra_smoke(
    date: str = "2021-06-01",
    *,
    output_dir: Optional[Path] = None,
    catalog_path: Path = DEFAULT_CATALOG,
    bar_type: str = DEFAULT_BAR_TYPE,
    step_seconds: int = 300,
    cross_check_sample: int = 25,
) -> dict[str, Any]:
    """Materialise and verify one bounded day of forward outcomes."""
    year = int(date[:4])
    if year >= 2025:
        raise ValueError(
            f"infra smoke refuses {date}: 2025/2026 are reserved and this is not a study"
        )
    out = Path(output_dir or (REPO_ROOT / "runs" / "forward_outcomes_infra_smoke" / date))

    spec = ForwardOutcomeSpec(
        spec_id="infra_smoke_v1",
        horizons_seconds=(30, 60, 120, 300),
        max_tracking_seconds=600,
        excursion_units=("points", "atr"),
        session="RTH",
        session_end_censoring=True,
        max_gap_seconds=120,
        diagnostic_levels_atr=(0.5, 1.0),
        epsilon=0.25,
    )

    bars = load_bar_tuples(Path(catalog_path), bar_type, date)
    if not bars:
        raise RuntimeError(f"no bars available for {date} in {catalog_path}")

    anchors = build_grid_anchors(
        bars, study_id="forward_outcomes_infra_smoke", source_period="infra_smoke",
        step_seconds=step_seconds, session="RTH",
        authorization_sha256="infra_smoke_not_a_study",
        source_freeze_sha256="infra_smoke_not_a_study",
    )
    entries = [anchors[k] for k in sorted(anchors)]
    records = stream_outcomes(bars, anchors, spec)

    frame = pd.DataFrame(records)
    findings: list[str] = []

    if frame.empty:
        findings.append("no outcome rows produced")
    else:
        if len(frame) != len(entries):
            findings.append(f"row count {len(frame)} != entry count {len(entries)}")
        if frame["entry_id"].duplicated().any():
            findings.append("duplicate entry_id in outcome rows")
        resolved = frame[frame["outcome_status"] == OutcomeStatus.RESOLVED.value]
        if resolved.empty:
            findings.append("no RESOLVED rows; the day produced nothing measurable")
        else:
            for column in ("max_mfe", "max_mae", "max_mfe_atr", "max_mae_atr",
                           "return_30s", "return_300s", "final_return"):
                if resolved[column].isna().any():
                    findings.append(f"null {column} on a RESOLVED row")
        if set(frame["direction"]) != {"LONG", "SHORT"}:
            findings.append(f"expected both directions, saw {sorted(set(frame['direction']))}")

    # Independent cross-check against the naive scan.
    by_id = {r["entry_id"]: r for r in records}
    sample = entries[:: max(1, len(entries) // max(1, cross_check_sample))][:cross_check_sample]
    mismatches: list[str] = []
    for entry in sample:
        ref = bruteforce_outcomes(bars, entry, spec)
        got = by_id[entry.entry_id]
        if got["bars_observed"] != ref["bars_observed"]:
            mismatches.append(f"{entry.candidate_key}: bars {got['bars_observed']} vs {ref['bars_observed']}")
            continue
        for key in ("max_mfe", "max_mae"):
            a, b = got[key], ref[key]
            if a is None and b is None:
                continue
            if a is None or b is None or abs(float(a) - float(b)) > 1e-9:
                mismatches.append(f"{entry.candidate_key}: {key} {a} vs {b}")
        for seconds, price in ref["horizon_price"].items():
            column = f"price_{seconds}s"
            if got[column] is not None and abs(float(got[column]) - float(price)) > 1e-9:
                mismatches.append(f"{entry.candidate_key}: {column} {got[column]} vs {price}")
        # Direction convention: a favourable excursion is never below the signed move
        # to the extreme in the entry's own direction.
        sign = 1 if entry.direction is Direction.LONG else -1
        if got["final_price"] is not None and got["final_return"] is not None:
            expected = sign * (float(got["final_price"]) - entry.entry_price)
            if abs(expected - float(got["final_return"])) > 1e-9:
                mismatches.append(f"{entry.candidate_key}: final_return sign convention")
    if mismatches:
        findings.append(f"brute-force cross-check mismatches: {mismatches[:5]}")

    # Partition parity on the same real tape.
    if len(bars) > 10 and entries:
        midpoint = entries[len(entries) // 2].entry_ts
        parts = build_outcome_partitions(
            [("p1", bars[0][1], midpoint), ("p2", midpoint + 1, bars[-1][1])], spec
        )
        part_frames = [
            pd.DataFrame(stream_outcomes(bars, anchors, spec, primary_interval=p.primary_interval))
            for p in parts
        ]
        try:
            merged = merge_outcome_partitions(part_frames, parts)
            assert_partition_parity(frame, merged, context="infra smoke")
            parity = {"passed": True, "partitions": [p.partition_id for p in parts]}
        except Exception as err:  # surfaced as a finding, never swallowed
            parity = {"passed": False, "error": str(err)}
            findings.append(f"partition parity failed: {err}")
    else:
        parity = {"passed": None, "reason": "insufficient data"}

    manifest = write_outcome_artifacts(
        out,
        entries=entries, records=records, spec=spec,
        study_id="forward_outcomes_infra_smoke", source_period="infra_smoke",
        authorization_sha256="infra_smoke_not_a_study",
        source_freeze_sha256="infra_smoke_not_a_study",
        source_identity={
            "catalog": str(catalog_path), "bar_type": bar_type, "date": date,
            "bar_count": len(bars),
        },
        selector_identity={"selector_id": "infra_smoke_time_grid", "step_seconds": step_seconds},
    )
    reconciliation = reconcile_outcome_artifacts(out)
    if not reconciliation["passed"]:
        findings.append(f"reconciliation failed: {reconciliation['findings']}")

    status_counts = (
        frame["outcome_status"].value_counts().to_dict() if not frame.empty else {}
    )
    report = {
        "status": "PASS" if not findings else "FAIL",
        "date": date,
        "output_dir": str(out),
        "bars": len(bars),
        "entries": len(entries),
        "outcome_rows": int(len(frame)),
        "outcome_status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "cross_checked_entries": len(sample),
        "partition_parity": parity,
        "reconciliation": reconciliation,
        "spec_sha256": manifest["spec_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "findings": findings,
    }
    (out / "infra_smoke_report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Forward-outcome infrastructure smoke")
    parser.add_argument("--date", default="2021-06-01")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--bar-type", default=DEFAULT_BAR_TYPE)
    parser.add_argument("--step-seconds", type=int, default=300)
    args = parser.parse_args()

    report = run_infra_smoke(
        args.date,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        catalog_path=Path(args.catalog),
        bar_type=args.bar_type,
        step_seconds=args.step_seconds,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
