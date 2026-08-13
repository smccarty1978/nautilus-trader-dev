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
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIR_PARTS = {
    "__pycache__", ".git", ".mypy_cache", ".pytest_cache",
    "_work", "_snapshots", "archive", "node_modules", ".venv", "venv",
}

PRAGMA_RE = re.compile(r"#\s*causal-lint:\s*ignore\[([A-H]\d{1,2})\]\s*(.*)$")

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
    # Optional pattern that suppresses the hit when present ANYWHERE in the
    # file. Use when the disambiguating context legitimately lives on another
    # line (e.g. a TimeSeriesSplit assigned above the cross_val_score call).
    file_unless: str | None = None


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
    # --- A5 / G3: resample boundary injects look-ahead ---------------------
    Rule(
        rule_id="A5/G3",
        severity="CRITICAL",
        pattern=r"closed\s*=\s*['\"]right['\"]",
        requires=r"\bresample\b",
        message=(
            "resample(closed='right') on intrabar data injects look-ahead -- the "
            "bar stamped at t includes the tick at t. Use closed='left'. "
            "See memory: catalog_1m_resample_bug."
        ),
    ),
    Rule(
        rule_id="G3",
        severity="WARNING",
        pattern=r"\.resample\(",
        unless=r"\b(label|closed)\s*=",
        message="resample() without explicit label=/closed= arguments.",
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
        pattern=r"(\.bfill\(|method\s*=\s*['\"]bfill['\"]|method\s*=\s*['\"]backfill['\"]|\.fillna\([^)]*bfill)",
        message="Backward fill writes future values into past timestamps.",
    ),
    # --- B6: merge_asof without an explicit direction ----------------------
    Rule(
        rule_id="B6",
        severity="CRITICAL",
        pattern=r"merge_asof\(",
        unless=r"direction\s*=",
        message=(
            "merge_asof() without explicit direction=. Default is 'backward', but "
            "relying on the default has produced boundary bugs -- state it."
        ),
    ),
    Rule(
        rule_id="B6",
        severity="CRITICAL",
        pattern=r"direction\s*=\s*['\"](forward|nearest)['\"]",
        message="merge_asof direction='forward'/'nearest' aligns onto future rows.",
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
    # --- C3: random split on time-series -----------------------------------
    Rule(
        rule_id="C3",
        severity="CRITICAL",
        pattern=r"train_test_split\(",
        unless=r"shuffle\s*=\s*False",
        message="train_test_split() shuffles by default; splits must be temporal.",
    ),
    Rule(
        rule_id="C3",
        severity="CRITICAL",
        pattern=r"\b(KFold|StratifiedKFold|cross_val_score|cross_validate)\b",
        file_unless=r"TimeSeriesSplit",
        message="Random-fold CV on time-series data leaks across the time axis.",
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


def strip_code(line: str) -> str:
    """Remove a trailing comment so comments/docstrings don't trigger rules."""
    out, in_s, quote = [], False, ""
    i = 0
    while i < len(line):
        ch = line[i]
        if in_s:
            if ch == "\\":
                out.append(ch)
                i += 1
                if i < len(line):
                    out.append(line[i])
                i += 1
                continue
            if ch == quote:
                in_s = False
            out.append(ch)
        elif ch in "\"'":
            in_s, quote = True, ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:  # unreadable file is a finding, not a crash
        return [Finding("LINT", "WARNING", str(path), 0, "", f"unreadable: {exc}")]

    try:
        rel = str(path.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(path)

    whole = "\n".join(raw)
    file_suppressed = {
        id(rule) for rule in RULES
        if rule.file_unless and re.search(rule.file_unless, whole, re.IGNORECASE)
    }

    for lineno, full_line in enumerate(raw, start=1):
        pragma = PRAGMA_RE.search(full_line)
        suppressed = None
        if pragma:
            suppressed = pragma.group(1)
            if not pragma.group(2).strip():
                findings.append(Finding(
                    "LINT", "WARNING", rel, lineno, full_line.strip(),
                    "causal-lint pragma has no reason; a bare suppression is not allowed.",
                ))

        code = strip_code(full_line)
        if not code.strip():
            continue

        for rule in RULES:
            if suppressed and suppressed in rule.rule_id:
                continue
            if id(rule) in file_suppressed:
                continue
            if not re.search(rule.pattern, code, re.IGNORECASE):
                continue
            if rule.requires and not re.search(rule.requires, code, re.IGNORECASE):
                continue
            if rule.unless and re.search(rule.unless, code, re.IGNORECASE):
                continue
            findings.append(Finding(
                rule.rule_id, rule.severity, rel, lineno,
                code.strip()[:200], rule.message,
            ))
    return findings


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
    if args.study:
        sd = Path(args.study)
        if not sd.exists():
            print(f"error: study path does not exist: {sd}", file=sys.stderr)
            return 2
        roots.append(sd)
    roots.extend(Path(p) for p in args.path)

    if not roots:
        print("error: supply --study and/or --path", file=sys.stderr)
        return 2

    files = iter_python_files(roots)
    findings: list[Finding] = []
    for f in files:
        findings.extend(scan_file(f))

    n_crit = sum(1 for f in findings if f.severity == "CRITICAL")
    n_warn = sum(1 for f in findings if f.severity == "WARNING")

    payload = {
        "tool": "causal_lint",
        "version": 1,
        "roots": [str(r) for r in roots],
        "files_scanned": len(files),
        "critical": n_crit,
        "warning": n_warn,
        "clean": n_crit == 0 and n_warn == 0,
        "findings": [asdict(f) for f in findings],
    }

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"causal_lint: {len(files)} files scanned -> "
          f"{n_crit} CRITICAL, {n_warn} WARNING")
    for f in findings:
        print(f"  [{f.severity[:4]}] {f.rule_id:<7} {f.file}:{f.line}")
        print(f"        {f.text}")
        print(f"        -> {f.message}")

    if n_crit:
        return 1
    if n_warn and not args.warn_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
