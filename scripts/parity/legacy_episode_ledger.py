#!/usr/bin/env python3
"""Reference event ledger for Shape B from the LEGACY episode runtime.

Drives the sealed implementation -- ``research_workflow.population_runtime.EpisodePopulationRuntime``
(``EpisodePopulationEngine`` + ``CompletedRegimeStateFeed``) fed exactly as
``generic_collector._episode_dispatch_1s`` feeds it -- over a catalog window and records
every engine decision (ARMED / REARM / TERMINATE / EMIT) with its timestamp.  The host's
trigger ledger is compared against this file by ``compare_episode_ledgers``.

    python scripts/parity/legacy_episode_ledger.py --start 2021-01-01 --end 2021-01-05 --out <path.jsonl>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MAIN_REPO = ROOT.parent / "Nautilus Trader"


def build_ledger(start: str, end: str, *, warmup_days: int = 5, primary_start_ns: int | None = None) -> list[dict]:
    from backtests.nt_runtime.data_plan import resolve_catalog_plan
    from utils.runner.data import CausalDataLoader
    from features.trackers.regime_dual_ema import DualEmaRegimeTracker
    from research_workflow.completed_regime_state import CompletedRegimeStateFeed
    from research_workflow.episode_population import EpisodeAction
    from research_workflow.population_runtime import resolve_population_runtime

    plan = resolve_catalog_plan("NQ", start, end, warmup_days=warmup_days, repo_root=MAIN_REPO)
    loader = CausalDataLoader(plan.catalog_path)
    bars_1s = loader.load_bars(plan.bar_type_1s, plan.warmup_start_dt, plan.end_dt)
    bars_1m = loader.load_bars(plan.bar_type_1m, plan.warmup_start_dt, plan.end_dt)
    events = sorted([(int(b.ts_init), 0, b) for b in bars_1s] + [(int(b.ts_init), 1, b) for b in bars_1m], key=lambda t: (t[0], t[1]))

    lifecycle = {"arm_condition": {"kind": "directional_adverse_excursion", "threshold_atr": 1.0, "price_source": "completed_1s_intrabar"},
                 "required_event": {"kind": "direction_relation", "source": "generic_completed_5s_regime_state", "bar_state": "completed",
                                    "availability_timestamp": "completed_source_bar_ts_init", "relation": "opposite_prevailing", "active_at_arm_counts": True},
                 "emit_condition": {"kind": "direction_transition", "source": "generic_completed_5s_regime_state", "bar_state": "completed",
                                    "availability_timestamp": "completed_source_bar_ts_init", "from_relation": "opposite_prevailing",
                                    "to_relation": "aligned_prevailing", "strictly_after_arm": True},
                 "rearm_on": ["new_favorable_extreme"], "terminate_on": ["prevailing_regime_flip"], "max_candidates_per_episode": 1}
    runtime = resolve_population_runtime({"episode_lifecycle": lifecycle})
    regime = DualEmaRegimeTracker(timeframe="1m")
    feed = CompletedRegimeStateFeed(["5s", "5m"])
    ledger: list[dict] = []
    engine = runtime._engine
    real_on_event = engine.on_event

    def recording_on_event(snapshot):
        decision = real_on_event(snapshot)
        if decision.action in (EpisodeAction.ARMED, EpisodeAction.REARM, EpisodeAction.TERMINATE, EpisodeAction.EMIT):
            ts = int(decision.timestamp_ns)
            if primary_start_ns is None or ts >= primary_start_ns:
                ledger.append({"timestamp": ts, "stage": "trigger", "key": decision.action.value,
                               "payload": {"action": decision.action.value, "reason": decision.reason,
                                           "transition": (snapshot.transition_from, snapshot.transition_to)}})
        return decision
    engine.on_event = recording_on_event

    active_dir = 0
    for ts, kind, b in events:
        if kind == 1:
            old = regime.regime
            new = regime.update(float(b.high), float(b.low), float(b.close))
            if new != old and new != 0:
                runtime.on_prevailing_regime(direction=new, start_ns=int(b.ts_init), start_price=float(b.open))
                active_dir = new
            continue
        o, h, l, c, v = float(b.open), float(b.high), float(b.low), float(b.close), float(b.volume)
        transitions_5s = []
        for tr in feed.on_completed_1s_bar(ts_event=int(b.ts_event), ts_init=int(b.ts_init), open=o, high=h, low=l, close=c, volume=v):
            if tr.timeframe == "5s":
                transitions_5s.append(tr)
        cur5s = feed.state("5s", decision_ts=int(b.ts_init))
        runtime.on_completed_1s(ts_event=int(b.ts_event), ts_init=int(b.ts_init), open=o, high=h, low=l, close=c, volume=v,
                                completed_1m_atr=regime.atr, completed_5s_state=(int(cur5s.regime) if cur5s is not None else None),
                                completed_5s_transitions=tuple(transitions_5s))
    return ledger


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--warmup-days", type=int, default=5)
    a = ap.parse_args()
    primary_start = int(pd.Timestamp(f"{a.start} 00:00:00", tz="UTC").value)
    ledger = build_ledger(a.start, a.end, warmup_days=a.warmup_days, primary_start_ns=primary_start)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for row in ledger:
            fh.write(json.dumps(row) + "\n")
    from collections import Counter
    print(json.dumps({"rows": len(ledger), "by_action": dict(Counter(r["key"] for r in ledger)), "out": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
