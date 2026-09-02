"""Execution-closure file hashing algorithms (platform-v2 item 09).

``v1``  canonical text hash (CRLF-normalised bytes) -- the historical algorithm. Every
        frozen manifest written before this module exists is a v1 manifest and keeps
        verifying under v1: sealed studies retain their execution authority unchanged.

``v2``  *semantic* hash for Python sources: the AST with docstrings removed -- and, for
        modules that no closure member star-imports, module-level ``__all__`` removed -- so
        comment-only, docstring-only, formatting-only and (where inert) ``__all__``-only edits do
        not move a study's composite, while any change to executable code (a constant, an
        expression, an import, a default argument, or ``__all__`` of a wildcard-imported module)
        does. Non-Python files keep the v1 canonical text/byte hash.

The algorithm is recorded in ``audit/frozen_execution_manifest.json`` as ``hash_algorithm``;
resolution and verification always use the algorithm the frozen manifest names, and only a
study without a frozen manifest defaults to the current algorithm.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Callable, Dict, Optional

DEFAULT_HASH_ALGORITHM = "v2"


class _Strip(ast.NodeTransformer):
    """Remove docstrings and (unless ``keep_all``) module-level ``__all__`` assignments.

    ``__all__`` IS executable when another closure member does ``from module import *``:
    editing it changes which names that importer binds. The resolver therefore passes
    ``keep_all=True`` for every module that is a wildcard-import target inside the closure
    (see ``wildcard_import_targets``); only modules nobody star-imports get the
    ``__all__``-insensitive hash.
    """

    def __init__(self, keep_all: bool = False) -> None:
        super().__init__()
        self.keep_all = keep_all

    def _strip_docstring(self, node):
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
        return node

    def visit_Module(self, node: ast.Module):
        node = self._strip_docstring(node)
        if not self.keep_all:
            node.body = [
                stmt for stmt in node.body
                if not (isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])))
            ] or [ast.Pass()]
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        self._strip_docstring(node); self.generic_visit(node); return node

    def visit_AsyncFunctionDef(self, node):
        self._strip_docstring(node); self.generic_visit(node); return node

    def visit_ClassDef(self, node):
        self._strip_docstring(node); self.generic_visit(node); return node


def canonical_text_sha256(path: Path) -> str:
    """v1: CRLF-normalised text hash for source-like files, byte hash otherwise."""
    from scripts.resolve_execution_manifest import canonical_file_sha256
    return canonical_file_sha256(Path(path))


def semantic_python_sha256(path: Path, *, keep_all: bool = False) -> Optional[str]:
    """sha256 of the docstring-stripped (and, unless ``keep_all``, ``__all__``-stripped) AST dump; None if the file does not parse."""
    try:
        source = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None
    tree = _Strip(keep_all=keep_all).visit(tree)
    ast.fix_missing_locations(tree)
    dump = ast.dump(tree, include_attributes=False, annotate_fields=True)
    tag = "py-ast-v2-keepall\n" if keep_all else "py-ast-v2\n"
    return hashlib.sha256((tag + dump).encode("utf-8")).hexdigest()


def hash_file_v2(path: Path, *, keep_all: bool = False) -> str:
    p = Path(path)
    if p.suffix.lower() == ".py":
        h = semantic_python_sha256(p, keep_all=keep_all)
        if h is not None:
            return h
    return canonical_text_sha256(p)


def wildcard_import_targets(files, repo_root: Path) -> set:
    """Resolved paths of every module that some file in ``files`` imports with ``import *``.

    Those modules' ``__all__`` is executable for the closure and must stay in their hash.
    """
    from scripts.resolve_execution_manifest import resolve_module_to_path
    targets = set()
    for f in files:
        f = Path(f)
        if f.suffix.lower() != ".py":
            continue
        try:
            tree = ast.parse(f.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and any(a.name == "*" for a in node.names):
                resolved = resolve_module_to_path(node.module, f, Path(repo_root))
                if resolved is not None:
                    targets.add(Path(resolved).resolve())
    return targets


HASH_ALGORITHMS: Dict[str, Callable[[Path], str]] = {"v1": canonical_text_sha256, "v2": hash_file_v2}


def frozen_hash_algorithm(study_dir: Path) -> Optional[str]:
    """The algorithm a study's frozen manifest was written with; None when no manifest exists."""
    import json
    p = Path(study_dir) / "audit" / "frozen_execution_manifest.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(data.get("hash_algorithm") or "v1")


def resolve_hash_algorithm(study_dir: Path, requested: Optional[str] = None) -> str:
    """Requested > frozen manifest's algorithm > current default. Unknown names fail closed."""
    algo = requested or frozen_hash_algorithm(study_dir) or DEFAULT_HASH_ALGORITHM
    if algo not in HASH_ALGORITHMS:
        raise ValueError(f"UNKNOWN_CLOSURE_HASH_ALGORITHM: {algo!r}")
    return algo


__all__ = ["DEFAULT_HASH_ALGORITHM", "HASH_ALGORITHMS", "canonical_text_sha256", "semantic_python_sha256", "hash_file_v2", "wildcard_import_targets",
           "frozen_hash_algorithm", "resolve_hash_algorithm"]
