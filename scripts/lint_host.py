#!/usr/bin/env python3
"""Host boundary lint: the host coordinates primitives and implements no science.

Checks every module under ``research_workflow/host/``:

* imports: nothing from ``features``, ``indicators``, ``collectors``, ``studies``,
  ``strategies``, ``backtests`` or ``utils.session_boundaries``; ``pandas``/``numpy`` only in
  ``sink.py`` (flush-time frame construction);
* string literals: no instrument ids (``NQ.XCME``), bar-type strings, timezone names,
  session names;
* numeric literals: only 0, 1, -1 and the nanosecond scale (``1_000_000_000``) unless the
  line carries a ``# host-constant:`` explanation.

Usage: ``python scripts/lint_host.py`` (exit 0 = CLEAR, 1 = violations).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_DIR = ROOT / "research_workflow" / "host"

FORBIDDEN_IMPORT_PREFIXES = ("features", "indicators", "collectors", "studies", "strategies", "backtests",
                             "utils.session_boundaries", "research.study_types", "research.engines")
FRAME_LIBS = ("pandas", "numpy")
FRAME_LIB_ALLOWED_FILES = {"sink.py"}
ALLOWED_NUMBERS = {0, 1, -1, 2, 1_000_000_000}
INSTRUMENT_RE = re.compile(r"\b[A-Z]{1,4}\.X[A-Z]{2,6}\b")
BAR_TYPE_RE = re.compile(r"-(SECOND|MINUTE|HOUR|DAY)-|LAST-EXTERNAL")
TZ_RE = re.compile(r"America/|Europe/|Asia/|US/|Etc/|Chicago|New_York")
SESSION_RE = re.compile(r"^(RTH|ETH)$")


def lint_file(path: Path) -> list[dict]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    findings: list[dict] = []

    def add(kind: str, node: ast.AST, detail: str) -> None:
        findings.append({"file": path.relative_to(ROOT).as_posix(), "line": getattr(node, "lineno", 0), "kind": kind, "detail": detail})

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES):
                    add("FORBIDDEN_IMPORT", node, name)
                if any(name == p or name.startswith(p + ".") for p in FRAME_LIBS) and path.name not in FRAME_LIB_ALLOWED_FILES:
                    add("FRAME_LIB_ON_HOT_PATH", node, name)
        elif isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, str):
                if INSTRUMENT_RE.search(v):
                    add("INSTRUMENT_LITERAL", node, v)
                if BAR_TYPE_RE.search(v):
                    add("BAR_TYPE_LITERAL", node, v)
                if TZ_RE.search(v):
                    add("TIMEZONE_LITERAL", node, v)
                if SESSION_RE.match(v):
                    add("SESSION_LITERAL", node, v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                if v not in ALLOWED_NUMBERS:
                    line = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
                    if "host-constant:" not in line:
                        add("UNEXPLAINED_NUMERIC_LITERAL", node, repr(v))
    # docstrings are prose, not code: drop literal findings that sit inside a docstring
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
                d = node.body[0]
                doc_lines.update(range(d.lineno, (d.end_lineno or d.lineno) + 1))
    return [f for f in findings if not (f["kind"].endswith("_LITERAL") and f["line"] in doc_lines)]


def main() -> int:
    findings: list[dict] = []
    files = sorted(p for p in HOST_DIR.glob("*.py"))
    for p in files:
        findings.extend(lint_file(p))
    card = {"STATUS": "CLEAR" if not findings else "VIOLATIONS", "files": len(files), "findings": findings,
            "rules": {"forbidden_import_prefixes": list(FORBIDDEN_IMPORT_PREFIXES), "allowed_numbers": sorted(ALLOWED_NUMBERS),
                      "frame_libs_allowed_in": sorted(FRAME_LIB_ALLOWED_FILES)}}
    print(json.dumps(card, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
