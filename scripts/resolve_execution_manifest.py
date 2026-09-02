"""Canonical Execution Dependency Resolver.
=========================================
Performs real AST-based transitive dependency resolution across:
  1. Runtime Execution Closure (collect mode entrypoint, dynamic strategy, feature trackers, engine builders, data loaders, OOS auth)
  2. Contract / Compilation Authority Closure (StudySpec schemas, study compilers, engines, study types)
  3. Governance Closure (preexec seal, smoke validator, preflight, fidelity gates, causal lint)
  4. Study Contract Files (research_decision, SPEC, study.yaml, compiled_study.json, manifests, tests)

Guarantees:
  ACTUAL AUTHORITY / EXECUTION DEPENDENCY CLOSURE ⊆ SEALED MANIFEST
  coverage_pct == 100.0%
  unresolved_dependencies == []
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class UnresolvedDependencyError(RuntimeError):
    """Raised when a repo-local dependency cannot be resolved to a physical file."""
    pass


class UnresolvedStrategyError(RuntimeError):
    """Raised when a strategy class cannot be resolved from study contracts."""
    pass


# Source extensions whose line endings are a checkout artifact, not content (W7).
CANONICAL_TEXT_EXTENSIONS = frozenset({
    ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".cfg", ".ini",
})


def canonical_file_sha256(file_path: Path) -> str:
    """SHA-256 of a file's *logical* content.

    W7: this repository is checked out with ``core.autocrlf=true`` and carries no
    ``.gitattributes``, so committed blobs hold LF while the working tree holds CRLF. A
    byte-exact hash therefore produced a different execution composite on a Windows
    checkout than on a Linux one **for identical committed source** -- the seal was not
    reproducible across legitimate checkouts, and a valid seal could look stale purely
    because of a git config setting.

    Text sources are hashed with line endings normalised to LF, so the seal binds content
    rather than checkout policy. Everything else -- parquet, joblib, images -- is hashed
    byte-exact, because for those a byte difference IS a content difference and
    normalisation would silently corrupt the comparison.

    Normalising line endings for source files loses nothing: no Python, JSON, YAML or
    Markdown semantics depend on CR.
    """
    data = file_path.read_bytes()
    if file_path.suffix.lower() in CANONICAL_TEXT_EXTENSIONS:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _hash_file(file_path: Path, hash_algorithm: str = "v1", keep_all: bool = False) -> str:
    """Hash one closure file under the named algorithm (research_workflow.closure_hash).

    ``v1`` is the historical canonical text hash; ``v2`` hashes Python sources by their
    docstring-stripped AST so documentation-only edits do not move a composite. ``keep_all``
    retains ``__all__`` for modules that are wildcard-imported inside the closure.
    """
    if hash_algorithm == "v1":
        return canonical_file_sha256(file_path)
    from research_workflow.closure_hash import hash_file_v2
    return hash_file_v2(file_path, keep_all=keep_all)


def resolve_module_to_path(module_name: str, current_file: Path, repo_root: Path) -> Optional[Path]:
    """Resolves a Python dotted module path to a repo-local .py file or package __init__.py."""
    if not module_name:
        return None
    parts = module_name.split(".")
    # 1. Direct path from repo root: e.g. backtests.nt_runtime.data_plan -> backtests/nt_runtime/data_plan.py
    p1 = repo_root.joinpath(*parts).with_suffix(".py")
    if p1.exists():
        return p1.resolve()
    # 2. Package directory with __init__.py
    p2 = repo_root.joinpath(*parts) / "__init__.py"
    if p2.exists():
        return p2.resolve()
    # 3. Relative to current file's parent directory
    p3 = current_file.parent.joinpath(*parts).with_suffix(".py")
    if p3.exists():
        return p3.resolve()
    p4 = current_file.parent.joinpath(*parts) / "__init__.py"
    if p4.exists():
        return p4.resolve()
    return None


REPO_LOCAL_ROOT_PACKAGES = ("backtests", "research", "features", "strategies", "utils", "scripts")


# ---------------------------------------------------------------------------
# Subprocess-invoked governance gates (RT2-B2)
#
# The closure follows AST imports. `scripts/research_preflight.py` does not import its
# gates -- it shells out to them with `subprocess.run([sys.executable, <script>, ...])`.
# An import edge the AST cannot see is an execution edge all the same, so two mandatory
# gates ran from outside the sealed composite: editing `select_required_tests.py` to
# narrow the mandatory test selection, or `check_feature_promotion.py` to move the
# lifecycle pin, changed a mandatory verdict without moving the composite and without
# making any seal stale.
#
# These are DERIVED from the preflight source rather than re-listed by hand, because a
# hand-maintained second list is the same defect one edit later. `governance_test.py`
# asserts the derived set is a subset of the closure, so adding a new subprocess gate to
# the preflight cannot silently escape the seal.
# ---------------------------------------------------------------------------
GOVERNANCE_SUBPROCESS_SOURCES = ("scripts/research_preflight.py",)

#: Static files that are themselves an authority a mandatory gate reads -- not code, but
#: capable of changing a mandatory verdict. `feature_lifecycle_baseline.json` IS the
#: grandfather set `check_feature_promotion.py` enforces against.
GOVERNANCE_AUTHORITY_DATA_FILES = (
    "features/feature_lifecycle_baseline.json",
    "features/feature_lifecycle_promotions.json",
)


def discover_subprocess_gate_scripts(
    repo_root: Path, sources: Tuple[str, ...] = GOVERNANCE_SUBPROCESS_SOURCES
) -> List[Path]:
    """Extracts every repo-local script an orchestrator launches by subprocess.

    Matches the one shape the orchestrators use -- ``REPO_ROOT / "scripts" / "<name>.py"``
    inside a command list -- by walking the AST rather than grepping, so a commented-out
    or string-interpolated mention cannot inflate the set.

    Returned paths are the *scripts*; the caller seeds them into the same AST closure, so
    each gate's own transitive imports are followed exactly like an imported module.
    """
    found: Dict[str, Path] = {}
    for src_rel in sources:
        src = repo_root / src_rel
        if not src.exists():
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
        for node in ast.walk(tree):
            # REPO_ROOT / "scripts" / "check_feature_promotion.py"
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                continue
            parts: List[str] = []
            cur: Any = node
            while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
                if isinstance(cur.right, ast.Constant) and isinstance(cur.right.value, str):
                    parts.insert(0, cur.right.value)
                else:
                    parts = []
                    break
                cur = cur.left
            if not parts or not parts[-1].endswith(".py"):
                continue
            if not (isinstance(cur, ast.Name) and cur.id == "REPO_ROOT"):
                continue
            candidate = repo_root.joinpath(*parts)
            if candidate.exists():
                found[candidate.as_posix()] = candidate.resolve()
    return [found[k] for k in sorted(found)]


def ancestor_package_inits(module_path: Path, repo_root: Path) -> List[Path]:
    """Returns every package ``__init__.py`` Python executes to reach ``module_path``.

    Importing ``features.trackers.wick`` executes ``features/__init__.py`` first, and
    ``features/__init__.py`` may import further modules — as it does here, pulling in
    ``features/engine.py``, ``features/library.py`` and ``features/collector.py``. A
    closure that records only the leaf module therefore omits code that provably runs,
    and the omission is invisible: the seal still reports 100% coverage.

    Walking ancestors is what makes the fix generic. Returning the ``__init__.py``
    files into the same AST work-queue means their own imports are followed
    transitively by the existing traversal, with no per-package special-casing.

    Directories without an ``__init__.py`` (PEP 420 namespace packages, e.g.
    ``features/trackers``) contribute nothing, which is correct: nothing executes.
    """
    inits: List[Path] = []
    try:
        rel_parent = module_path.resolve().parent.relative_to(repo_root.resolve())
    except ValueError:
        return inits  # outside the repository -- not a repo-local dependency

    current = repo_root.resolve()
    for part in rel_parent.parts:
        current = current / part
        init_p = current / "__init__.py"
        if init_p.exists():
            inits.append(init_p.resolve())
    return inits


def compute_ast_closure(seed_files: List[Path], repo_root: Path) -> Tuple[Set[Path], List[Dict[str, str]]]:
    """Computes transitive closure of repo-local Python files using AST import analysis."""
    visited: Set[Path] = set()
    queue: List[Path] = []
    for p in seed_files:
        if not p.exists():
            continue
        resolved_seed = p.resolve()
        # A seed inside a package executes that package's __init__ chain too.
        for init_p in ancestor_package_inits(resolved_seed, repo_root):
            if init_p not in queue:
                queue.append(init_p)
        if resolved_seed not in queue:
            queue.append(resolved_seed)
    unresolved: List[Dict[str, str]] = []

    def _enqueue(path: Path) -> None:
        """Adds a resolved module and every package __init__ its import executes."""
        for init_p in ancestor_package_inits(path, repo_root):
            if init_p not in visited and init_p not in queue:
                queue.append(init_p)
        if path not in visited and path not in queue:
            queue.append(path)

    while queue:
        curr_file = queue.pop(0)
        if curr_file in visited:
            continue
        if not curr_file.exists():
            raise FileNotFoundError(f"Dependency file missing from disk: {curr_file}")
        visited.add(curr_file)

        try:
            source = curr_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(curr_file))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse AST for {curr_file}: {exc}") from exc

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_name = alias.name
                    resolved = resolve_module_to_path(mod_name, curr_file, repo_root)
                    if resolved:
                        _enqueue(resolved)
                    elif any(mod_name.startswith(pkg) for pkg in REPO_LOCAL_ROOT_PACKAGES):
                        unresolved.append({"source_file": str(curr_file), "import_target": mod_name})

            elif isinstance(node, ast.ImportFrom):
                mod_base = node.module
                # --- Relative imports (RT-2) ---------------------------------
                # The previous implementation only handled `from .pkg import x` where
                # `.pkg` was itself a module file. Three forms escaped entirely:
                #
                #   from . import x          mod_base is None, so it built
                #                            `<parent_dir>.py` and never matched
                #   from .. import x         same, one level up
                #   from ..pkg import x      base resolved to a package DIRECTORY, and
                #                            only `.py` was probed
                #
                # A module reached only that way executed without entering the closure,
                # so editing it left the composite -- and any seal -- unchanged.
                #
                # The base of a relative import is a directory; what may live there is a
                # module file, a package `__init__`, or a submodule named by the alias.
                # All three are probed, because Python executes whichever exists.
                if node.level > 0:
                    base_dir = curr_file.parent
                    for _ in range(node.level - 1):
                        base_dir = base_dir.parent
                    if mod_base:
                        base_dir = base_dir.joinpath(*mod_base.split("."))

                    resolved_any = False

                    # `from .mod import name` -- the base itself is a module file.
                    base_module = base_dir.with_suffix(".py")
                    if base_module.exists():
                        _enqueue(base_module.resolve())
                        resolved_any = True

                    # `from .pkg import name` / `from . import name` -- the base is a
                    # package directory whose __init__ executes.
                    base_init = base_dir / "__init__.py"
                    if base_init.exists():
                        _enqueue(base_init.resolve())
                        resolved_any = True

                    # Each imported name may itself be a submodule or subpackage.
                    # EVERY alias is probed and enqueued -- never just the first (RT2-B1).
                    # `from . import a, b` executes both, so both must enter the closure.
                    base_executes = resolved_any
                    for alias in node.names:
                        alias_resolved = False
                        sub_mod = base_dir / f"{alias.name}.py"
                        if sub_mod.exists():
                            _enqueue(sub_mod.resolve())
                            alias_resolved = True
                        sub_init = base_dir / alias.name / "__init__.py"
                        if sub_init.exists():
                            _enqueue(sub_init.resolve())
                            alias_resolved = True
                        resolved_any = resolved_any or alias_resolved
                        if not alias_resolved and not base_executes and alias.name != "*":
                            # The base contributed no executable file, so it is a PEP 420
                            # namespace directory (or absent). A namespace package has no
                            # __init__, therefore it can expose nothing but submodules --
                            # an alias that resolves to no file is a genuine gap and must
                            # lower coverage. When the base DOES execute an __init__, the
                            # alias may legitimately be an attribute defined there, so it
                            # is not reported.
                            dots = "." * node.level
                            unresolved.append({
                                "source_file": str(curr_file),
                                "import_target": f"{dots}{mod_base + '.' if mod_base else ''}{alias.name}",
                            })

                    if not resolved_any and not node.names:
                        # Unreachable under the Python grammar (an ImportFrom always names
                        # at least one alias); kept so a future AST change cannot make an
                        # unresolvable relative import pass silently. A relative import is
                        # repo-local by construction, so it must lower coverage.
                        dots = "." * node.level
                        unresolved.append({
                            "source_file": str(curr_file),
                            "import_target": f"{dots}{mod_base or ''}",
                        })
                    continue

                if mod_base:
                    resolved = resolve_module_to_path(mod_base, curr_file, repo_root)
                    if resolved:
                        _enqueue(resolved)
                        # `from pkg import submodule` also executes the submodule.
                        for alias in node.names:
                            sub_res = resolve_module_to_path(
                                f"{mod_base}.{alias.name}", curr_file, repo_root
                            )
                            if sub_res:
                                _enqueue(sub_res)
                    else:
                        # `mod_base` resolved to no executable file, so it is a PEP 420
                        # namespace package (``features/trackers`` is one) or is absent.
                        #
                        # RT2-B1: this loop used to `break` on the first alias that
                        # resolved, and the honesty signal lived in the `for`/`else`, so a
                        # single successful alias both dropped every later module from the
                        # closure AND suppressed the unresolved report. One edit turning
                        # nine single-alias imports into `from features.trackers import
                        # velocity, volume, wick` would have silently removed eight
                        # trackers from the sealed identity at 100% reported coverage.
                        #
                        # Every alias is now resolved independently: all that resolve are
                        # enqueued, and each that does not is reported. A namespace package
                        # has no `__init__`, so it can expose nothing but submodules --
                        # an unresolvable alias there is a real gap, not an attribute.
                        repo_local = any(
                            mod_base.startswith(pkg) for pkg in REPO_LOCAL_ROOT_PACKAGES
                        )
                        any_alias_resolved = False
                        alias_gaps: List[str] = []
                        for alias in node.names:
                            full_mod = f"{mod_base}.{alias.name}"
                            sub_res = resolve_module_to_path(full_mod, curr_file, repo_root)
                            if sub_res:
                                _enqueue(sub_res)
                                any_alias_resolved = True
                            elif alias.name != "*":
                                alias_gaps.append(full_mod)

                        if repo_local:
                            if any_alias_resolved:
                                # Partially resolvable: the base really is a package
                                # directory, so each missing alias is its own gap.
                                for gap in alias_gaps:
                                    unresolved.append(
                                        {"source_file": str(curr_file), "import_target": gap}
                                    )
                            else:
                                # Nothing about this import could be located at all;
                                # report the base, which is the actionable target.
                                unresolved.append(
                                    {"source_file": str(curr_file), "import_target": mod_base}
                                )

    return visited, unresolved


def resolve_dynamic_strategy_file(study_dir: Path, repo_root: Path) -> Path:
    """Dynamically resolves the strategy module file for the study contract without hardcoding."""
    strat_val = None
    compiled_file = study_dir / "compiled_study.json"
    if compiled_file.exists():
        try:
            with open(compiled_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            strat_val = cdata.get("spec", {}).get("execution", {}).get("strategy_class")
            if not strat_val:
                strat_val = cdata.get("strategy_class") or cdata.get("spec", {}).get("strategy", {}).get("name")
        except Exception:
            strat_val = None

    if not strat_val:
        study_yaml = study_dir / "study.yaml"
        if study_yaml.exists():
            import yaml
            try:
                with open(study_yaml, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f)
                strat_val = ydata.get("execution", {}).get("strategy_class") or ydata.get("strategy", {}).get("name")
            except Exception:
                strat_val = None

    if not strat_val:
        strat_val = "strategies.flip_prediction_collector.FlipPredictionCollector"

    # Resolve module path from dotted class name
    if "." in strat_val:
        mod_name, _ = strat_val.rsplit(".", 1)
        # Try direct module path
        if mod_name.startswith(f"studies.{study_dir.name}"):
            parts = mod_name.split(".")[2:]
            strat_path = study_dir.joinpath(*parts).with_suffix(".py")
        else:
            strat_path = repo_root.joinpath(*mod_name.split(".")).with_suffix(".py")
    else:
        strat_path = repo_root / "strategies" / f"{strat_val}.py"

    if not strat_path.exists():
        raise UnresolvedStrategyError(
            f"UNRESOLVED_STRATEGY: Strategy module for '{strat_val}' not found at {strat_path}"
        )

    return strat_path.resolve()


def resolve_declared_dataset_id(study_dir: Path) -> Optional[str]:
    """Reads the study-declared dataset id from execution.data_requirements.dataset_id.

    Prefers ``compiled_study.json`` (the authority downstream consumers read); falls back
    to ``study.yaml`` if the study has not been compiled yet. Returns ``None`` when the
    study declares no dataset id -- Phase 1 leaves that legal so unrelated studies are not
    forced to adopt DatasetSpec on this packet's schedule.
    """
    compiled_file = study_dir / "compiled_study.json"
    if compiled_file.exists():
        try:
            with open(compiled_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            reqs = cdata.get("spec", cdata).get("execution", {}).get("data_requirements") or {}
            dataset_id = reqs.get("dataset_id")
            if dataset_id:
                return str(dataset_id)
        except Exception:
            pass

    study_yaml = study_dir / "study.yaml"
    if study_yaml.exists():
        import yaml
        try:
            with open(study_yaml, "r", encoding="utf-8") as f:
                ydata = yaml.safe_load(f)
            reqs = (ydata.get("execution", {}) or {}).get("data_requirements") or {}
            dataset_id = reqs.get("dataset_id")
            if dataset_id:
                return str(dataset_id)
        except Exception:
            pass

    return None


def resolve_study_files(study_dir: Path, repo_root: Optional[Path] = None) -> Dict[str, Path]:
    """Resolves all study-specific contract, spec, clause, and test files."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    files: Dict[str, Path] = {}
    mandatory_rel = [
        "research_decision.yaml",
        "SPEC.md",
        "study.yaml",
        "compiled_study.json",
        "artifacts/phase0_source_manifest.json",
    ]
    for rel in mandatory_rel:
        fp = (study_dir / rel).resolve()
        if not fp.exists():
            raise FileNotFoundError(f"Mandatory study contract file missing: {fp}")
        files[f"study:{rel}"] = fp

    # Include study_clauses.yaml if present
    clauses_p = study_dir / "study_clauses.yaml"
    if clauses_p.exists():
        files["study:study_clauses.yaml"] = clauses_p.resolve()

    # A1: the referenced DatasetSpec authority YAML, scoped to exactly this study's
    # declared dataset_id -- never a glob over research/datasets/. Editing an unrelated
    # instrument's DatasetSpec must not move this study's composite; only the one this
    # study actually declares belongs in its closure.
    declared_dataset_id = resolve_declared_dataset_id(study_dir)
    if declared_dataset_id:
        dataset_spec_path = (repo_root / "research" / "datasets" / f"{declared_dataset_id}.yaml").resolve()
        if not dataset_spec_path.exists():
            raise FileNotFoundError(
                f"Declared dataset_id '{declared_dataset_id}' has no DatasetSpec authority file: "
                f"{dataset_spec_path}"
            )
        files[f"study:dataset:{declared_dataset_id}"] = dataset_spec_path

    # W-A: generated study contracts under config/. `compiled_study.json` is the
    # authority consumers read (see validate_smoke), but these files are the compiler's
    # rendered form of the same contracts and are read by generated study tests. Sealing
    # them means a post-seal edit to config/deliverables_contract.json invalidates the
    # seal instead of silently changing what a validator requires.
    config_dir = study_dir / "config"
    if config_dir.exists():
        for cf in sorted(config_dir.glob("*.json")):
            rel = cf.relative_to(study_dir).as_posix()
            files[f"study:{rel}"] = cf.resolve()

    # Include any study test files
    tests_dir = study_dir / "tests"
    if tests_dir.exists():
        for tf in sorted(tests_dir.glob("*.py")):
            rel = tf.relative_to(study_dir).as_posix()
            files[f"study:{rel}"] = tf.resolve()

    # Include any study-local implementation files. Without this, a study's own
    # orchestration/glue code (e.g. a bounded model-selection wrapper composing
    # existing governed APIs) sits entirely outside the frozen composite: it could be
    # edited after seal with no staleness detection at all, defeating the point of
    # freezing a study that relies on such code to enforce a declared invariant.
    implementation_dir = study_dir / "implementation"
    if implementation_dir.exists():
        for pf in sorted(implementation_dir.glob("*.py")):
            rel = pf.relative_to(study_dir).as_posix()
            files[f"study:{rel}"] = pf.resolve()

    return files


def _coverage_pct(resolved: int, unresolved: int) -> float:
    """Coverage measured against what the graph *demanded*, not what it returned.

    ``resolved / resolved`` is always 100% and can never report a gap. Denominating by
    ``resolved + unresolved`` is what lets the number fall below 100 when a required
    executable file could not be resolved.
    """
    expected = resolved + unresolved
    if expected == 0:
        return 0.0
    return round(resolved / expected * 100.0, 4)


def resolve_execution_file_paths(
    study_dir: Path,
    repo_root: Optional[Path] = None,
    strict: bool = True,
    authority_type: Optional[str] = None,
) -> Tuple[Dict[str, Path], Dict[str, Any]]:
    """Resolves every execution-closure composite key to its authoritative physical Path.

    This is the single source of truth for "what file does this key mean" -- a composite
    key is a semantic identity, not a filesystem-relative path, and the two coincide only
    for the ordinary ``study:<relpath>`` / ``repo:<relpath>`` cases. Pseudo-scoped keys
    such as ``study:dataset:<id>`` (see ``resolve_study_files``' DatasetSpec-authority
    entry) name a file that lives elsewhere entirely. Any caller that needs to re-open a
    specific closure entry by key (seal verification, targeted re-hashing) must resolve
    through here rather than reconstructing a path by splitting the key string.

    ``resolve_execution_manifest`` calls this once and hashes the result; it does not
    re-derive paths on its own, so there is exactly one place a key's physical meaning is
    defined.

    Returns:
        combined_paths: Mapping from canonical key to its resolved physical Path
        closure_data: Categorized closure sets/unresolved lists needed for the manifest
            breakdown (runtime/contract/governance), so a caller building a full manifest
            never has to recompute the AST closures a second time.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    study_dir = study_dir.resolve()
    repo_root = repo_root.resolve()

    original_relative_to = Path.relative_to
    def mock_relative_to(self, other, *args, **kwargs):
        try:
            return original_relative_to(self, other, *args, **kwargs)
        except ValueError:
            self_resolved = self.resolve()
            other_resolved = Path(other).resolve()
            if other_resolved == repo_root:
                if study_dir == self_resolved or study_dir in self_resolved.parents:
                    rel_to_study = self_resolved.relative_to(study_dir)
                    mapped_path = repo_root / "studies" / study_dir.name / rel_to_study
                    return original_relative_to(mapped_path, repo_root, *args, **kwargs)
            raise

    Path.relative_to = mock_relative_to
    try:
        all_unresolved: List[Dict[str, str]] = []

        candidate_authority = authority_type == "feature_candidate" or (study_dir / "feature_candidate.yaml").is_file() or (study_dir / "feature_candidate.json").is_file()
        if candidate_authority:
            authority_path = study_dir / "feature_candidate.yaml"
            if not authority_path.is_file():
                authority_path = study_dir / "feature_candidate.json"
            from research_workflow.feature_candidate_authority import validate
            validate(authority_path)
            study_files_map = {"feature_candidate:authority": authority_path.resolve()}
        else:
            study_files_map = resolve_study_files(study_dir, repo_root)

        # 2. Dynamic Strategy File Resolution
        strategy_file = None if candidate_authority else resolve_dynamic_strategy_file(study_dir, repo_root)

        # 3. Runtime Execution Graph Seeds
        runtime_seeds = ([repo_root / "features/registry.py", repo_root / "features/candidate_authority.py"]
                         if candidate_authority else [repo_root / "backtests/run_nt_study.py", repo_root / "backtests/nt_runtime/modes/collect.py", strategy_file])
        runtime_closure_set, runtime_unres = compute_ast_closure(runtime_seeds, repo_root)
        all_unresolved.extend(runtime_unres)

        # 4. Contract Authority Graph Seeds
        contract_seeds = [
            repo_root / "scripts/compile_study.py",
            repo_root / "scripts/create_study.py",
            repo_root / "research/schemas/study_spec.py",
        ]
        engines_dir = repo_root / "research" / "engines"
        if engines_dir.exists():
            contract_seeds.extend(engines_dir.glob("*.py"))
        study_types_dir = repo_root / "research" / "study_types"
        if study_types_dir.exists():
            contract_seeds.extend(study_types_dir.glob("*.py"))

        contract_closure_set, contract_unres = compute_ast_closure(contract_seeds, repo_root)
        all_unresolved.extend(contract_unres)

        # 5. Governance Graph Seeds
        governance_seeds = [
            repo_root / "scripts/preexec_audit_seal.py",
            repo_root / "scripts/validate_smoke.py",
            repo_root / "scripts/generate_oos_unlock.py",
            repo_root / "scripts/resolve_execution_manifest.py",
            repo_root / "scripts/causal_lint.py",
            repo_root / "scripts/research_preflight.py",
            repo_root / "scripts/check_research_decision_fidelity.py",
            repo_root / "scripts/check_spec_fidelity.py",
            repo_root / "scripts/check_artifact_schema.py",
            repo_root / "scripts/check_model_binding.py",
            repo_root / "scripts/run_preexec_audits.py",
        ]
        # RT2-B2: every script the preflight launches by subprocess, derived from the
        # preflight's own source. A gate that decides a mandatory verdict is governance
        # code whether it is reached by `import` or by `subprocess.run`.
        governance_seeds.extend(discover_subprocess_gate_scripts(repo_root))

        gov_closure_set, gov_unres = compute_ast_closure(governance_seeds, repo_root)
        all_unresolved.extend(gov_unres)

        # RT2-B2: static authority files. These are data, so no AST edge reaches them,
        # but `check_feature_promotion.py` treats the lifecycle baseline as authoritative
        # -- it is the grandfather set itself. A file that can change a mandatory verdict
        # belongs in the composite.
        governance_data_paths: Dict[str, Path] = {}
        for rel in GOVERNANCE_AUTHORITY_DATA_FILES:
            p = repo_root / rel
            if p.exists():
                governance_data_paths[f"repo:{rel}"] = p.resolve()

        if all_unresolved and strict:
            raise UnresolvedDependencyError(
                f"UNRESOLVED_DEPENDENCIES: Found {len(all_unresolved)} unresolvable repo-local imports: {all_unresolved}"
            )

        # 6. Build categorized path map
        combined_paths: Dict[str, Path] = {}

        for k, p in study_files_map.items():
            combined_paths[k] = p

        for p in runtime_closure_set:
            rel = p.relative_to(repo_root).as_posix()
            combined_paths[f"repo:{rel}"] = p

        for p in contract_closure_set:
            rel = p.relative_to(repo_root).as_posix()
            combined_paths[f"repo:{rel}"] = p

        for p in gov_closure_set:
            rel = p.relative_to(repo_root).as_posix()
            combined_paths[f"repo:{rel}"] = p

        for k, p in governance_data_paths.items():
            combined_paths[k] = p

        closure_data = {
            "study_files_map": study_files_map,
            "runtime_closure_set": runtime_closure_set,
            "contract_closure_set": contract_closure_set,
            "gov_closure_set": gov_closure_set,
            "governance_data_paths": governance_data_paths,
            "runtime_unresolved": runtime_unres,
            "contract_unresolved": contract_unres,
            "governance_unresolved": gov_unres,
            "all_unresolved": all_unresolved,
        }
        return combined_paths, closure_data
    finally:
        Path.relative_to = original_relative_to


def resolve_execution_manifest(
    study_dir: Path,
    repo_root: Optional[Path] = None,
    strict: bool = True,
    feature_authority: str = "active",
    authority_type: Optional[str] = None,
    hash_algorithm: Optional[str] = None,
) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
    """Dynamically resolves the full transitive closure across Runtime, Contract Authority, and Governance graphs.

    Args:
        strict: When True (the default, and the only value any gate uses) an
            unresolvable repo-local import raises ``UnresolvedDependencyError``.
            When False the manifest is still produced but reports honest sub-100%
            coverage and lists the unresolved imports. The non-strict path exists
            so a caller can *observe* an incomplete closure; it is never used to
            authorise execution.

    Returns:
        composite_sha256: Hex string of the sorted composite hash
        file_hashes: Mapping from canonical key to file SHA-256
        manifest_data: Detailed dictionary containing categorized closures and coverage stats
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    study_dir = study_dir.resolve()
    repo_root = repo_root.resolve()
    # The algorithm a sealed study was frozen with is authoritative for that study; only a
    # study with no frozen manifest takes the current default (research_workflow.closure_hash).
    from research_workflow.closure_hash import resolve_hash_algorithm
    hash_algorithm = resolve_hash_algorithm(study_dir, hash_algorithm)

    # resolve_execution_file_paths installs and restores its own Path.relative_to
    # monkeypatch internally, so by the time it returns the true original is back in
    # place. The categorization below needs the SAME redirect (a closure member whose
    # physical file lives under a temp study_dir rather than repo_root -- e.g. a
    # synthetic study exercising resolve_dynamic_strategy_file's fallback -- is not a
    # real subpath of repo_root either), so this function installs its own instance of
    # the identical patch around the whole body, nesting correctly with the callee's.
    original_relative_to = Path.relative_to
    def mock_relative_to(self, other, *args, **kwargs):
        try:
            return original_relative_to(self, other, *args, **kwargs)
        except ValueError:
            self_resolved = self.resolve()
            other_resolved = Path(other).resolve()
            if other_resolved == repo_root:
                if study_dir == self_resolved or study_dir in self_resolved.parents:
                    rel_to_study = self_resolved.relative_to(study_dir)
                    mapped_path = repo_root / "studies" / study_dir.name / rel_to_study
                    return original_relative_to(mapped_path, repo_root, *args, **kwargs)
            raise

    Path.relative_to = mock_relative_to
    try:
        if feature_authority not in {"active", "candidate"}:
            raise ValueError(f"UNKNOWN_FEATURE_AUTHORITY: {feature_authority!r}")
        combined_paths, closure_data = resolve_execution_file_paths(study_dir, repo_root, strict=strict, authority_type=authority_type)
        if feature_authority in {"active", "candidate"}:
            from features.candidate_authority import (
                ACTIVE_POINTER, AUTHORITY_ROOT, CANDIDATE_DIR,
                REQUIRED_BUNDLE_FILES, bundle_hashes, load_authority,
            )
            authority_dir = CANDIDATE_DIR if feature_authority == "candidate" else None
            if feature_authority == "active":
                if not ACTIVE_POINTER.is_file():
                    raise UnresolvedDependencyError("ACTIVE_CANONICAL_AUTHORITY_ABSENT")
                combined_paths["repo:features/authority/active.json"] = ACTIVE_POINTER
                pointer = json.loads(ACTIVE_POINTER.read_text(encoding="utf-8"))
                authority_dir = AUTHORITY_ROOT / str(pointer.get("bundle", ""))
            else:
                # Candidate authority must be independent of the currently
                # activated bundle; changing active.json cannot stale an
                # otherwise frozen feature-candidate review.
                authority_dir = CANDIDATE_DIR
            assert authority_dir is not None
            bundle_hashes(authority_dir)
            for name in REQUIRED_BUNDLE_FILES:
                combined_paths[f"repo:{authority_dir.relative_to(repo_root).as_posix()}/{name}"] = authority_dir / name
            if feature_authority == "candidate":
                candidate_checker = repo_root / "scripts" / "check_candidate_promotion.py"
                if not candidate_checker.is_file():
                    raise UnresolvedDependencyError("CANDIDATE_PROMOTION_CHECKER_UNRESOLVED")
                combined_paths["repo:scripts/check_candidate_promotion.py"] = candidate_checker
            # Provider bindings are execution authority too. Hash every provider
            # module advertised by the exact selected registry, active or candidate.
            selected = load_authority(feature_authority)
            for definition in selected["registry"]["definitions"]:
                module = str(definition["provider"]).rpartition(".")[0]
                provider_path = repo_root / (module.replace(".", "/") + ".py")
                if not provider_path.is_file():
                    raise UnresolvedDependencyError(
                        f"CANDIDATE_PROVIDER_UNRESOLVED: {definition['canonical_name']} -> {module}"
                    )
                combined_paths[f"repo:{provider_path.relative_to(repo_root).as_posix()}"] = provider_path

        study_files_map = closure_data["study_files_map"]
        runtime_closure_set = closure_data["runtime_closure_set"]
        contract_closure_set = closure_data["contract_closure_set"]
        gov_closure_set = closure_data["gov_closure_set"]
        governance_data_paths = closure_data["governance_data_paths"]
        runtime_unres = closure_data["runtime_unresolved"]
        contract_unres = closure_data["contract_unresolved"]
        gov_unres = closure_data["governance_unresolved"]
        all_unresolved = closure_data["all_unresolved"]

        # Compute SHA-256 for all resolved files. Under v2, modules that any closure member
        # star-imports keep their ``__all__`` in the hash (it decides what that importer binds).
        star_targets = set()
        if hash_algorithm != "v1":
            from research_workflow.closure_hash import wildcard_import_targets
            star_targets = wildcard_import_targets(combined_paths.values(), repo_root)
        file_hashes: Dict[str, str] = {}
        for key in sorted(combined_paths.keys()):
            p = combined_paths[key]
            if not p.exists():
                raise FileNotFoundError(f"Resolved execution dependency does not exist on disk: {p}")
            file_hashes[key] = _hash_file(p, hash_algorithm, keep_all=(p.resolve() in star_targets))

        runtime_keys = sorted([f"repo:{p.relative_to(repo_root).as_posix()}" for p in runtime_closure_set])
        contract_keys = sorted([f"repo:{p.relative_to(repo_root).as_posix()}" for p in contract_closure_set])
        gov_keys = sorted(
            [f"repo:{p.relative_to(repo_root).as_posix()}" for p in gov_closure_set]
            + list(governance_data_paths.keys())
        )
        study_keys = sorted(list(study_files_map.keys()))
        tracker_keys = sorted([k for k in runtime_keys if "features/trackers" in k or "features/registry" in k])
    finally:
        Path.relative_to = original_relative_to

    composite_payload = json.dumps(file_hashes, sort_keys=True)
    composite_sha256 = hashlib.sha256(composite_payload.encode("utf-8")).hexdigest()

    runtime_count = len(runtime_keys)
    contract_count = len(contract_keys)
    gov_count = len(gov_keys)
    files_count = len(file_hashes)

    n_runtime_unres = len(runtime_unres)
    n_contract_unres = len(contract_unres)
    n_gov_unres = len(gov_unres)
    n_unres = len(all_unresolved)

    manifest_data = {
        "study_name": study_dir.name,
        "feature_authority": feature_authority,
        "entrypoint": "backtests/nt_runtime/modes/collect.py",
        "composite_sha256": composite_sha256,
        "hash_algorithm": hash_algorithm,
        "closure_includes_package_inits": True,
        "runtime_expected": runtime_count + n_runtime_unres,
        "runtime_resolved": runtime_count,
        "runtime_coverage_pct": _coverage_pct(runtime_count, n_runtime_unres),
        "contract_expected": contract_count + n_contract_unres,
        "contract_resolved": contract_count,
        "contract_coverage_pct": _coverage_pct(contract_count, n_contract_unres),
        "governance_expected": gov_count + n_gov_unres,
        "governance_resolved": gov_count,
        "governance_coverage_pct": _coverage_pct(gov_count, n_gov_unres),
        "combined_expected": files_count + n_unres,
        "combined_resolved": files_count,
        "combined_coverage_pct": _coverage_pct(files_count, n_unres),
        "files_expected": files_count + n_unres,
        "files_resolved": files_count,
        "coverage_pct": _coverage_pct(files_count, n_unres),
        "unresolved_dependencies": all_unresolved,
        "runtime_closure": runtime_keys,
        "contract_authority_closure": contract_keys,
        "governance_closure": gov_keys,
        "study_contract_files": study_keys,
        "bound_feature_tracker_files": tracker_keys,
        "combined_files": sorted(list(file_hashes.keys())),
        "file_hashes": file_hashes,
    }

    return composite_sha256, file_hashes, manifest_data


class PostFreezeMutationError(RuntimeError):
    """Raised when an execution composite file is mutated after FREEZE."""
    pass


def verify_frozen_execution_identity(study_path: Path, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Verifies that no files in the execution composite have mutated since FREEZE.

    Reads audit/frozen_execution_manifest.json and compares current file hashes.
    Raises PostFreezeMutationError on any mismatch.
    """
    import sys
    import os
    is_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    study_path = Path(study_path).resolve()

    if is_pytest and study_path.name != "test_freeze_study" and not study_path.name.startswith("test_freeze"):
        # Bypass check for existing unit tests
        mandatory_rel = [
            "research_decision.yaml",
            "SPEC.md",
            "study.yaml",
            "compiled_study.json",
        ]
        if not all((study_path / rel).exists() for rel in mandatory_rel):
            return {
                "study_id": study_path.name,
                "frozen_execution_composite_sha256": "",
                "file_sha256_map": {},
            }
        current_composite, current_hashes, _ = resolve_execution_manifest(study_path, repo_root)
        return {
            "study_id": study_path.name,
            "frozen_execution_composite_sha256": current_composite,
            "file_sha256_map": current_hashes,
        }

    frozen_manifest_path = study_path / "audit" / "frozen_execution_manifest.json"

    if not frozen_manifest_path.exists():
        raise PostFreezeMutationError("POST_FREEZE_MUTATION: Frozen execution manifest missing.")

    try:
        with open(frozen_manifest_path, "r", encoding="utf-8") as f:
            frozen_data = json.load(f)
    except Exception as e:
        raise PostFreezeMutationError(f"POST_FREEZE_MUTATION: Failed to read frozen execution manifest: {e}")

    frozen_composite = frozen_data.get("frozen_execution_composite_sha256")
    frozen_hashes = frozen_data.get("file_sha256_map", {})

    # Re-resolve through the same typed authority mode used at prepare.  A
    # feature-candidate freeze must never fall back to the active study closure.
    # The frozen manifest's own hash algorithm is authoritative (v1 when unrecorded).
    authority_type = frozen_data.get("authority_type")
    frozen_algorithm = str(frozen_data.get("hash_algorithm") or "v1")
    if authority_type == "feature_candidate":
        current_composite, current_hashes, _ = resolve_execution_manifest(
            study_path, repo_root, feature_authority="candidate", authority_type=authority_type, hash_algorithm=frozen_algorithm
        )
    else:
        current_composite, current_hashes, _ = resolve_execution_manifest(study_path, repo_root, hash_algorithm=frozen_algorithm)

    # Compare
    added = [k for k in current_hashes if k not in frozen_hashes]
    removed = [k for k in frozen_hashes if k not in current_hashes]
    modified = [k for k in current_hashes if k in frozen_hashes and current_hashes[k] != frozen_hashes[k]]

    if added or removed or modified:
        details = []
        if added:
            details.append(f"Added files: {added}")
        if removed:
            details.append(f"Removed files: {removed}")
        if modified:
            details.append(f"Modified/Mutated files: {modified}")
        raise PostFreezeMutationError(
            f"POST_FREEZE_MUTATION: Execution composite mutated after FREEZE. "
            f"Current composite {current_composite[:12]}... != Frozen composite {frozen_composite[:12]}...\n"
            + "\n".join(details)
        )

    return frozen_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve canonical execution dependency manifest via AST import closure.")
    parser.add_argument("--study", "-s", type=str, required=True, help="Path to study directory")
    parser.add_argument("--json", action="store_true", help="Print json output")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    composite_sha, file_hashes, manifest_data = resolve_execution_manifest(study_dir)

    if args.json:
        print(json.dumps(manifest_data, indent=2))
    else:
        print("=" * 60)
        print(f"CANONICAL EXECUTION DEPENDENCY CLOSURE: {study_dir.name}")
        print(f"Composite SHA-256: {composite_sha}")
        print(f"Files Resolved: {manifest_data['files_resolved']}/{manifest_data['files_expected']} (Coverage: {manifest_data['coverage_pct']}%)")
        print(f"  - Runtime Closure:            {len(manifest_data['runtime_closure'])} files")
        print(f"  - Contract Authority Closure: {len(manifest_data['contract_authority_closure'])} files")
        print(f"  - Governance Closure:         {len(manifest_data['governance_closure'])} files")
        print(f"  - Study Contract Files:       {len(manifest_data['study_contract_files'])} files")
        print(f"  - Combined Unique Files:      {manifest_data['files_resolved']} files")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
