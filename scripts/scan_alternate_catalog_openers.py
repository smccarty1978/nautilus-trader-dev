"""Static guard for Phase 1 Packet A3: alternate catalog openers under a study tree.

Detects executable study code that opens or references a physical catalog outside the
governed resolver (``backtests/nt_runtime/data_plan.py:resolve_catalog_plan``). Scoped to
``studies/<study>/**/*.py``, not the execution closure -- an unauthorized bypass path is
by definition outside the governed closure, so closure membership cannot detect it
(``implementation/run_collect.py`` was never in it).

Two narrow, deterministic AST rules -- not a general security scanner:

1. a direct call to ``ParquetDataCatalog(...)``                     -> DIRECT_CATALOG_CONSTRUCTION
2. a string literal containing ``data/catalog/`` or ``data\\catalog\\``,
   outside a docstring position                                     -> HARDCODED_CATALOG_PATH_LITERAL

Both are executable-code findings. Type annotations, comments, and docstrings are
structurally exempt: a type annotation is an ``ast.Name``/``ast.Attribute``, never an
``ast.Call``; comments never appear in the AST at all; and docstrings are excluded
explicitly by position (the first statement of a module/class/function body).
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

HARDCODED_PATH_MARKERS = ("data/catalog/", "data\\catalog\\")


@dataclass(frozen=True)
class AlternateCatalogOpenerFinding:
    file: Path
    line: int
    rule: str
    detail: str


def _is_docstring_expr(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _docstring_node_ids(tree: ast.Module) -> Set[int]:
    """Collects id() of every string-constant AST node that is a real docstring."""
    docstring_ids: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and _is_docstring_expr(body[0]):
                docstring_ids.add(id(body[0].value))
    return docstring_ids


def scan_source_for_alternate_catalog_openers(
    source: str, file_path: Path
) -> List[AlternateCatalogOpenerFinding]:
    """Scans already-read source text. Split out from file I/O so tests can pass
    synthetic source strings directly without touching disk.
    """
    findings: List[AlternateCatalogOpenerFinding] = []
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return findings

    docstring_ids = _docstring_node_ids(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            callee_name = None
            if isinstance(func, ast.Name):
                callee_name = func.id
            elif isinstance(func, ast.Attribute):
                callee_name = func.attr
            if callee_name == "ParquetDataCatalog":
                findings.append(AlternateCatalogOpenerFinding(
                    file=file_path,
                    line=node.lineno,
                    rule="DIRECT_CATALOG_CONSTRUCTION",
                    detail="ParquetDataCatalog(...) constructed directly, outside resolve_catalog_plan",
                ))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue
            if any(marker in node.value for marker in HARDCODED_PATH_MARKERS):
                findings.append(AlternateCatalogOpenerFinding(
                    file=file_path,
                    line=node.lineno,
                    rule="HARDCODED_CATALOG_PATH_LITERAL",
                    detail=f"string literal references a hardcoded catalog path: {node.value!r}",
                ))

    return findings


def scan_file_for_alternate_catalog_openers(path: Path) -> List[AlternateCatalogOpenerFinding]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return scan_source_for_alternate_catalog_openers(source, path)


def scan_study_for_alternate_catalog_openers(study_dir: Path) -> List[AlternateCatalogOpenerFinding]:
    """Scans studies/<study>/**/*.py -- the full study tree, not the execution closure."""
    findings: List[AlternateCatalogOpenerFinding] = []
    for py_file in sorted(study_dir.rglob("*.py")):
        findings.extend(scan_file_for_alternate_catalog_openers(py_file))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan studies/<study>/**/*.py for alternate (ungoverned) catalog openers."
    )
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    findings = scan_study_for_alternate_catalog_openers(study_dir)
    if findings:
        print(f"ALTERNATE_CATALOG_OPENER_VIOLATIONS: {len(findings)}")
        for f in findings:
            print(f"  {f.file}:{f.line} [{f.rule}] {f.detail}")
        return 1
    print("ALTERNATE_CATALOG_OPENER_VIOLATIONS: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
