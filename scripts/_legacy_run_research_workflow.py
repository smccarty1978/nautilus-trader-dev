#!/usr/bin/env python3
"""Advance an artifact-governed study to its next real terminal gate."""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from research_workflow.workflow_engine import run_workflow
def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--study", required=True); p.add_argument("--advance", action="store_true"); p.add_argument("--smoke", action="store_true")
    p.add_argument("--execute-train", action="store_true",
                   help="permit partitioned TRAIN collection once the study reaches an authorized train gate (touches data)")
    a = p.parse_args()
    if not a.advance: p.error("--advance is required to execute workflow actions")
    result = run_workflow(a.study, smoke=a.smoke, execute_authorized=a.execute_train)
    print(json.dumps(result, indent=2, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
