"""Parity Event Ledger First-Divergence Localization Tool.
=========================================================

Compares two execution/event ledgers (e.g. offline research vs NT event-loop live runtime)
and pinpoints the EXACT earliest timestamp and stage of divergence.

Ordered Stages:
  1. input
  2. completed_bar
  3. session
  4. regime
  5. candidate
  6. feature_snapshot
  7. score
  8. trigger
  9. order
  10. fill
  11. exit

Usage:
  python scripts/find_first_parity_divergence.py --reference ledger_a.jsonl --runtime ledger_b.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ORDERED_STAGES = [
    "input",
    "completed_bar",
    "session",
    "regime",
    "candidate",
    "feature_snapshot",
    "score",
    "trigger",
    "order",
    "fill",
    "exit",
]


def load_ledger(path: Path) -> List[Dict[str, Any]]:
    events = []
    if not path.exists():
        raise FileNotFoundError(f"Ledger file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                events.append(json.loads(line_str))
    return events


def compare_ledgers(
    ref_events: List[Dict[str, Any]],
    run_events: List[Dict[str, Any]],
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Compares two ledgers and returns (is_identical, divergence_report)."""
    # Key by (timestamp, stage, key)
    min_len = min(len(ref_events), len(run_events))
    last_matching_stage = "start"

    for i in range(min_len):
        ref = ref_events[i]
        run = run_events[i]

        ts_ref = ref.get("timestamp")
        ts_run = run.get("timestamp")
        stage_ref = ref.get("stage", "unknown")
        stage_run = run.get("stage", "unknown")

        if ts_ref != ts_run or stage_ref != stage_run:
            return False, {
                "timestamp": ts_ref or ts_run,
                "key": ref.get("key") or run.get("key"),
                "last_matching_stage": last_matching_stage,
                "first_failing_stage": stage_run if stage_ref == stage_run else f"{stage_ref}_vs_{stage_run}",
                "detail": f"Index {i} event mismatch: Ref=(ts={ts_ref}, stage={stage_ref}) vs Run=(ts={ts_run}, stage={stage_run})",
            }

        # Compare payloads or hashes
        ref_payload = ref.get("payload", {})
        run_payload = run.get("payload", {})
        ref_hash = ref.get("hash")
        run_hash = run.get("hash")

        if ref_hash and run_hash and ref_hash != run_hash:
            # Find differing field if payload exists
            diff_field = None
            diff_ref_val = None
            diff_run_val = None
            for k in set(ref_payload.keys()).union(run_payload.keys()):
                if ref_payload.get(k) != run_payload.get(k):
                    diff_field = k
                    diff_ref_val = ref_payload.get(k)
                    diff_run_val = run_payload.get(k)
                    break

            return False, {
                "timestamp": ts_ref,
                "key": ref.get("key"),
                "last_matching_stage": last_matching_stage,
                "first_failing_stage": stage_ref,
                "field": diff_field,
                "reference": diff_ref_val,
                "runtime": diff_run_val,
                "ref_hash": ref_hash,
                "run_hash": run_hash,
            }

        if ref_payload != run_payload:
            diff_field = None
            diff_ref_val = None
            diff_run_val = None
            for k in set(ref_payload.keys()).union(run_payload.keys()):
                if ref_payload.get(k) != run_payload.get(k):
                    diff_field = k
                    diff_ref_val = ref_payload.get(k)
                    diff_run_val = run_payload.get(k)
                    break
            return False, {
                "timestamp": ts_ref,
                "key": ref.get("key"),
                "last_matching_stage": last_matching_stage,
                "first_failing_stage": stage_ref,
                "field": diff_field,
                "reference": diff_ref_val,
                "runtime": diff_run_val,
            }

        last_matching_stage = stage_ref

    if len(ref_events) != len(run_events):
        return False, {
            "timestamp": "END_OF_STREAM",
            "last_matching_stage": last_matching_stage,
            "first_failing_stage": "stream_length",
            "detail": f"Ledger length mismatch: Reference={len(ref_events)} vs Runtime={len(run_events)}",
        }

    return True, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Find earliest parity divergence between two event ledgers")
    ap.add_argument("--reference", type=str, required=True, help="Reference ledger JSONL")
    ap.add_argument("--runtime", type=str, required=True, help="Runtime ledger JSONL")
    args = ap.parse_args()

    ref_path = Path(args.reference)
    run_path = Path(args.runtime)

    try:
        ref_events = load_ledger(ref_path)
        run_events = load_ledger(run_path)
    except Exception as e:
        print(f"Error loading ledgers: {e}", file=sys.stderr)
        return 2

    identical, div = compare_ledgers(ref_events, run_events)
    if identical:
        print("PARITY_CLEAR: Ledgers match bit-exactly across all timestamps and stages.")
        return 0
    else:
        print("FIRST_DIVERGENCE")
        print(f"timestamp={div.get('timestamp')}")
        if div.get("key"):
            print(f"key={div.get('key')}")
        print(f"last_matching_stage={div.get('last_matching_stage')}")
        print(f"first_failing_stage={div.get('first_failing_stage')}")
        if div.get("field"):
            print(f"field={div.get('field')}")
            print(f"reference={div.get('reference')}")
            print(f"runtime={div.get('runtime')}")
        if div.get("detail"):
            print(f"detail={div.get('detail')}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
