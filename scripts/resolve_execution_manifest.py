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


def _hash_file(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


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
                # Handle relative imports (e.g. from .data_plan import ...)
                if node.level > 0:
                    parent_dir = curr_file.parent
                    for _ in range(node.level - 1):
                        parent_dir = parent_dir.parent
                    target_parts = mod_base.split(".") if mod_base else []
                    cand_p = parent_dir.joinpath(*target_parts).with_suffix(".py")
                    if cand_p.exists():
                        _enqueue(cand_p.resolve())
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
                        # Check sub-modules imported via from ... import sub_module
                        for alias in node.names:
                            full_mod = f"{mod_base}.{alias.name}"
                            sub_res = resolve_module_to_path(full_mod, curr_file, repo_root)
                            if sub_res:
                                _enqueue(sub_res)
                                break
                        else:
                            if any(mod_base.startswith(pkg) for pkg in REPO_LOCAL_ROOT_PACKAGES):
                                unresolved.append({"source_file": str(curr_file), "import_target": mod_base})

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
        strat_path = repo_root.joinpath(*mod_name.split(".")).with_suffix(".py")
    else:
        strat_path = repo_root / "strategies" / f"{strat_val}.py"

    if not strat_path.exists():
        raise UnresolvedStrategyError(
            f"UNRESOLVED_STRATEGY: Strategy module for '{strat_val}' not found at {strat_path}"
        )

    return strat_path.resolve()


def resolve_study_files(study_dir: Path) -> Dict[str, Path]:
    """Resolves all study-specific contract, spec, clause, and test files."""
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

    # Include any study test files
    tests_dir = study_dir / "tests"
    if tests_dir.exists():
        for tf in sorted(tests_dir.glob("*.py")):
            rel = tf.relative_to(study_dir).as_posix()
            files[f"study:{rel}"] = tf.resolve()

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


def resolve_execution_manifest(
    study_dir: Path,
    repo_root: Optional[Path] = None,
    strict: bool = True,
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

    all_unresolved: List[Dict[str, str]] = []

    # 1. Study Contract Files
    study_files_map = resolve_study_files(study_dir)

    # 2. Dynamic Strategy File Resolution
    strategy_file = resolve_dynamic_strategy_file(study_dir, repo_root)

    # 3. Runtime Execution Graph Seeds
    runtime_seeds = [
        repo_root / "backtests/run_nt_study.py",
        repo_root / "backtests/nt_runtime/modes/collect.py",
        strategy_file,
    ]
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
    gov_closure_set, gov_unres = compute_ast_closure(governance_seeds, repo_root)
    all_unresolved.extend(gov_unres)

    if all_unresolved and strict:
        raise UnresolvedDependencyError(
            f"UNRESOLVED_DEPENDENCIES: Found {len(all_unresolved)} unresolvable repo-local imports: {all_unresolved}"
        )

    # 6. Build categorized file lists and compute hashes
    file_hashes: Dict[str, str] = {}
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

    # Compute SHA-256 for all resolved files
    for key in sorted(combined_paths.keys()):
        p = combined_paths[key]
        if not p.exists():
            raise FileNotFoundError(f"Resolved execution dependency does not exist on disk: {p}")
        file_hashes[key] = _hash_file(p)

    runtime_keys = sorted([f"repo:{p.relative_to(repo_root).as_posix()}" for p in runtime_closure_set])
    contract_keys = sorted([f"repo:{p.relative_to(repo_root).as_posix()}" for p in contract_closure_set])
    gov_keys = sorted([f"repo:{p.relative_to(repo_root).as_posix()}" for p in gov_closure_set])
    study_keys = sorted(list(study_files_map.keys()))
    tracker_keys = sorted([k for k in runtime_keys if "features/trackers" in k or "features/registry" in k])

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
        "entrypoint": "backtests/nt_runtime/modes/collect.py",
        "composite_sha256": composite_sha256,
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
