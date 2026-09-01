"""Compact public CLI for the governed-study controller."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from research_workflow.governed_controller import GovernedStudyController, compact_card

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    ap.add_argument("--through", default="seal")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--owned-path", action="append", default=[])
    ap.add_argument("--max-runtime", type=float, default=600)
    ap.add_argument("--stale-progress-timeout", type=float, default=120)
    ap.add_argument("--rss-limit-mb", type=float)
    ap.add_argument("--execute-authorized", action="store_true")
    ap.add_argument("--analysis-frame")
    ap.add_argument("--score-columns-json")
    ap.add_argument("--target-column")
    ns = ap.parse_args()
    actions = None
    if ns.execute_authorized:
        from research_workflow.controller_actions import production_actions
        supplied = [ns.analysis_frame, ns.score_columns_json, ns.target_column]
        if any(supplied) and not all(supplied): ap.error("analysis options must be supplied together")
        import json
        config = {"frame_path": ns.analysis_frame, "score_columns": json.loads(ns.score_columns_json), "target_column": ns.target_column} if all(supplied) else None
        actions = production_actions(execute_authorized=True, analysis_config=config)
    card = GovernedStudyController(ns.study, actions=actions, owned_paths=tuple(ns.owned_path), max_runtime=ns.max_runtime,
                                  stale_progress_timeout=ns.stale_progress_timeout, rss_limit_mb=ns.rss_limit_mb).run(
                                      through=ns.through, inspect=ns.inspect, dry_run=ns.dry_run)
    print(compact_card(card, as_json=ns.json))
    return 2 if card["STATUS"] == "BLOCKED" else 0
if __name__ == "__main__": raise SystemExit(main())
