"""Execution-closure hashing v2 (platform-v2 item 09): semantic Python hash, per-manifest algorithm."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_workflow import closure_hash as ch

CODE = '''"""Module docstring."""
import math

__all__ = ["f"]

CONST = 1.5


def f(x, k=2):
    """Doc."""
    # comment
    return math.sqrt(x) * k + CONST


class C:
    """Class doc."""
    def m(self):
        return f(4)
'''


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name; p.write_text(text, encoding="utf-8"); return p


def test_docstring_comment_all_and_formatting_edits_do_not_move_v2_hash(tmp_path: Path):
    base = ch.hash_file_v2(_write(tmp_path, "a.py", CODE))
    variants = {
        "docstrings": CODE.replace('"""Module docstring."""', '"""Rewritten module docstring."""').replace('"""Doc."""', '"""Other."""').replace('"""Class doc."""', '"""Changed."""'),
        "comment": CODE.replace("# comment", "# a completely different comment"),
        "__all__": CODE.replace('__all__ = ["f"]', '__all__ = ["f", "C", "CONST"]'),
        "no_all": CODE.replace('__all__ = ["f"]\n', ""),
        "formatting": CODE.replace("return math.sqrt(x) * k + CONST", "return (math.sqrt(x) * k) + CONST").replace("\n\n\n", "\n\n"),
        "crlf": CODE.replace("\n", "\r\n"),
    }
    for name, text in variants.items():
        assert ch.hash_file_v2(_write(tmp_path, f"{name}.py", text)) == base, name


def test_executable_changes_move_v2_hash(tmp_path: Path):
    base = ch.hash_file_v2(_write(tmp_path, "a.py", CODE))
    variants = {
        "constant": CODE.replace("CONST = 1.5", "CONST = 1.6"),
        "default_arg": CODE.replace("def f(x, k=2):", "def f(x, k=3):"),
        "expression": CODE.replace("* k + CONST", "* k - CONST"),
        "import": CODE.replace("import math", "import math, os"),
        "new_function": CODE + "\n\ndef g():\n    return 1\n",
    }
    for name, text in variants.items():
        assert ch.hash_file_v2(_write(tmp_path, f"{name}.py", text)) != base, name


def test_v1_still_moves_on_docstring_edit_and_non_python_uses_text_hash(tmp_path: Path):
    a = _write(tmp_path, "a.py", CODE); b = _write(tmp_path, "b.py", CODE.replace('"""Doc."""', '"""Other."""'))
    assert ch.canonical_text_sha256(a) != ch.canonical_text_sha256(b)
    j1, j2, j3 = tmp_path / "x.json", tmp_path / "y.json", tmp_path / "z.json"
    j1.write_bytes(b'{"a": 1}\n'); j2.write_bytes(b'{"a": 1}\r\n'); j3.write_bytes(b'{"a": 2}\n')  # bytes: no platform newline translation
    assert ch.hash_file_v2(j1) == ch.hash_file_v2(j2) != ch.hash_file_v2(j3)


def test_unparseable_python_falls_back_to_text_hash(tmp_path: Path):
    p = _write(tmp_path, "broken.py", "def (:\n")
    assert ch.semantic_python_sha256(p) is None and ch.hash_file_v2(p) == ch.canonical_text_sha256(p)


def test_frozen_manifest_algorithm_is_authoritative(tmp_path: Path):
    study = tmp_path / "s"; (study / "audit").mkdir(parents=True)
    assert ch.resolve_hash_algorithm(study) == ch.DEFAULT_HASH_ALGORITHM  # no manifest -> current default
    (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps({"frozen_execution_composite_sha256": "x"}), encoding="utf-8")
    assert ch.resolve_hash_algorithm(study) == "v1"  # legacy manifest without the field
    (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps({"frozen_execution_composite_sha256": "x", "hash_algorithm": "v2"}), encoding="utf-8")
    assert ch.resolve_hash_algorithm(study) == "v2"
    assert ch.resolve_hash_algorithm(study, "v1") == "v1"  # explicit request wins
    with pytest.raises(ValueError):
        ch.resolve_hash_algorithm(study, "v9")


def test_resolver_records_algorithm_and_sealed_study_keeps_v1():
    """The sealed regime-transition study on this branch was frozen under v1: its manifest names no
    algorithm, so the resolver must keep hashing it with v1, and a v2 resolution must differ only
    by algorithm, never by closure membership."""
    from scripts.resolve_execution_manifest import resolve_execution_manifest
    repo = Path(__file__).resolve().parents[2]
    study = repo / "studies" / "regime_transition_target_before_stop_v1"
    if not (study / "compiled_study.json").is_file():
        pytest.skip("study not present")
    c1, h1, m1 = resolve_execution_manifest(study, repo)
    c2, h2, m2 = resolve_execution_manifest(study, repo, hash_algorithm="v2")
    assert m1["hash_algorithm"] == "v1" and m2["hash_algorithm"] == "v2"
    assert set(h1) == set(h2)  # same closure membership
    assert c1 != c2  # different algorithm -> different composite, by design
    c1b, _, _ = resolve_execution_manifest(study, repo)
    assert c1b == c1  # deterministic


def test_all_edit_moves_hash_for_wildcard_imported_modules_only(tmp_path: Path):
    """Audit pass-01 CRITICAL: __all__ decides what a star-importer binds, so it stays in the
    hash of any module that is wildcard-imported inside the closure."""
    mod = _write(tmp_path, "mod.py", CODE)
    mod2 = _write(tmp_path, "mod2.py", CODE.replace('__all__ = ["f"]', '__all__ = ["f", "C"]'))
    assert ch.hash_file_v2(mod) == ch.hash_file_v2(mod2)                       # nobody star-imports it
    assert ch.hash_file_v2(mod, keep_all=True) != ch.hash_file_v2(mod2, keep_all=True)  # star-imported: __all__ binds
    importer = _write(tmp_path, "user.py", "from mod import *\n")
    (tmp_path / "__init__.py").write_text("")
    targets = ch.wildcard_import_targets([importer, mod], tmp_path)
    assert mod.resolve() in targets and importer.resolve() not in targets
