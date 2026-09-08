"""Tiered merge gate -- mechanical classifier + derived test surface + historical replay (design proof tool).

Usage:
  python tier_replay.py map                       # build reverse coverage map -> coverage_map.json
  python tier_replay.py classify <base> <head>    # class + derived surface for one diff
  python tier_replay.py replay                    # every chore merge since Platform V2 -> replay.json
"""
from __future__ import annotations
import ast, json, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

import os
ROOT = Path(os.environ.get("TIER_ROOT") or r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from research_workflow.grammar.compiler import _static_imports, _module_file  # noqa: E402

TEST_SCOPES = ["research_workflow/tests", "scripts/tests", "features/tests", "tests", "research/analysis/tests"]
IMPORT_ROOTS = ("features", "research_workflow", "research", "utils", "indicators", "backtests", "scripts", "collectors", "strategies")

# ---------------------------------------------------------------- change classes (mechanical, allowlist-based)
# Everything NOT matched by an allowlist below is CORE_SURFACE. Fail toward broad.
CAPABILITY_MODULE_RE = re.compile(r"^(features/trackers/(?!host_bindings\.py)[^/]+\.py|research/analysis/diagnostic_ops\.py)$")
REGISTRATION_FILES = {  # file -> (kind, names of module-level registration literals allowed to grow by pure insertion)
    "features/trackers/host_bindings.py": ("dict", {"TRACKER_BINDINGS", "__all__"}),
    "research_workflow/provider_host.py": ("dict", {"ADAPTER_REGISTRY", "__all__"}),
    "features/registry.py": ("call", {"_add"}),
    "research/analysis/diagnostic_ops.py": ("dict", {"OPS", "OP_INPUTS", "__all__"}),
}
SEED_FILES = {"research_workflow/capabilities_index.yaml"}
GENERATED_FILES = {"research_workflow/capabilities/registry.json", "docs/RESEARCH_YAML_REFERENCE.md"}
TEST_FILE_RE = re.compile(r"^(research_workflow/tests|scripts/tests|features/tests|tests|research/analysis/tests)/.+\.py$")
# studies/** is deliberately NOT inert: historical study artifacts are pinned scientific evidence; a chore that touches them is CORE.
INERT_RE = re.compile(r"^(docs/.*\.md|[A-Z_]+\.md|artifacts/.*|research_workflow/capabilities/proposals/.*\.yaml)$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def changed(base: str, head: str):
    out = []
    for line in git("diff", "--name-status", "-M", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append((parts[0][0], parts[-1].replace("\\", "/")))
    return out


# ---------------------------------------------------------------- registration-insertion AST rule
def _top_level_signature(src: str):
    tree = ast.parse(src)
    stmts = []
    literals = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = [t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)]
            val = node.value
            if targets and isinstance(val, ast.Dict):
                literals[targets[0]] = ("dict", {ast.dump(k): ast.dump(v) for k, v in zip(val.keys, val.values)})
                stmts.append(("LIT", targets[0])); continue
            if targets and isinstance(val, (ast.List, ast.Tuple)):
                literals[targets[0]] = ("list", [ast.dump(e) for e in val.elts])
                stmts.append(("LIT", targets[0])); continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            stmts.append(("CALL", node.value.func.id, ast.dump(node))); continue
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            stmts.append(("DEF", node.name, ast.dump(node))); continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            stmts.append(("IMPORT", ast.dump(node))); continue
        stmts.append(("OTHER", ast.dump(node)))
    return stmts, literals


def registration_insertion_only(rel: str, old_src: str, new_src: str):
    """True iff new == old plus (a) new entries in the named registration literals, (b) new top-level DEF/CALL/IMPORT
    statements whose names do not already exist, and nothing else changed. Mechanical, conservative."""
    kind, names = REGISTRATION_FILES[rel]
    try:
        os_, ol = _top_level_signature(old_src); ns_, nl = _top_level_signature(new_src)
    except SyntaxError:
        return False, "syntax"
    # every old non-literal statement must survive byte-identical (as AST dump)
    old_other = [s for s in os_ if s[0] != "LIT"]; new_other = [s for s in ns_ if s[0] != "LIT"]
    new_set = set(new_other)
    missing = [s for s in old_other if s not in new_set]
    if missing:
        return False, f"existing statements changed/removed: {[m[:2] for m in missing][:3]}"
    added = [s for s in new_other if s not in set(old_other)]
    for s in added:
        if s[0] == "CALL" and kind == "call" and s[1] in names:
            continue
        if s[0] in ("DEF",) and not any(o[0] == "DEF" and o[1] == s[1] for o in old_other):
            continue
        if s[0] == "IMPORT":
            continue
        return False, f"non-registration statement added: {s[:2]}"
    # literals: old entries subset of new
    for name, (lk, old_entries) in ol.items():
        if name not in nl:
            return False, f"literal {name} removed"
        nk, new_entries = nl[name]
        if lk == "dict":
            if any(k not in new_entries or new_entries[k] != v for k, v in old_entries.items()):
                return False, f"existing entries of {name} changed"
            if len(new_entries) != len(old_entries) and name not in names:
                return False, f"literal {name} grew but is not a declared registration point"
        else:
            if old_entries != new_entries[: len(old_entries)] and set(old_entries) - set(new_entries):
                return False, f"existing elements of {name} changed"
            if len(new_entries) != len(old_entries) and name not in names:
                return False, f"literal {name} grew but is not a declared registration point"
    for name in nl:
        if name not in ol:
            return False, f"new module-level literal {name}"
    return True, "insertion-only"


def yaml_insertion_only(old: str, new: str) -> bool:
    """Semantic, not textual: `cap scaffold` re-serialises the whole seed file (quoting/order churn), so the rule is
    'every old entry (by id) is present and unchanged in the new file, and only new ids were added'."""
    import yaml
    try:
        o = yaml.safe_load(old) or {}; n = yaml.safe_load(new) or {}
    except Exception:
        return False
    if set(o) - set(n):
        return False
    for kind, entries in o.items():
        old_by = {e.get("id"): e for e in (entries or [])}
        new_by = {e.get("id"): e for e in (n.get(kind) or [])}
        if any(k not in new_by or new_by[k] != v for k, v in old_by.items()):
            return False
    return True


def classify_diff(base: str, head: str):
    rows = []
    cls_votes = set()
    for status, rel in changed(base, head):
        reason = None; c = None
        if status == "D":
            c, reason = "CORE_SURFACE", "deletion"
        elif TEST_FILE_RE.match(rel) or rel.endswith("/conftest.py") and status == "A":
            c, reason = "TESTS", "test file"
        elif INERT_RE.match(rel):
            c, reason = "INERT", "docs/artifacts/proposal"
        elif CAPABILITY_MODULE_RE.match(rel) and status == "A":
            c, reason = "ADDITIVE_CAPABILITY", "new capability module"
        elif rel in REGISTRATION_FILES and status == "M":
            ok, why = registration_insertion_only(rel, git("show", f"{base}:{rel}"), git("show", f"{head}:{rel}"))
            c = "ADDITIVE_CAPABILITY" if ok else ("MODIFIED_CAPABILITY" if CAPABILITY_MODULE_RE.match(rel) else "CORE_SURFACE")
            reason = f"registration file: {why}"
        elif rel in SEED_FILES and status == "M":
            ok = yaml_insertion_only(git("show", f"{base}:{rel}"), git("show", f"{head}:{rel}"))
            c, reason = ("ADDITIVE_CAPABILITY" if ok else "MODIFIED_CAPABILITY"), "seed yaml " + ("insertion-only" if ok else "edited")
        elif rel in GENERATED_FILES:
            c, reason = "GENERATED", "regenerated by the gate (cap generate --check / gen_yaml_reference)"
        elif CAPABILITY_MODULE_RE.match(rel) and status == "M":
            c, reason = "MODIFIED_CAPABILITY", "existing capability module edited"
        else:
            c, reason = "CORE_SURFACE", "not on any allowlist"
        rows.append({"status": status, "path": rel, "class": c, "reason": reason})
        if c in ("ADDITIVE_CAPABILITY", "MODIFIED_CAPABILITY", "CORE_SURFACE"):
            cls_votes.add(c)
    if "CORE_SURFACE" in cls_votes:
        cls = "CORE_SURFACE"
    elif "MODIFIED_CAPABILITY" in cls_votes:
        cls = "MODIFIED_CAPABILITY"
    elif "ADDITIVE_CAPABILITY" in cls_votes:
        cls = "ADDITIVE_CAPABILITY"
    else:
        cls = "INERT_OR_TESTS_ONLY"   # docs/tests only: still runs the tests it touches + the fixed set
    return cls, rows


# ---------------------------------------------------------------- reverse coverage map
def _literal_seeds(rel: str):
    """String literals in a test/support file that name a repo file or module (subprocess-driven tests)."""
    out = set()
    try:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.strip().replace("\\", "/")
            if not s or len(s) > 200 or "\n" in s:
                continue
            if "/" in s and (ROOT / s).is_file() and s.endswith(".py"):
                out.add(s)
            elif re.fullmatch(r"[A-Za-z_][\w]*(\.[A-Za-z_]\w*)+", s) and s.split(".")[0] in IMPORT_ROOTS:
                f = _module_file(s, ROOT)
                if f:
                    out.add(f)
            elif re.fullmatch(r"[\w\-]+\.py", s):
                hits = list((ROOT / "scripts").glob(s)) + list((ROOT / "scripts" / "parity").glob(s))
                for h in hits:
                    out.add(h.relative_to(ROOT).as_posix())
    return out


def _imports_any(rel: str):
    """Repo-local imports including `scripts.*` and imports of modules under tests dirs (support modules)."""
    deps = set(_static_imports(rel, ROOT))
    try:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return deps
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for n in names:
            parts = n.split(".")
            if parts[0] in ("scripts", "collectors", "strategies", "indicators"):
                base = ROOT.joinpath(*parts)
                for cand in (base.with_suffix(".py"), base / "__init__.py"):
                    if cand.is_file():
                        deps.add(cand.relative_to(ROOT).as_posix())
    # package inits
    parts = Path(rel).parts[:-1]
    for i in range(1, len(parts) + 1):
        init = "/".join(parts[:i]) + "/__init__.py"
        if (ROOT / init).is_file():
            deps.add(init)
    return deps


def closure_of(seeds):
    seen = set(); stack = list(seeds)
    while stack:
        rel = stack.pop()
        if rel in seen or "__pycache__" in rel:
            continue
        seen.add(rel)
        for d in _imports_any(rel):
            if d not in seen:
                stack.append(d)
    return seen


def build_map():
    tests = []
    for scope in TEST_SCOPES:
        tests += sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / scope).rglob("test_*.py"))
    conftests = ["conftest.py", "scripts/tests/conftest.py"]
    cov = {}
    for t in tests:
        seeds = {t} | {c for c in conftests if t.startswith(c.rsplit("/", 1)[0] + "/") or "/" not in c}
        seeds |= _literal_seeds(t)
        for c in list(seeds):
            if "tests" in c:
                seeds |= _literal_seeds(c)
        cov[t] = sorted(closure_of(seeds))
    reverse = defaultdict(set)
    for t, files in cov.items():
        for f in files:
            reverse[f].add(t)
    (HERE / "coverage_map.json").write_text(json.dumps({"tests": cov, "reverse": {k: sorted(v) for k, v in reverse.items()}}, indent=1), encoding="utf-8")
    return cov, reverse


def load_map():
    d = json.loads((HERE / "coverage_map.json").read_text(encoding="utf-8"))
    return d["tests"], {k: set(v) for k, v in d["reverse"].items()}


def data_readers(rel: str):
    """Modules that mention a non-Python changed file's basename (registry.json, WORKFLOW.md, *.yaml...)."""
    base = Path(rel).name
    if base in ("__init__.py", ".gitignore") or not base:
        return set()
    r = subprocess.run(["git", "grep", "-n", "-F", base, "HEAD", "--", *[f"{r}/*.py" for r in IMPORT_ROOTS], "conftest.py"],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    bound = re.compile(r"(?<![\w.\-])" + re.escape(base) + r"(?![\w\-])")   # 'registry.json' must not match 'canonical_registry.json'
    out = set()
    for l in r.stdout.splitlines():
        parts = l.split(":", 3)
        if len(parts) >= 4 and bound.search(parts[3]):
            out.add(parts[1].replace("\\", "/"))
    return out


GENERATORS = {"research_workflow/capabilities/registry.json": "research_workflow/capabilities.py",
              "docs/RESEARCH_YAML_REFERENCE.md": "scripts/gen_yaml_reference.py"}


FIXED_ADDITIVE_TESTS = [   # the governance floor every capability tier runs regardless of reachability
    "research_workflow/tests/test_closure_transitive_imports.py", "research_workflow/tests/test_redteam_v2_closure.py",
    "research_workflow/tests/test_replay_closure.py", "scripts/tests/test_execution_closure.py",
    "scripts/tests/test_capabilities.py", "research_workflow/tests/test_grammar_v2.py", "research_workflow/tests/test_golden_fixture.py",
    "research_workflow/tests/test_runtime_bindings.py", "research_workflow/tests/test_docs_v2.py",
]


def derive_surface(rows, reverse, counts):
    surface = set(); why = {}
    for r in rows:
        rel = r["path"]
        if r["class"] == "TESTS":
            surface.add(rel); why.setdefault(rel, set()).add("changed test")
            continue
        if r["class"] == "GENERATED":
            g = GENERATORS[rel]
            for t in reverse.get(g, ()):
                surface.add(t); why.setdefault(t, set()).add(f"generated by {g}")
            continue
        if r["class"] == "INERT":
            for m in data_readers(rel):
                for t in reverse.get(m, ()):
                    surface.add(t); why.setdefault(t, set()).add(f"reads {rel} via {m}")
            for t in reverse.get(rel, ()):
                surface.add(t); why.setdefault(t, set()).add(f"names {rel}")
            continue
        if rel.endswith(".py"):
            for t in reverse.get(rel, ()):
                surface.add(t); why.setdefault(t, set()).add(f"imports {rel}")
        else:
            for m in data_readers(rel):
                for t in reverse.get(m, ()):
                    surface.add(t); why.setdefault(t, set()).add(f"reads {rel} via {m}")
    for t in FIXED_ADDITIVE_TESTS:
        if (ROOT / t).is_file():
            surface.add(t); why.setdefault(t, set()).add("fixed governance floor")
    n = sum(counts.get(t, 0) for t in surface)
    return sorted(surface), n, {k: sorted(v) for k, v in why.items()}


def load_counts():
    counts = {}
    for line in (HERE / "collect_counts.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            counts[parts[1]] = int(parts[0])
    return counts


MERGES = [  # (merge commit, label) -- every chore merge / direct platform commit on main since Platform V2 (dc2ae0fe)
    ("474cd650", "chore/end_cycle_wave1"), ("8b3d3d2f", "chore/collection_latency"), ("05656639", "docs/nt-collection-performance"),
    ("a7f932b0", "chore/v2-freeze-provenance-multicell"), ("be66e8de", "chore/v2-freeze-oos-multicell-model-records"),
    ("122c6f1a", "chore/controlled_feature_family_180s-missing_capability"), ("df43989a", "chore/analysis-parity-session-exclusions"),
    ("59c53310", "chore/supervisor-v1-efficiency-closeout"), ("e6792ab7", "chore/v2-closure-validate-before-write"),
    ("71e01ed3", "chore/supervisor-v1-hardening-03"), ("933be461", "chore/supervisor-v1-hardening-02"),
    ("66578afa", "chore/v2-closure-transitive-imports"), ("bb6cc9a7", "chore/restore-historical-artifacts-after-testrun (2)"),
    ("5d1447ca", "chore/restore-historical-artifacts-after-testrun (1)"), ("7169c635", "chore/supervisor-v1-hardening-01"),
    ("a33b1460", "chore/research-supervisor"), ("e461ea37", "chore/v2-multi-arm-modeling"),
    ("d8e99b4b", "chore/booster-integrity-and-test-isolation"), ("fc767f2d", "chore/v2-diagnostic-window-and-analysis"),
    ("6624a3ea", "chore/feature-window-parameterization"), ("df56be7b", "chore/platform-v2-redteam-hardening (follow-up)"),
    ("82ff9b00", "chore/platform-v2-redteam-hardening"), ("366cbb48", "chore/platform-v2-do-soon"),
    ("df26b124", "chore/platform-v2-closeout"), ("dc2ae0fe", "chore/platform-v2 (DO NOW)"),
    # direct platform commits on main (no chore branch)
    ("fba27a44", "direct: feat(workflow) sessions/handoffs/test baseline"), ("8338e554", "direct: writer lease identity"),
    ("bfedf510", "direct: antigravity identity"), ("63aecf79", "direct: fix(calendar) Globex authority"),
    ("3942565c", "direct: old-runtime policy + tuning adapter"),
]


def replay():
    cov, reverse = load_map(); counts = load_counts(); total = sum(counts.values())
    out = []
    for sha, label in MERGES:
        parents = git("rev-list", "--parents", "-n", "1", sha).split()
        base = parents[1]
        cls, rows = classify_diff(base, sha)
        surface, n, why = derive_surface(rows, reverse, counts)
        by_class = defaultdict(list)
        for r in rows:
            by_class[r["class"]].append(r["path"])
        out.append({"sha": sha, "label": label, "class": cls, "files": len(rows), "core_paths": by_class.get("CORE_SURFACE", [])[:12],
                    "modified_capability_paths": by_class.get("MODIFIED_CAPABILITY", []), "additive_paths": by_class.get("ADDITIVE_CAPABILITY", []),
                    "registration_reasons": [r["reason"] for r in rows if r["path"] in REGISTRATION_FILES or r["path"] in SEED_FILES],
                    "derived_surface_files": len(surface), "derived_surface_tests": n, "broad_tests": total,
                    "surface_fraction": round(n / total, 3) if total else None, "surface": surface})
        print(f"{sha} {cls:22s} files={len(rows):3d} surface={len(surface):3d} files/{n:4d} tests ({round(100*n/total)}%)  {label}")
    (HERE / "replay.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "map":
        cov, rev = build_map()
        print("tests", len(cov), "files covered", len(rev))
    elif cmd == "classify":
        cov, rev = load_map(); counts = load_counts()
        cls, rows = classify_diff(sys.argv[2], sys.argv[3])
        surface, n, why = derive_surface(rows, rev, counts)
        print(json.dumps({"class": cls, "rows": rows, "surface_files": len(surface), "surface_tests": n, "surface": surface, "why": why}, indent=1))
    elif cmd == "replay":
        replay()
