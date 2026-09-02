#!/usr/bin/env python3
"""Compare the legacy episode-engine ledger (ARMED/REARM/TERMINATE/EMIT) with the host's
trigger ledger (enter:WATCH / reset:new_leg / reset:regime changed / entry).

    python scripts/parity/compare_episode_ledgers.py --legacy legacy.jsonl --host host.jsonl [--start-ns N]

Event mapping (host -> legacy):
    enter WATCH                      -> ARMED
    expire WATCH reason reset:...new_leg  -> REARM
    expire WATCH reason reset:regime_1m.changed -> TERMINATE
    candidate                        -> EMIT
A legacy REARM/TERMINATE with no armed state has no host counterpart (the host only
expires an active state); those are counted separately and are not divergences.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def load(path: Path) -> List[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def normalize_host(rows: List[dict]) -> List[tuple]:
    out = []
    for r in rows:
        if r["stage"] == "candidate":
            out.append((int(r["timestamp"]), "EMIT"))
        elif r["stage"] == "trigger":
            p = r["payload"]
            if p["kind"] == "enter" and p["state"] == "WATCH":
                out.append((int(r["timestamp"]), "ARMED"))
            elif p["kind"] == "expire" and p["state"] == "WATCH":
                reason = str(p.get("reason", ""))
                out.append((int(r["timestamp"]), "TERMINATE" if "changed" in reason else "REARM"))
    return out


def normalize_legacy(rows: List[dict], armed_only: bool = True) -> tuple[List[tuple], Counter]:
    out, unarmed = [], Counter()
    armed = False
    for r in rows:
        action = r["key"]
        ts = int(r["timestamp"])
        if action == "ARMED":
            armed = True
            out.append((ts, "ARMED"))
        elif action in ("REARM", "TERMINATE"):
            if armed:
                out.append((ts, action))
            else:
                unarmed[action] += 1
            armed = False
        elif action == "EMIT":
            out.append((ts, "EMIT"))
    return out, unarmed


def compare(legacy: List[dict], host: List[dict], start_ns: Optional[int] = None) -> Dict:
    l, unarmed = normalize_legacy(legacy)
    h = normalize_host(host)
    if start_ns is not None:
        l = [x for x in l if x[0] >= start_ns]
        h = [x for x in h if x[0] >= start_ns]
    l_sorted, h_sorted = sorted(l), sorted(h)
    first = None
    for i, (a, b) in enumerate(zip(l_sorted, h_sorted)):
        if a != b:
            first = {"index": i, "legacy": a, "host": b}
            break
    if first is None and len(l_sorted) != len(h_sorted):
        i = min(len(l_sorted), len(h_sorted))
        first = {"index": i, "legacy": l_sorted[i] if i < len(l_sorted) else None, "host": h_sorted[i] if i < len(h_sorted) else None}
    return {"passed": first is None, "legacy_events": len(l_sorted), "host_events": len(h_sorted),
            "legacy_by_action": dict(Counter(x[1] for x in l_sorted)), "host_by_action": dict(Counter(x[1] for x in h_sorted)),
            "legacy_unarmed_resets_ignored": dict(unarmed), "first_divergence": first}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--start-ns", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    report = compare(load(Path(a.legacy)), load(Path(a.host)), a.start_ns)
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
