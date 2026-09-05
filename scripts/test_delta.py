"""Run a pytest scope ONCE and report only what is NEW against the committed failure baseline.

    python scripts/test_delta.py research_workflow/tests scripts/tests          # compare against config/test_failure_baseline.json
    python scripts/test_delta.py scripts/tests/test_workspace.py --json
    python scripts/test_delta.py research_workflow/tests scripts/tests features/tests tests --update-baseline --reason "..."

``@pytest.mark.slow`` tests (real data replay; scripts/tests carries several that run for tens of minutes) are
excluded by default so one broad run stays in minutes; ``--include-slow`` lifts the filter.

Why: every agent used to run the suite on its branch AND on clean main to rediscover the same
pre-existing failures (33 in research_workflow/tests at the 2026-09-04 platform state). The baseline is
generated deterministically once, committed, and every later run is classified against it:

    NEW_FAILURE                    failed now, not in the baseline            -> the only thing an agent must act on
    KNOWN_BASELINE_FAILURE         failed now, recorded in the baseline       -> pre-existing, not yours
    BASELINE_FAILURE_NOW_FIXED     recorded as failing, passed now           -> update the baseline (explicitly) when you commit the fix
    ENVIRONMENTAL_MISSING_ARTIFACT failed now on a missing file/root/package -> this machine, not the code

A known failure is only "known" inside the scope it was recorded under: a baseline entry whose recorded
scope does not cover the node is reported as NEW_FAILURE_OUTSIDE_BASELINE_SCOPE, never silently allowed.
The baseline changes only through ``--update-baseline --reason`` (an explicit, reviewable commit).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "config" / "test_failure_baseline.json"
SUMMARY_RE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+?)(?:\s+-\s+(.*))?$")
ENV_PATTERNS = re.compile(r"FileNotFoundError|No such file or directory|DATASET_ROOT_UNRESOLVED|RAW_YEAR_MISSING|ModuleNotFoundError|"
                          r"CATALOG_NOT_FOUND|catalog .* not found|could not find|is not a directory|PermissionError|WinError 32|"
                          r"REFERENCE_TABLE_MISSING|not installed|MISSING_ARTIFACT|no catalog_roots", re.IGNORECASE)


def _git(args: List[str]) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


def run_pytest(scope: List[str], extra: List[str]) -> Tuple[Dict[str, Tuple[str, str]], int, str]:
    """Run pytest once with ``-rA`` and return {node_id: (outcome, message)}, the exit code and the raw tail."""
    cmd = [sys.executable, "-m", "pytest", *scope, "-q", "-rA", "-p", "no:cacheprovider", *extra]
    import os
    env = {**os.environ, "COLUMNS": "400", "PYTHONIOENCODING": "utf-8"}   # -rA summary lines are width-truncated; keep the message
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    results: Dict[str, Tuple[str, str]] = {}
    for line in r.stdout.splitlines():
        m = SUMMARY_RE.match(line.strip())
        if m:
            outcome, node, msg = m.group(1), m.group(2), (m.group(3) or "")
            results[node] = (outcome, msg)
    return results, r.returncode, "\n".join(r.stdout.splitlines()[-3:])


def load_baseline(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "platform_commit": None, "generated_at_utc": None, "scopes": [], "expected_failures": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _scope_covers(scopes: List[str], node: str) -> bool:
    n = node.replace("\\", "/")
    return any(n.startswith(s.replace("\\", "/").rstrip("/") + "/") or n.startswith(s.replace("\\", "/")) for s in scopes)


def classify(results: Dict[str, Tuple[str, str]], baseline: Dict[str, Any], scope: List[str]) -> Dict[str, Any]:
    expected = {e["node_id"]: e for e in baseline.get("expected_failures", [])}
    base_scopes = list(baseline.get("scopes") or [])
    out: Dict[str, List[Dict[str, Any]]] = {"NEW_FAILURE": [], "NEW_FAILURE_OUTSIDE_BASELINE_SCOPE": [], "KNOWN_BASELINE_FAILURE": [],
                                            "BASELINE_FAILURE_NOW_FIXED": [], "ENVIRONMENTAL_MISSING_ARTIFACT": []}
    for node, (outcome, msg) in sorted(results.items()):
        failed = outcome in ("FAILED", "ERROR")
        if failed:
            if node in expected:
                out["KNOWN_BASELINE_FAILURE"].append({"node_id": node, "classification": expected[node].get("classification"), "reason": expected[node].get("reason")})
            elif ENV_PATTERNS.search(msg or ""):
                out["ENVIRONMENTAL_MISSING_ARTIFACT"].append({"node_id": node, "message": msg[:300]})
            elif base_scopes and not _scope_covers(base_scopes, node):
                out["NEW_FAILURE_OUTSIDE_BASELINE_SCOPE"].append({"node_id": node, "message": msg[:300],
                                                                  "note": "this path was never baselined; classify it explicitly (--update-baseline) or fix it"})
            else:
                out["NEW_FAILURE"].append({"node_id": node, "message": msg[:300]})
        elif node in expected and outcome in ("PASSED", "XPASS"):
            out["BASELINE_FAILURE_NOW_FIXED"].append({"node_id": node, "reason": expected[node].get("reason")})
    ran = len(results)
    return {"ran": ran, "passed": sum(1 for o, _ in results.values() if o == "PASSED"), "failed": sum(1 for o, _ in results.values() if o in ("FAILED", "ERROR")),
            "counts": {k: len(v) for k, v in out.items()}, **out}


def update_baseline(path: Path, results: Dict[str, Tuple[str, str]], scope: List[str], reason: str, prior: Dict[str, Any]) -> Dict[str, Any]:
    prior_entries = {e["node_id"]: e for e in prior.get("expected_failures", [])}
    scopes_norm = sorted({s.replace("\\", "/").rstrip("/") for s in scope})
    now = datetime.now(timezone.utc).isoformat()
    head = _git(["rev-parse", "HEAD"]) or None
    entries: List[Dict[str, Any]] = []
    # keep prior entries whose scope was NOT re-run (they were not observed this time)
    for node, e in prior_entries.items():
        if not _scope_covers(scopes_norm, node):
            entries.append(e)
    for node, (outcome, msg) in sorted(results.items()):
        if outcome in ("FAILED", "ERROR"):
            old = prior_entries.get(node)
            cls = "environmental" if ENV_PATTERNS.search(msg or "") else "pre_existing"
            entries.append({"node_id": node, "classification": (old or {}).get("classification") or cls,
                            "reason": (old or {}).get("reason") or reason, "first_seen_commit": (old or {}).get("first_seen_commit") or head,
                            "last_seen_commit": head, "message": (msg or "")[:200]})
    doc = {"schema_version": 1, "platform_commit": head, "platform_tag": _git(["describe", "--tags", "--abbrev=0"]) or None,
           "generated_at_utc": now, "python": sys.version.split()[0], "reason": reason,
           "marker_filter": "not slow (default; --include-slow lifts it)",
           "scopes": sorted(set(scopes_norm) | {s for s in (prior.get("scopes") or []) if not any(_scope_covers([n], s) for n in scopes_norm)}),
           "environment_requirements": prior.get("environment_requirements") or [
               "~/.nt_research/config.yaml with catalog_roots (Dataset V2 catalogs), model_root, leases_dir, worktree_root",
               "psutil, pandas_market_calendars, nautilus_trader installed", "Windows paths (some tests are Windows-specific)"],
           "expected_failures": sorted(entries, key=lambda e: e["node_id"])}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scope", nargs="+", help="pytest paths / node ids to run ONCE")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--update-baseline", action="store_true", help="rewrite the baseline for the requested scopes (explicit, reviewable)")
    ap.add_argument("--reason", help="required with --update-baseline")
    ap.add_argument("--json", action="store_true", help="full JSON card (default: compact card with NEW_FAILURE first)")
    ap.add_argument("--pytest-arg", action="append", default=[], help="extra argument forwarded to pytest (repeatable)")
    ap.add_argument("--include-slow", action="store_true", help="also run @pytest.mark.slow tests (data replay); excluded by default so a broad run stays minutes, not hours")
    ns = ap.parse_args(argv)
    if not ns.include_slow:
        ns.pytest_arg = ["-m", "not slow", *ns.pytest_arg]
    baseline_path = Path(ns.baseline)
    if ns.update_baseline and not (ns.reason or "").strip():
        print(json.dumps({"STATUS": "FAIL", "error": "--update-baseline requires --reason"})); return 2
    prior = load_baseline(baseline_path)
    results, rc, tail = run_pytest(ns.scope, ns.pytest_arg)
    if not results:
        print(json.dumps({"STATUS": "FAIL", "error": "pytest produced no -rA summary (collection error?)", "exit_code": rc, "tail": tail})); return 2
    if ns.update_baseline:
        doc = update_baseline(baseline_path, results, ns.scope, ns.reason, prior)
        print(json.dumps({"STATUS": "OK", "action": "BASELINE_UPDATED", "baseline": str(baseline_path), "platform_commit": doc["platform_commit"],
                          "scopes": doc["scopes"], "expected_failures": len(doc["expected_failures"]), "ran": len(results)}, default=str))
        return 0
    rep = classify(results, prior, ns.scope)
    new = rep["NEW_FAILURE"] + rep["NEW_FAILURE_OUTSIDE_BASELINE_SCOPE"]
    status = "OK" if not new else "NEW_FAILURES"
    card = {"STATUS": status, "baseline": str(baseline_path), "baseline_commit": prior.get("platform_commit"), "head": _git(["rev-parse", "--short", "HEAD"]),
            "ran": rep["ran"], "passed": rep["passed"], "failed": rep["failed"], "counts": rep["counts"],
            "NEW_FAILURE": rep["NEW_FAILURE"], "NEW_FAILURE_OUTSIDE_BASELINE_SCOPE": rep["NEW_FAILURE_OUTSIDE_BASELINE_SCOPE"],
            "BASELINE_FAILURE_NOW_FIXED": [e["node_id"] for e in rep["BASELINE_FAILURE_NOW_FIXED"]],
            "ENVIRONMENTAL_MISSING_ARTIFACT": [e["node_id"] for e in rep["ENVIRONMENTAL_MISSING_ARTIFACT"]],
            "KNOWN_BASELINE_FAILURE": [e["node_id"] for e in rep["KNOWN_BASELINE_FAILURE"]] if ns.json else len(rep["KNOWN_BASELINE_FAILURE"])}
    print(json.dumps(card, indent=2 if ns.json else None, default=str))
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
