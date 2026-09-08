"""Run a pytest scope ONCE and report only what is NEW against the committed failure baseline.

    python scripts/test_delta.py research_workflow/tests scripts/tests          # compare against config/test_failure_baseline.json
    python scripts/test_delta.py scripts/tests/test_workspace.py --json
    python scripts/test_delta.py research_workflow/tests scripts/tests features/tests tests --update-baseline --reason "..."

``@pytest.mark.slow`` tests (real data replay; scripts/tests carries several that run for tens of minutes) are
excluded by default but the measured Wave 1 broad run still took 74m41s; ``--include-slow`` lifts the filter.

Why: every agent used to run the suite on its branch AND on clean main to rediscover the same
pre-existing failures (33 in research_workflow/tests at the 2026-09-04 platform state). The baseline is
generated deterministically once, committed, and every later run is classified against it:

    NEW_FAILURE                    failed now, not in the baseline            -> the only thing an agent must act on
    KNOWN_BASELINE_FAILURE         failed now, recorded in the baseline       -> pre-existing, not yours
    BASELINE_FAILURE_NOW_FIXED     recorded as failing, passed now           -> update the baseline (explicitly) when you commit the fix
    ENVIRONMENTAL_MISSING_ARTIFACT reserved legacy output category; never inferred from error text

A known failure is only "known" inside the scope it was recorded under: a baseline entry whose recorded
scope does not cover the node is reported as NEW_FAILURE_OUTSIDE_BASELINE_SCOPE, never silently allowed.
The baseline changes only through ``--update-baseline --reason`` (an explicit, reviewable commit).
"""
from __future__ import annotations

import argparse
import importlib.metadata
import platform
import tempfile
from contextlib import nullcontext
import time
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
# Missing imports, paths and artifacts are never automatically environmental.
ENV_PATTERNS = re.compile(r"(?!)")


def environment_identity() -> Dict[str, Any]:
    packages = {}
    for name in ('pytest', 'numpy', 'pandas', 'psutil', 'pandas_market_calendars', 'nautilus_trader'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {'python': sys.version, 'platform': platform.platform(), 'packages': packages}


def baseline_issues(baseline: Dict[str, Any], reference: Optional[str] = None) -> List[str]:
    reference = _git(['merge-base', 'HEAD', 'main']) if reference is None else reference
    issues = []
    if baseline.get('schema_version') != 2:
        issues.append('BASELINE_SCHEMA_REQUIRES_EXPLICIT_MIGRATION')
    if not reference or baseline.get('platform_commit') != reference:
        issues.append('BASELINE_COMMIT_MISMATCH')
    if not baseline.get('environment') or baseline['environment'] != environment_identity():
        issues.append('BASELINE_ENVIRONMENT_MISMATCH')
    return issues



def _git(args: List[str]) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


def run_pytest(scope: List[str], extra: List[str]) -> Tuple[Dict[str, Tuple[str, str]], int, str]:
    """Capture full pytest reports and phase timings, never truncated summary signatures."""
    import os
    plugin = """import json, os
from pathlib import Path
reports = {}
def pytest_runtest_logreport(report):
    reports.setdefault(report.nodeid, []).append({'phase': report.when, 'outcome': report.outcome,
        'message': str(report.longrepr) if report.failed else '', 'seconds': report.duration, 'wasxfail': hasattr(report, 'wasxfail')})
def pytest_collectreport(report):
    if report.failed:
        reports.setdefault(report.nodeid, []).append({'phase': 'collection', 'outcome': 'failed',
            'message': str(report.longrepr), 'seconds': 0.0})
def pytest_sessionfinish(session, exitstatus):
    Path(os.environ['TEST_DELTA_REPORT']).write_text(json.dumps(reports), encoding='utf-8')
"""
    started = time.perf_counter()
    with nullcontext(tempfile.mkdtemp(prefix='test_delta_')) as td:
        d = Path(td)
        (d / 'test_delta_capture.py').write_text(plugin, encoding='utf-8')
        report_path = d / 'reports.json'
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1', 'TEST_DELTA_REPORT': str(report_path),
               'PYTHONPATH': td + os.pathsep + os.environ.get('PYTHONPATH', '')}
        cmd = [sys.executable, '-m', 'pytest', *scope, '-q', '-rA', '-p', 'no:cacheprovider',
               '-p', 'test_delta_capture', *extra]
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        reports = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    # Remove only the files this runner created; never recursively delete a subprocess directory.
    for name in ('test_delta_capture.py', 'reports.json'):
        (d / name).unlink(missing_ok=True)
    try:
        d.rmdir()
    except OSError:
        pass  # Unexpected subprocess-created files are left for inspection.
    results = {}
    timings = {}
    for node, phases in reports.items():
        failures = [p for p in phases if p['outcome'] == 'failed']
        call = next((p for p in phases if p['phase'] == 'call'), None)
        outcome = ('ERROR' if any(p['phase'] != 'call' for p in failures) else 'FAILED') if failures else (
            'PASSED' if call and call['outcome'] == 'passed' else 'SKIPPED')
        if not failures and any(p.get('wasxfail') for p in phases):
            outcome = 'XPASS' if call and call['outcome'] == 'passed' else 'XFAIL'
        results[node] = (outcome, '\n'.join(p['phase'] + ': ' + p['message'] for p in failures))
        timings[node] = {'seconds': sum(p['seconds'] for p in phases),
                         'phases': {p['phase']: p['seconds'] for p in phases}}
    run_pytest.last_timings = timings
    run_pytest.last_wall_seconds = time.perf_counter() - started
    return results, r.returncode, '\n'.join((r.stdout + r.stderr).splitlines()[-5:])


def load_baseline(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "platform_commit": None, "generated_at_utc": None, "scopes": [], "expected_failures": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _scope_covers(scopes: List[str], node: str) -> bool:
    n = node.replace('\\', '/')
    return any(n == s or n.startswith(s + '/') or n.startswith(s + '::')
               for s in (str(v).replace('\\', '/').rstrip('/') for v in scopes) if s)


def classify(results: Dict[str, Tuple[str, str]], baseline: Dict[str, Any], scope: List[str],
             reference_commit: Optional[str] = None) -> Dict[str, Any]:
    expected = {e['node_id']: e for e in baseline.get('expected_failures', [])}
    issues = baseline_issues(baseline, reference_commit)
    out = {k: [] for k in ('NEW_FAILURE', 'NEW_FAILURE_OUTSIDE_BASELINE_SCOPE', 'KNOWN_BASELINE_FAILURE',
                           'BASELINE_FAILURE_NOW_FIXED', 'ENVIRONMENTAL_MISSING_ARTIFACT')}
    for node, (outcome, msg) in sorted(results.items()):
        entry = expected.get(node)
        covered = bool(entry and _scope_covers(entry.get('scopes') or [], node)
                       and _scope_covers(baseline.get('scopes') or [], node) and _scope_covers(scope, node))
        if outcome in ('FAILED', 'ERROR'):
            if entry and not covered:
                category, reason = 'NEW_FAILURE_OUTSIDE_BASELINE_SCOPE', 'ENTRY_SCOPE_MISMATCH_OR_MISSING'
            elif not issues and covered and entry.get('message') and msg == entry['message'] and outcome == entry.get('outcome', 'FAILED'):
                out['KNOWN_BASELINE_FAILURE'].append({'node_id': node, 'classification': entry.get('classification'), 'reason': entry.get('reason')})
                continue
            else:
                category = 'NEW_FAILURE'
                reason = ','.join(issues) if issues else ('FAILURE_SIGNATURE_CHANGED_OR_MISSING' if entry else 'UNRECORDED_FAILURE')
            out[category].append({'node_id': node, 'message': msg, 'reason': reason})
        elif entry and covered and not issues and outcome in ('PASSED', 'XPASS'):
            out['BASELINE_FAILURE_NOW_FIXED'].append({'node_id': node, 'reason': entry.get('reason')})
    return {'ran': len(results), 'passed': sum(o == 'PASSED' for o, _ in results.values()),
            'failed': sum(o in ('FAILED', 'ERROR') for o, _ in results.values()),
            'baseline_issues': issues, 'counts': {k: len(v) for k, v in out.items()}, **out}


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
                            "last_seen_commit": head, "message": msg or "", "outcome": outcome, "scopes": scopes_norm})
    doc = {"schema_version": 2, "environment": environment_identity(), "platform_commit": head, "platform_tag": _git(["describe", "--tags", "--abbrev=0"]) or None,
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
    ap.add_argument("--baseline-reference", help="exact approved commit/ref; default merge-base HEAD main")
    ap.add_argument("--check-baseline", action="store_true", help="validate compatibility without running pytest")
    ap.add_argument("--update-baseline", action="store_true", help="rewrite the baseline for the requested scopes (explicit, reviewable)")
    ap.add_argument("--reason", help="required with --update-baseline")
    ap.add_argument("--json", action="store_true", help="full JSON card (default: compact card with NEW_FAILURE first)")
    ap.add_argument("--pytest-arg", action="append", default=[], help="extra argument forwarded to pytest (repeatable)")
    ap.add_argument("--include-slow", action="store_true", help="also run @pytest.mark.slow tests (data replay); excluded by default the measured Wave 1 broad run took 74m41s")
    ns = ap.parse_args(argv)
    if not ns.include_slow:
        ns.pytest_arg = ["-m", "not slow", *ns.pytest_arg]
    baseline_path = Path(ns.baseline)
    if ns.update_baseline and not (ns.reason or "").strip():
        print(json.dumps({"STATUS": "FAIL", "error": "--update-baseline requires --reason"})); return 2
    prior = load_baseline(baseline_path)
    reference = _git(['rev-parse', ns.baseline_reference + '^{commit}']) if ns.baseline_reference else _git(['merge-base', 'HEAD', 'main'])
    issues = baseline_issues(prior, reference)
    if ns.check_baseline:
        print(json.dumps({'STATUS': 'BASELINE_INCOMPATIBLE' if issues else 'OK', 'issues': issues, 'reference_commit': reference}))
        return 2 if issues else 0
    if ns.update_baseline and (_git(['rev-parse', 'HEAD']) != reference or not reference):
        print(json.dumps({'STATUS': 'FAIL', 'error': 'BASELINE_UPDATE_REQUIRES_EXACT_REFERENCE_CHECKOUT'})); return 2
    if ns.update_baseline and issues and any(not _scope_covers(ns.scope, e['node_id']) for e in prior.get('expected_failures', [])):
        print(json.dumps({'STATUS': 'FAIL', 'error': 'CANNOT_REATTEST_UNOBSERVED_INCOMPATIBLE_ENTRIES'})); return 2
    results, rc, tail = run_pytest(ns.scope, ns.pytest_arg)
    failures = sum(o in ('FAILED', 'ERROR') for o, _ in results.values())
    if rc not in (0, 1) or (rc == 1 and not failures) or (rc == 0 and failures):
        print(json.dumps({'STATUS': 'NEW_FAILURES', 'error': 'PYTEST_EXIT_CODE', 'exit_code': rc, 'tail': tail,
                          'per_test_timings': getattr(run_pytest, 'last_timings', {})})); return 2
    if not results:
        print(json.dumps({"STATUS": "FAIL", "error": "pytest produced no -rA summary (collection error?)", "exit_code": rc, "tail": tail})); return 2
    if ns.update_baseline:
        doc = update_baseline(baseline_path, results, ns.scope, ns.reason, prior)
        print(json.dumps({"STATUS": "OK", "action": "BASELINE_UPDATED", "baseline": str(baseline_path), "platform_commit": doc["platform_commit"],
                          "scopes": doc["scopes"], "expected_failures": len(doc["expected_failures"]), "ran": len(results)}, default=str))
        return 0
    rep = classify(results, prior, ns.scope, reference_commit=reference)
    new = rep["NEW_FAILURE"] + rep["NEW_FAILURE_OUTSIDE_BASELINE_SCOPE"]
    status = "OK" if not new else "NEW_FAILURES"
    card = {"STATUS": status, "baseline": str(baseline_path), "baseline_commit": prior.get("platform_commit"), "head": _git(["rev-parse", "--short", "HEAD"]),
            "baseline_issues": rep["baseline_issues"], "pytest_exit_code": rc,
            "wall_seconds": getattr(run_pytest, "last_wall_seconds", None), "per_test_timings": getattr(run_pytest, "last_timings", {}),
            "ran": rep["ran"], "passed": rep["passed"], "failed": rep["failed"], "counts": rep["counts"],
            "NEW_FAILURE": rep["NEW_FAILURE"], "NEW_FAILURE_OUTSIDE_BASELINE_SCOPE": rep["NEW_FAILURE_OUTSIDE_BASELINE_SCOPE"],
            "BASELINE_FAILURE_NOW_FIXED": [e["node_id"] for e in rep["BASELINE_FAILURE_NOW_FIXED"]],
            "ENVIRONMENTAL_MISSING_ARTIFACT": [e["node_id"] for e in rep["ENVIRONMENTAL_MISSING_ARTIFACT"]],
            "KNOWN_BASELINE_FAILURE": [e["node_id"] for e in rep["KNOWN_BASELINE_FAILURE"]] if ns.json else len(rep["KNOWN_BASELINE_FAILURE"])}
    print(json.dumps(card, indent=2 if ns.json else None, default=str))
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
