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
    ap.add_argument("--label-column", help="binary label column for the fit/freeze stages (required unless the target contract declares one)")
    ap.add_argument("--period", default="train")
    ap.add_argument("--closure-outcome"); ap.add_argument("--closure-decision")
    ap.add_argument("--smoke-date", help="v2: bounded smoke day (YYYY-MM-DD)")
    ap.add_argument("--years", help="v2: comma-separated subset of partition years")
    ap.add_argument("--windows", help="v2: comma-separated subset of declared chronology.windows (narrow only)")
    ap.add_argument("--studies-root", help="v2: machine-local root holding parent studies for frozen external scores")
    ap.add_argument("--chunked-batch-rows", type=int, default=0,
                    help="v2: opt-in bounded-memory collection -- flush candidates/observations to disk every N rows "
                         "instead of holding a whole partition in memory. 0 (default) preserves exact pre-existing "
                         "behaviour. See artifacts/platform_v2/chunked_sink_flush/README.md.")
    ap.add_argument("--chunked-batch-bytes", type=int, default=None,
                    help="v2: secondary byte-estimate flush trigger, inert unless --chunked-batch-rows > 0. Flushes on "
                         "whichever of the row or byte threshold is reached first. Defaults to the module's "
                         "DEFAULT_BATCH_BYTES (256 MiB) when --chunked-batch-rows is set and this is not given.")
    ns = ap.parse_args()
    from research_workflow.lifecycle_v2 import is_v2_study
    if is_v2_study(Path(ns.study)):
        from research_workflow.governed_controller_v2 import V2StudyController
        from research_workflow.lifecycle_v2 import V2Options
        closure = {"outcome": ns.closure_outcome, "terminal_decision": ns.closure_decision} if (ns.closure_outcome or ns.closure_decision) else None
        v2_kwargs = dict(execute=ns.execute_authorized, smoke_date=ns.smoke_date, years=[int(y) for y in ns.years.split(",")] if ns.years else None,
                         windows=[w.strip() for w in ns.windows.split(",") if w.strip()] if ns.windows else None,
                         closure=closure, studies_root=Path(ns.studies_root) if ns.studies_root else None, max_runtime=ns.max_runtime,
                         chunked_batch_rows=ns.chunked_batch_rows)
        if ns.chunked_batch_bytes is not None:
            v2_kwargs["chunked_batch_bytes"] = ns.chunked_batch_bytes
        opts = V2Options(**v2_kwargs)
        card = V2StudyController(ns.study, options=opts, owned_paths=tuple(ns.owned_path), max_runtime=ns.max_runtime,
                                 stale_progress_timeout=ns.stale_progress_timeout, rss_limit_mb=ns.rss_limit_mb).run(
                                     through=ns.through, inspect=ns.inspect, dry_run=ns.dry_run)
        print(compact_card(card, as_json=ns.json))
        return 2 if card["STATUS"] == "BLOCKED" else 0
    from research_workflow.policy import OldRuntimePolicyError, assert_old_runtime_allowed
    try:
        assert_old_runtime_allowed(Path(ns.study))
    except OldRuntimePolicyError as exc:
        card = {"STATUS": "BLOCKED", "state": "NEEDS_COMPILE", "stage": "policy", "blocker_code": "OLD_RUNTIME_LEGACY_ONLY", "reason": str(exc),
                "artifact": None, "sha256": None, "next_state": "NEEDS_COMPILE", "failure_packet": None, "test_counts": {}}
        print(compact_card(card, as_json=ns.json))
        return 2
    actions = None
    if ns.execute_authorized:
        from research_workflow.controller_actions import production_actions
        supplied = [ns.analysis_frame, ns.score_columns_json, ns.target_column]
        if any(supplied) and not all(supplied): ap.error("analysis options must be supplied together")
        import json
        config = {"frame_path": ns.analysis_frame, "score_columns": json.loads(ns.score_columns_json), "target_column": ns.target_column} if all(supplied) else None
        closure = {"outcome": ns.closure_outcome, "terminal_decision": ns.closure_decision} if (ns.closure_outcome or ns.closure_decision) else None
        actions = production_actions(execute_authorized=True, analysis_config=config, label_column=ns.label_column, period=ns.period, closure=closure)
    card = GovernedStudyController(ns.study, actions=actions, owned_paths=tuple(ns.owned_path), max_runtime=ns.max_runtime,
                                  stale_progress_timeout=ns.stale_progress_timeout, rss_limit_mb=ns.rss_limit_mb).run(
                                      through=ns.through, inspect=ns.inspect, dry_run=ns.dry_run)
    print(compact_card(card, as_json=ns.json))
    return 2 if card["STATUS"] == "BLOCKED" else 0
if __name__ == "__main__": raise SystemExit(main())
