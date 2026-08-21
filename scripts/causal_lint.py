"""Deterministic pre-audit lint for known-recurring causal defects.

Runs BEFORE any auditor subagent. Every pattern here corresponds to a defect
class that has already been found by a paid LLM audit pass at least once in this
repository's history -- catching them with grep is free and instant.

Usage
-----
    python scripts/causal_lint.py --study studies/<name>
    python scripts/causal_lint.py --path features/ indicators/
    python scripts/causal_lint.py --study studies/<name> --json audit/lint.json

Exit codes
----------
    0  clean (no CRITICAL, no WARNING)
    1  findings present
    2  invocation error

Suppression
-----------
Add an inline pragma with a mandatory reason on the offending line:

    df["x"] = raw.shift(-1)  # causal-lint: ignore[B4] label column, not a feature

A pragma without a reason is itself reported.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SKIP_DIR_PARTS = {
    "__pycache__", ".git", ".mypy_cache", ".pytest_cache",
    "_work", "_snapshots", "archive", "node_modules", ".venv", "venv",
}

PRAGMA_RE = re.compile(r"#\s*causal-lint:\s*ignore\[([A-Z]\d{1,2}(?:/[A-Z]\d{1,2})*)\]\s*(.*)$")

# This tool's own source and tests necessarily contain every pattern it detects
# (inside rule regexes and message strings), so they would self-report.
SELF_EXCLUDE = {
    Path(__file__).resolve(),
    (REPO_ROOT / "scripts" / "tests" / "test_causal_lint.py").resolve(),
}


@dataclass
class Rule:
    rule_id: str
    severity: str
    pattern: str
    message: str
    # Optional second pattern that must ALSO match the line for a hit.
    requires: str | None = None
    # Optional pattern that suppresses the hit when present on the line.
    unless: str | None = None


RULES: list[Rule] = [
    # --- H4: fill priced at the trigger level rather than a real fill -------
    Rule(
        rule_id="H4",
        severity="CRITICAL",
        pattern=r"(exit_pnl|pnl|gross|net)\s*=\s*\(\s*(sl_px|stop_px|pt_px|target_px|trigger_px|stop_price)\b",
        message=(
            "PnL computed directly from a stop/target LEVEL. Fill price must be "
            "the next-bar open or the NT-reported fill, not the trigger price. "
            "Most-repeated finding in repo history (8 prior occurrences)."
        ),
    ),
    Rule(
        rule_id="H4",
        severity="WARNING",
        pattern=r"\bfill_px\s*=\s*(self\.)?_?(last_)?(1s_)?close\b",
        message=(
            "Fill price taken from a bar close (the scoring snap price). Correct "
            "for scoring, not for execution -- reconcile against NT's actual fill."
        ),
    ),
    # --- H1: stop/target detection on close instead of high/low ------------
    Rule(
        rule_id="H1",
        severity="WARNING",
        pattern=r"\b(close|c)\s*(<=|>=|<|>)\s*(sl_px|stop_px|pt_px|target_px|stop_price|target_price)\b",
        message="SL/PT detection compares against close; must use bar HIGH/LOW.",
    ),
    # --- A1 / F1: session gate on open time --------------------------------
    # Attribute access -- this genuinely reads the bar's OPEN time.
    Rule(
        rule_id="A1/F1",
        severity="CRITICAL",
        pattern=r"[\w\]\)]\.ts_event\b",
        # (?:\b|_) so `in_rth` / `is_rth` match while `method` / `together` do not.
        requires=r"(?:\b|_)(rth|eth|session|in_window|minute_of_day|time_of_day|to_ct|is_open|market_open|market_close)(?:\b|_)",
        message=(
            "Session/RTH classification reads .ts_event (bar OPEN time). "
            "Must use ts_init (bar CLOSE time). Found historically at "
            "studies/_shared_exit_mgmt/base_strategy.py:232."
        ),
    ),
    # Bare identifier -- usually a parameter NAMED ts_event that is actually
    # passed ts_init. Not a defect by itself, but a prior audit raised it as
    # "[A1 naming] Aggregator parameter named ts_event but receives bar.ts_init".
    Rule(
        rule_id="A1-naming",
        severity="WARNING",
        pattern=r"(?<![.\w])ts_event\b",
        requires=r"(?:\b|_)(rth|eth|session|in_window|minute_of_day|time_of_day|to_ct|is_open|market_open|market_close)(?:\b|_)",
        message=(
            "Identifier named ts_event in session-handling code. If it actually "
            "receives ts_init, rename it -- the mismatch has misled auditors before."
        ),
    ),
    # --- B1: centered rolling ----------------------------------------------
    Rule(
        rule_id="B1",
        severity="CRITICAL",
        pattern=r"center\s*=\s*True",
        message="Centered rolling window reads future bars.",
    ),
    # --- B4: negative shift in a feature path ------------------------------
    Rule(
        rule_id="B4",
        severity="CRITICAL",
        pattern=r"\.shift\(\s*-\s*\d+",
        message=(
            "Negative shift pulls future values backward. Legal ONLY in a label "
            "column -- suppress with a pragma naming the label."
        ),
    ),
    # --- B5: backfill -------------------------------------------------------
    Rule(
        rule_id="B5",
        severity="CRITICAL",
        pattern=r"\.bfill\(",
        message="Backward fill writes future values into past timestamps.",
    ),
    # --- B7: scaler fit on the full dataset --------------------------------
    Rule(
        rule_id="B7",
        severity="WARNING",
        pattern=r"\.fit_transform\(",
        requires=r"\b(scaler|imputer|encoder|normali[sz]er|StandardScaler|MinMaxScaler|RobustScaler)\b",
        message=(
            "Scaler/imputer fit_transform -- confirm it is fit on TRAIN rows only, "
            "not the full dataset."
        ),
    ),
    # --- F4: fixed UTC offset for a session window -------------------------
    Rule(
        rule_id="F4",
        severity="WARNING",
        pattern=r"(timedelta\(hours\s*=\s*-?\d+\)|['\"]UTC[+-]\d|tz\s*=\s*['\"]Etc/GMT)",
        requires=r"\b(rth|eth|session|open|close|08:?30|15:?00|15:?15|9:?30|16:?00)\b",
        message=(
            "Session boundary derived from a fixed UTC offset breaks across DST. "
            "Use a named zone (America/Chicago)."
        ),
    ),
    # --- G1: non volume-continuous contract data ---------------------------
    Rule(
        rule_id="G1",
        severity="WARNING",
        pattern=r"['\"][A-Z]{2,3}\.[cn]\.\d",
        message=(
            "Non volume-continuous contract symbol. HARD RULE: only *.v.0 data. "
            "See memory: databento_download_rule."
        ),
    ),
]


@dataclass
class Finding:
    rule_id: str
    severity: str
    file: str
    line: int
    text: str
    message: str


@dataclass
class Suppression:
    rule: str
    file: str
    line: int
    reason: str


@dataclass
class ScanOutcome:
    findings: list[Finding]
    suppressions: list[Suppression]


def iter_python_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            out.append(root)
            continue
        for p in sorted(root.rglob("*.py")):
            if SKIP_DIR_PARTS.intersection(p.parts):
                continue
            if p.resolve() in SELF_EXCLUDE:
                continue
            out.append(p)
    return out


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _blank_tokens(raw: str) -> tuple[list[str], list[tokenize.TokenInfo]]:
    """Return executable-looking lines and tokens without strings/comments.

    `tokenize` deliberately removes docstrings and ordinary string literals, so
    examples in documentation or regex definitions cannot trigger lexical rules.
    Newlines and columns are retained for accurate finding locations.
    """
    lines = raw.splitlines(keepends=True)
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    for token in tokens:
        if token.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (start_line, start_col), (end_line, end_col) = token.start, token.end
        for line_no in range(start_line, end_line + 1):
            index = line_no - 1
            if index >= len(lines):
                continue
            left = start_col if line_no == start_line else 0
            right = end_col if line_no == end_line else len(lines[index])
            lines[index] = lines[index][:left] + " " * max(0, right - left) + lines[index][right:]
    return [line.rstrip("\r\n") for line in lines], tokens


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _expr_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_expr_name(node.value)}.{node.attr}"
    return ""


def _literal(node: ast.expr | None):
    return node.value if isinstance(node, ast.Constant) else None


def _rule_aliases(rule_id: str) -> set[str]:
    """Explicitly supported suppression names for a rule (no substring match)."""
    return {rule_id, *rule_id.split("/")}


KNOWN_SUPPRESSION_IDS = set().union(*(_rule_aliases(rule.rule_id) for rule in RULES), {
    "A2", "A5/G3", "B6", "C3", "G3",
})


def _is_suppressed(rule_id: str, line: int, suppressions: dict[int, set[str]]) -> bool:
    return bool(_rule_aliases(rule_id) & suppressions.get(line, set()))


def _append_finding(findings: list[Finding], seen: set[tuple[str, int]], *, rule_id: str,
                    severity: str, rel: str, line: int, text: str, message: str,
                    suppressions: dict[int, set[str]]) -> None:
    if _is_suppressed(rule_id, line, suppressions):
        return
    key = (rule_id, line)
    if key not in seen:
        findings.append(Finding(rule_id, severity, rel, line, text.strip()[:200], message))
        seen.add(key)


def _ast_findings(tree: ast.AST, code_lines: list[str], rel: str,
                  suppressions: dict[int, set[str]], findings: list[Finding],
                  seen: set[tuple[str, int]]) -> None:
    """Structural checks for calls whose arguments may be multiline."""
    assignments: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is not None:
                for target in targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = value

    def add(node: ast.AST, rule_id: str, severity: str, message: str) -> None:
        line = node.lineno
        text = code_lines[line - 1] if line <= len(code_lines) else ""
        _append_finding(findings, seen, rule_id=rule_id, severity=severity, rel=rel,
                        line=line, text=text, message=message, suppressions=suppressions)

    def cv_is_temporal(value: ast.expr | None) -> bool:
        if isinstance(value, ast.Name):
            value = assignments.get(value.id)
        return isinstance(value, ast.Call) and _call_name(value.func) == "TimeSeriesSplit"

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        keywords = {item.arg: item.value for item in node.keywords if item.arg}

        if name == "resample":
            closed, label = _literal(keywords.get("closed")), _literal(keywords.get("label"))
            if closed == "right":
                add(node, "A5/G3", "CRITICAL", "resample(closed='right') on open-stamped intrabar data injects look-ahead; use closed='left' unless an explicit close-time transformation is documented and tested.")
            if closed is None or label is None:
                add(node, "G3", "WARNING", "resample() must state explicit label= and closed= arguments.")

        if name == "merge_asof":
            direction = _literal(keywords.get("direction"))
            if direction is None:
                add(node, "B6", "CRITICAL", "merge_asof() without explicit direction=. State direction='backward' for causal alignment.")
            elif direction in {"forward", "nearest"}:
                add(node, "B6", "CRITICAL", "merge_asof direction='forward'/'nearest' aligns onto future rows.")

        if name == "fillna" and _literal(keywords.get("method")) in {"bfill", "backfill"}:
            add(node, "B5", "CRITICAL", "Backward fill writes future values into past timestamps.")

        if name == "train_test_split" and _literal(keywords.get("shuffle")) is not False:
            add(node, "C3", "CRITICAL", "train_test_split() must explicitly set shuffle=False for temporal data.")

        if name in {"KFold", "StratifiedKFold", "ShuffleSplit", "StratifiedShuffleSplit"}:
            add(node, "C3", "CRITICAL", "Random-fold CV on time-series data leaks across the time axis; use TimeSeriesSplit.")

        if name in {"cross_val_score", "cross_validate"}:
            cv = keywords.get("cv")
            if isinstance(cv, ast.Constant) and isinstance(cv.value, int):
                add(node, "C3", "CRITICAL", "cross-validation with an integer cv= uses random folds; provide TimeSeriesSplit explicitly.")
            elif isinstance(cv, ast.Call) and _call_name(cv.func) in {"KFold", "StratifiedKFold", "ShuffleSplit", "StratifiedShuffleSplit"}:
                add(node, "C3", "CRITICAL", "cross-validation uses a random splitter; use TimeSeriesSplit.")
            elif cv is not None and not cv_is_temporal(cv) and isinstance(cv, ast.Name) and cv.id in assignments:
                add(node, "C3", "CRITICAL", "cross-validation splitter is not TimeSeriesSplit.")

        # A2 applies only where the receiver itself identifies an aggregated
        # timeframe; a generic `wrangler.process(...)` cannot be inferred safely.
        if name == "process":
            receiver = _expr_name(node.func.value) if isinstance(node.func, ast.Attribute) else ""
            if re.search(r"(?:^|[_\.])(1m|3m|5m|minute)(?:$|[_\.])", receiver, re.IGNORECASE):
                delta = _literal(keywords.get("ts_init_delta"))
                if delta == 0:
                    add(node, "A2", "CRITICAL", "Aggregated Databento bars require a positive canonical ts_init_delta so NT processes them at close time.")
                elif delta is None:
                    add(node, "A2", "WARNING", "Aggregated-bar wrangling should state the canonical ts_init_delta explicitly.")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Constant):
            continue
        value = node.value.value
        if isinstance(value, str) and re.search(r"^[A-Z]{2,3}\.[cn]\.\d", value):
            add(node, "G1", "WARNING", "Non volume-continuous contract symbol. HARD RULE: only *.v.0 data.")


def scan_file_details(path: Path) -> ScanOutcome:
    findings: list[Finding] = []
    suppressions_inventory: list[Suppression] = []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # unreadable file is a finding, not a crash
        return ScanOutcome([Finding("LINT", "WARNING", str(path), 0, "", f"unreadable: {exc}")], [])

    rel = _relative(path)
    try:
        code_lines, tokens = _blank_tokens(source)
    except (tokenize.TokenError, IndentationError) as exc:
        return ScanOutcome([Finding("LINT", "CRITICAL", rel, 0, "", f"cannot tokenize Python source: {exc}")], [])

    suppressions: dict[int, set[str]] = {}
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        pragma = PRAGMA_RE.search(token.string)
        suppressed = None
        if pragma:
            suppressed = pragma.group(1)
            line = token.start[0]
            reason = pragma.group(2).strip()
            if suppressed not in KNOWN_SUPPRESSION_IDS:
                findings.append(Finding("LINT", "CRITICAL", rel, line, token.string.strip(), f"unknown causal-lint suppression rule {suppressed}"))
                continue
            if not reason:
                findings.append(Finding(
                    "LINT", "WARNING", rel, line, token.string.strip(),
                    "causal-lint pragma has no reason; a bare suppression is not allowed.",
                ))
            else:
                suppressions.setdefault(line, set()).add(suppressed)
                suppressions_inventory.append(Suppression(suppressed, rel, line, reason))

    seen = {(finding.rule_id, finding.line) for finding in findings}
    for lineno, code in enumerate(code_lines, start=1):
        if not code.strip():
            continue

        for rule in RULES:
            if not re.search(rule.pattern, code, re.IGNORECASE):
                continue
            if rule.requires and not re.search(rule.requires, code, re.IGNORECASE):
                continue
            if rule.unless and re.search(rule.unless, code, re.IGNORECASE):
                continue
            _append_finding(findings, seen, rule_id=rule.rule_id, severity=rule.severity,
                            rel=rel, line=lineno, text=code, message=rule.message,
                            suppressions=suppressions)

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        findings.append(Finding("LINT", "CRITICAL", rel, exc.lineno or 0, "", f"cannot parse Python source: {exc.msg}"))
    else:
        _ast_findings(tree, code_lines, rel, suppressions, findings, seen)
    return ScanOutcome(findings, suppressions_inventory)


def scan_file(path: Path) -> list[Finding]:
    """Compatibility wrapper used by tests and other lightweight callers."""
    return scan_file_details(path).findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", type=str, help="Study folder to lint")
    ap.add_argument("--path", type=str, nargs="*", default=[],
                    help="Additional files/dirs to lint")
    ap.add_argument("--json", type=str, help="Write findings to this JSON path")
    ap.add_argument("--warn-ok", action="store_true",
                    help="Exit 0 when only WARNING-level findings are present")
    args = ap.parse_args()

    roots: list[Path] = []
    invocation_errors: list[str] = []
    explicit_files: list[Path] = []
    expected_count = 0

    if args.study:
        sd = Path(args.study)
        if not sd.exists():
            invocation_errors.append(f"study path does not exist: {sd}")
        elif (sd / "study.yaml").exists():
            try:
                from scripts.resolve_execution_manifest import resolve_execution_manifest
                _, file_hashes, _ = resolve_execution_manifest(sd, REPO_ROOT)
                for k in sorted(file_hashes.keys()):
                    if k.startswith("study:"):
                        rel_p = k[len("study:"):]
                        fp = sd / rel_p
                    elif k.startswith("repo:"):
                        rel_p = k[len("repo:"):]
                        fp = REPO_ROOT / rel_p
                    else:
                        fp = REPO_ROOT / k
                    if fp.suffix == ".py" and fp.exists() and fp not in SELF_EXCLUDE:
                        explicit_files.append(fp)
                expected_count = len(explicit_files)
            except Exception as e:
                invocation_errors.append(f"failed to resolve execution manifest for study {sd}: {e}")
                roots.append(sd)
        else:
            roots.append(sd)

    for raw_path in args.path:
        path = Path(raw_path)
        if not path.exists():
            invocation_errors.append(f"path does not exist: {path}")
        else:
            roots.append(path)

    if explicit_files:
        files = explicit_files
        if roots:
            files.extend([f for f in iter_python_files(roots) if f not in files])
    elif roots:
        files = iter_python_files(roots)
    else:
        files = []

    if not files and not invocation_errors:
        invocation_errors.append("no eligible Python files found under requested roots or execution manifest")

    coverage_complete = True
    if expected_count > 0 and len(files) < expected_count:
        coverage_complete = False
        invocation_errors.append(
            f"COVERAGE_INCOMPLETE: expected {expected_count} execution Python files, scanned only {len(files)}"
        )

    findings: list[Finding] = []
    suppressions: list[Suppression] = []
    for f in files:
        outcome = scan_file_details(f)
        findings.extend(outcome.findings)
        suppressions.extend(outcome.suppressions)

    n_crit = sum(1 for f in findings if f.severity == "CRITICAL")
    n_warn = sum(1 for f in findings if f.severity == "WARNING")
    invocation_valid = not invocation_errors and coverage_complete

    cov_pct = 100.0 if (expected_count > 0 and len(files) >= expected_count) else (
        (len(files) / expected_count * 100.0) if expected_count > 0 else 100.0
    )

    payload = {
        "tool": "causal_lint",
        "version": 2,
        "roots": [str(r) for r in roots] if roots else ["<execution_manifest>"],
        "files_expected": expected_count if expected_count > 0 else len(files),
        "files_scanned": len(files),
        "coverage_pct": cov_pct,
        "invocation_valid": invocation_valid,
        "invocation_errors": invocation_errors,
        "blocking_clean": invocation_valid and n_crit == 0 and n_warn == 0,
        "critical": n_crit,
        "warning": n_warn,
        "clean": invocation_valid and n_crit == 0 and n_warn == 0,
        "findings": [asdict(f) for f in findings],
        "suppressions": [asdict(item) for item in suppressions],
    }

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"causal_lint: {len(files)} files scanned (expected: {payload['files_expected']}, coverage: {cov_pct:.1f}%) -> "
          f"{n_crit} CRITICAL, {n_warn} WARNING")
    for error in invocation_errors:
        print(f"  [ERROR] {error}", file=sys.stderr)
    for f in findings:
        print(f"  [{f.severity[:4]}] {f.rule_id:<7} {f.file}:{f.line}")
        print(f"        {f.text}")
        print(f"        -> {f.message}")

    if not invocation_valid:
        return 2
    if n_crit:
        return 1
    if n_warn and not args.warn_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
