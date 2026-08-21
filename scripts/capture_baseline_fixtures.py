"""Baseline Fixture Capture Runner.
==================================

Implements ``BASELINE_CAPTURE_RERUN_PLAN.md`` (v5.1): captures immutable golden
baselines from the *unmodified* legacy backtest entrypoints so that the B1
backtest harness can later be proven equivalent to them.

Design rules enforced here (each maps to a section of the plan):

* **Phase 1 is authoritative.** The legacy command is executed verbatim as a
  subprocess. No ``python -c`` wrapper, no ``exec(open(...))``, no monkeypatching,
  no environment mutation.  (§4 Phase 1)
* **Every declared target is preserved before execution and restored after.**
  Targets absent before the run are copied into immutable evidence and then
  removed, so the working tree is left exactly as it was found.  (§2)
* **Only the four statuses in §1 are ever emitted.** There is no year-derived
  status; absence is always an *observation*.  (§1, §2B)
* **Quarantine is used only where it is required to prove a fresh absence.**
  (§2A)
* **Source identity is hashed before and after.** A change to any repo-local file
  in the entrypoint's import closure during the capture invalidates the run.  (§5)
* **Loaded-module tracing is supplemental only** and never replaces the
  authoritative CLI run.  (§4 Phase 2)

Usage
-----
    python scripts/capture_baseline_fixtures.py --dry-run
    python scripts/capture_baseline_fixtures.py --fixture fixture_1_score_fanning
    python scripts/capture_baseline_fixtures.py            # both fixtures
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]

# The capture parent process imports strategy config classes to materialise the
# resolved-config snapshot. Running as `python scripts/capture_baseline_fixtures.py`
# puts `scripts/` on sys.path, not the repo root, so make repo-local packages
# importable. This affects only the parent's introspection: the authoritative
# fixture runs are separate subprocesses whose own preamble is untouched.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Status vocabulary  (BASELINE_CAPTURE_RERUN_PLAN.md §1)
# ---------------------------------------------------------------------------

STATUS_PRODUCED = "produced_by_current_run"
STATUS_ABSENT_VERIFIED = "expected_absent_verified"
STATUS_ABSENT_UNVERIFIED = "expected_absent_unverified_due_to_preexisting_target"
STATUS_STALE_UNMANAGED = "preexisting_stale_unmanaged"

VALID_STATUSES = frozenset(
    {STATUS_PRODUCED, STATUS_ABSENT_VERIFIED, STATUS_ABSENT_UNVERIFIED, STATUS_STALE_UNMANAGED}
)

# Untracked .py files permitted by gate 3 (plan §3B).
UNTRACKED_PY_ALLOWLIST = frozenset(
    {
        "scripts/capture_baseline_fixtures.py",
        "scripts/tests/test_capture_baseline_fixtures.py",
    }
)

# Volatile columns excluded from normalized output identity (plan §6).
VOLATILE_COLUMNS = frozenset({"trader_id", "account_id", "run_id", "ts_captured"})

CAPTURE_SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Fixture declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetSpec:
    """A declared output path of a fixture.

    Parameters
    ----------
    path:
        Repo-relative path the legacy run may write.
    expectation:
        ``"produced"``  - the run is expected to create/overwrite this file.
        ``"conditional"`` - the run creates it only if a runtime condition holds.
        Conditional targets are quarantined so a fresh absence can be *proven*.
    hash_output:
        Whether the produced artifact participates in normalized identity hashing.
    absence_cause:
        Human-readable interpretation recorded *alongside* an observed absence.
        Never used as a precondition or to pre-declare a status.
    """

    path: str
    expectation: str
    hash_output: bool = True
    absence_cause: Optional[str] = None

    @property
    def quarantine_required(self) -> bool:
        """Every declared target is quarantined before an authoritative capture.

        Originally only `conditional` targets were quarantined, on the reasoning
        that quarantine exists to prove a fresh *absence*. Red Team M2 showed that
        leaves `produced` targets attributable on modification time alone: both
        primary baselines pre-existed, were byte-identical afterwards, and were
        never moved aside, so the "post-run hash comparison" half of the plan's
        attribution rule was degenerate.

        Quarantining a `produced` target makes `path_was_clean` true, so its
        presence after the run *is* the proof that this run created it.
        """
        return self.expectation in ("produced", "conditional")


@dataclass(frozen=True)
class FixtureSpec:
    fixture_id: str
    description: str
    entrypoint: str
    argv: Tuple[str, ...]
    targets: Tuple[TargetSpec, ...]
    stale_watch_globs: Tuple[str, ...] = ()
    external_inputs: Tuple[str, ...] = ()
    catalog_probe: Optional[Dict[str, Any]] = None
    side_effect_dirs: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
    resolved_config_spec: Optional[Dict[str, Any]] = None
    fill_evidence_statement: str = "No fill-level artifact is produced by this fixture."

    @property
    def command(self) -> List[str]:
        return [sys.executable, self.entrypoint, *self.argv]


FIXTURES: Tuple[FixtureSpec, ...] = (
    FixtureSpec(
        fixture_id="fixture_1_score_fanning",
        description=(
            "ScoreFanningStrategy multi-policy virtual evaluator, single day 2023-03-03. "
            "Places zero NT orders; its real output is per-policy virtual trade tables."
        ),
        entrypoint="backtests/run_staged_backtest.py",
        argv=("--start-date", "2023-03-03", "--end-date", "2023-03-03"),
        targets=(
            TargetSpec("backtests/results/checkpoints/results_R2.5.parquet", "produced"),
            TargetSpec(
                "backtests/results/checkpoints/results_R5.parquet",
                "conditional",
                absence_cause=(
                    "ScoreFanningStrategy.on_bar emits a constant dummy_score=0.55 which is "
                    "below the R5 threshold of 0.62, so the R5 evaluator opens no trades and "
                    "run_staged_backtest.py:148 `if trades_list:` is False."
                ),
            ),
            TargetSpec(
                "backtests/results/checkpoints/resume_manifest.json", "conditional",
                hash_output=False,
                absence_cause="Written by save_daily_checkpoint only on a day rollover.",
            ),
        ),
        stale_watch_globs=("backtests/results/checkpoints/checkpoint_*.pkl",),
        catalog_probe={
            "catalog": "data/catalog/NQ_v0_2020_2026",
            "bar_types": [
                "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
            ],
            "start": "2023-02-26 00:00:00",
            "end": "2023-03-03 23:59:59",
        },
        side_effect_dirs=("backtests/results/checkpoints",),
        resolved_config_spec={
            "config_class": "strategies.score_fanning_strategy.ScoreFanningConfig",
            "provenance": "backtests/run_staged_backtest.py:68-77 (strat_cfg_dict literal)",
            "kwargs": {
                "instrument_id": "NQ.XCME",
                "bar_type_1s": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                "bar_type_1m": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                "checkpoint_dir": "backtests/results/checkpoints",
                "policies": [
                    {"name": "R5", "threshold": 0.62, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0},
                    {"name": "R2.5", "threshold": 0.50, "sl_atr_mult": 1.5, "pt_atr_mult": 2.0},
                ],
            },
        },
        fill_evidence_statement=(
            "No fills exist: ScoreFanningStrategy submits no NT orders, so the positions report "
            "is empty by construction and that emptiness is part of the baseline."
        ),
        notes=(
            "Legacy defaults: --checkpoint-dir=backtests/results/checkpoints, --resume absent.",
            "checkpoint_dir is BOTH an input location and the output location for results_*.parquet.",
            "NT positions report is expected empty; that emptiness is part of the baseline.",
        ),
    ),
    FixtureSpec(
        fixture_id="fixture_2_w4_b1",
        description=(
            "W4ExitStrategy policy B1, full-year 2023 simulated-orders run. "
            "Inherits BaselineFlipParityStrategy which submits real NT orders."
        ),
        entrypoint="backtests/run_w4_backtest.py",
        argv=("--year", "2023", "--policy", "B1", "--theta", "0.62", "--N", "10"),
        targets=(
            TargetSpec("backtests/results/w4_exit_backtests/NQ_2023_B1/trades.parquet", "produced"),
            TargetSpec(
                "backtests/results/w4_exit_backtests/NQ_2023_B1/strategy_trades.parquet",
                "conditional",
                absence_cause="run_w4_backtest.py:144 `if strategy.all_trades:` is False.",
            ),
            TargetSpec(
                "backtests/results/w4_parity_2023_B1.parquet",
                "conditional",
                absence_cause=(
                    "w4_exit_strategy.py:264 `if self.parity_logs:` is False. parity_logs gains "
                    "rows only where _pred_dict.get((direction, flip_ts, ts)) matches; this is a "
                    "property of the executed run, NOT of --year 2023."
                ),
            ),
        ),
        stale_watch_globs=("backtests/results/w4_parity_*.parquet",),
        external_inputs=(
            "studies/regime_sequence_signal_audit/results/weakness_checkpoint_predictions.parquet",
        ),
        catalog_probe={
            "catalog": "data/catalog/NQ_v0_2020_2026",
            "bar_types": [
                "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
            ],
            "start": "2022-12-27 00:00:00",
            "end": "2023-12-31 23:59:59",
        },
        side_effect_dirs=("backtests/results/w4_exit_backtests/NQ_2023_B1",),
        resolved_config_spec={
            "config_class": "strategies.w4_exit_strategy.W4ExitConfig",
            "provenance": (
                "backtests/run_w4_backtest.py:112-122 (entry_qty derived at :112, "
                "remaining inherited BaselineFlipParityConfig fields left at class defaults)"
            ),
            "kwargs": {
                "instrument_id": "NQ.XCME",
                "bar_type_1s": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                "bar_type_1m": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                "year": 2023,
                "entry_qty": 1,
                "policy": "B1",
                "theta": 0.62,
                "N": 10,
            },
        },
        fill_evidence_statement=(
            "Fills are not persisted by the legacy entrypoint; it saves only the positions report "
            "(filtered to closed) and strategy.all_trades. Per-fill evidence is therefore absent "
            "from this baseline and equivalence is asserted at position and strategy-trade level."
        ),
        notes=(
            "entry_qty is derived in the runner: 2 for policy B4, else 1.",
            "engine.run(start=2023-01-01) with NO end -> run window mode 'from_start_all_loaded'.",
            "w4_parity_{year}_{policy}.parquet is an unmanaged side-effect write outside runs/.",
        ),
    ),
)


def get_fixture(fixture_id: str) -> FixtureSpec:
    for f in FIXTURES:
        if f.fixture_id == fixture_id:
            return f
    raise KeyError(f"Unknown fixture '{fixture_id}'. Known: {[f.fixture_id for f in FIXTURES]}")


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_file(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# Third-party packages whose version changes the replayed result. Red Team W3: a
# baseline that hashes only repo-local Python is blind to an NT or pandas upgrade.
PROVENANCE_PACKAGES = ("nautilus_trader", "pandas", "pyarrow", "numpy", "msgspec")


def dependency_versions() -> Dict[str, Optional[str]]:
    """Records the installed versions of every dependency that affects the replay."""
    import importlib.metadata as md

    out: Dict[str, Optional[str]] = {"python": sys.version.split()[0]}
    for pkg in PROVENANCE_PACKAGES:
        try:
            out[pkg] = md.version(pkg)
        except Exception:  # noqa: BLE001 - absence is itself provenance
            try:
                out[pkg] = __import__(pkg).__version__
            except Exception:  # noqa: BLE001
                out[pkg] = None
    return out


# ---------------------------------------------------------------------------
# Worktree gates (plan §3B)
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    passed: bool
    blocking_reason: Optional[str]
    worktree_clean: bool
    modified_tracked: List[str] = field(default_factory=list)
    staged: List[str] = field(default_factory=list)
    untracked_py: List[str] = field(default_factory=list)
    disallowed_untracked_py: List[str] = field(default_factory=list)
    untracked_py_outside_closure: List[str] = field(default_factory=list)
    protected_path_count: int = 0
    dirty_tracked_in_closure: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "blocking_reason": self.blocking_reason,
            "worktree_clean": self.worktree_clean,
            "modified_tracked": self.modified_tracked,
            "staged": self.staged,
            "untracked_py": self.untracked_py,
            "disallowed_untracked_py": self.disallowed_untracked_py,
            "untracked_py_outside_closure": self.untracked_py_outside_closure,
            "protected_path_count": self.protected_path_count,
            "dirty_tracked_in_closure": self.dirty_tracked_in_closure,
            "gate_3_rule": (
                "An untracked .py BLOCKS only if it is inside a selected fixture's resolved "
                "repo-local import closure. Because the closure is resolved by module name "
                "against the filesystem, a file that shadows an imported module is inside the "
                "closure and is therefore caught. Untracked .py outside every closure cannot "
                "affect the run and is recorded, not blocked."
            ),
        }


def _default_git_runner(args: Sequence[str], repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout


def check_worktree_gates(
    repo_root: Path,
    protected_paths: frozenset = frozenset(),
    allowlist: frozenset = UNTRACKED_PY_ALLOWLIST,
    git_runner: Callable[[Sequence[str], Path], str] = _default_git_runner,
) -> GateResult:
    """Evaluates the three worktree gates.

    Gate 3 is *blocking* but scoped: an untracked ``.py`` only blocks if it sits
    inside a selected fixture's resolved import closure, i.e. if it can actually
    affect the run. This is stricter than a static allowlist in the case that
    matters -- a file shadowing an imported module resolves *into* the closure and
    is caught -- while not blocking on unrelated new code elsewhere in the tree.

    Gates 1 and 2 are recorded but advisory, because the capture protocol itself
    ships as tracked-file modifications.
    """
    modified = [ln for ln in git_runner(["diff", "--name-only"], repo_root).splitlines() if ln.strip()]
    staged = [
        ln for ln in git_runner(["diff", "--cached", "--name-only"], repo_root).splitlines() if ln.strip()
    ]
    untracked = [
        ln
        for ln in git_runner(["ls-files", "--others", "--exclude-standard"], repo_root).splitlines()
        if ln.strip()
    ]
    untracked_py = sorted(p for p in untracked if p.endswith(".py"))
    candidates = [p for p in untracked_py if p not in allowlist]
    disallowed = sorted(p for p in candidates if p in protected_paths)
    outside = sorted(p for p in candidates if p not in protected_paths)

    # Red Team W2: a MODIFIED or STAGED tracked file inside the closure changes what
    # the entrypoint executes just as surely as an untracked one. Treating gates 1/2
    # as purely advisory meant an "authoritative unmodified baseline run" was
    # unmodified only at the entrypoint. Closure members are now blocking; files
    # outside every closure stay advisory.
    dirty_in_closure = sorted(
        {p for p in modified if p in protected_paths} | {p for p in staged if p in protected_paths}
    )

    passed = not disallowed and not dirty_in_closure
    reason = None
    if disallowed:
        reason = (
            "UNTRACKED_PY_IN_FIXTURE_CLOSURE: "
            + ", ".join(disallowed)
            + ". These files are inside a selected fixture's import closure, so they can change "
            "what the legacy entrypoint executes. Commit, archive, or remove them before capture."
        )
    elif dirty_in_closure:
        reason = (
            "MODIFIED_TRACKED_FILE_IN_FIXTURE_CLOSURE: "
            + ", ".join(dirty_in_closure)
            + ". An authoritative baseline must be captured from an unmodified closure, not "
            "merely an unmodified entrypoint. Commit or revert these before capture."
        )

    return GateResult(
        passed=passed,
        blocking_reason=reason,
        worktree_clean=(not modified and not staged),
        modified_tracked=sorted(modified),
        staged=sorted(staged),
        untracked_py=untracked_py,
        disallowed_untracked_py=disallowed,
        untracked_py_outside_closure=outside,
        protected_path_count=len(protected_paths),
        dirty_tracked_in_closure=dirty_in_closure,
    )


# ---------------------------------------------------------------------------
# Repo-local static import closure (plan §5.1)
# ---------------------------------------------------------------------------


_DOTTED_NAME_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")


def _module_to_paths(module: str, repo_root: Path) -> List[Path]:
    """Files that Python would execute when importing ``module``.

    Importing ``a.b.c`` executes every ancestor package's ``__init__.py`` as well
    as the leaf module, so all of them belong in an execution closure.
    """
    parts = module.split(".")
    out: List[Path] = []
    # Ancestor package __init__.py files (a/__init__.py, a/b/__init__.py, ...)
    for i in range(1, len(parts)):
        out.append(repo_root.joinpath(*parts[:i]) / "__init__.py")
    # The leaf itself, as either a module or a package.
    out.append(repo_root.joinpath(*parts).with_suffix(".py"))
    out.append(repo_root.joinpath(*parts) / "__init__.py")
    return out


def _imported_modules(tree: ast.AST, resolved: Path, repo_root: Path) -> List[str]:
    """Every module name an AST refers to via import statements."""
    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                try:
                    pkg = resolved.parent.relative_to(repo_root).as_posix().replace("/", ".")
                except ValueError:
                    continue
                parts = pkg.split(".") if pkg else []
                if node.level > 1:
                    parts = parts[: -(node.level - 1)]
                base = ".".join([*parts, node.module] if node.module else parts)
            elif node.module:
                base = node.module
            else:
                continue
            modules.append(base)
            # `from pkg import mod` may name a submodule rather than an attribute.
            modules.extend(f"{base}.{a.name}" for a in node.names if a.name != "*")
    return modules


def _dynamic_module_candidates(tree: ast.AST) -> List[str]:
    """Dotted module paths that appear as string literals.

    Strategies and configs are resolved dynamically at runtime from strings —
    ``STRATEGY_REGISTRY[...]["module_path"]``, a study contract's
    ``strategy_class``, or ``importlib.import_module("...")``. A static
    import-only walk cannot see those, so any string literal shaped like a dotted
    module path is treated as a candidate and kept only if it resolves to a
    repo-local file. This is a structural rule, not a curated filename list.
    """
    out: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if _DOTTED_NAME_RE.match(value):
                out.append(value)
                # `pkg.mod.ClassName` -> also consider `pkg.mod`
                head = value.rsplit(".", 1)[0]
                if "." in head:
                    out.append(head)
    return out


def resolve_repo_local_closure_detailed(
    entrypoint: Path, repo_root: Path
) -> Dict[str, str]:
    """Transitive repo-local execution closure of ``entrypoint``, with provenance.

    Returns ``{repo_relative_posix_path: discovery_reason}``. Discovery reasons:

    * ``entrypoint``            - the fixture's own script
    * ``static_import``         - reachable by ``import`` / ``from ... import ...``
    * ``package_init``          - an ``__init__.py`` executed on the way to a module
    * ``dynamic_string_literal``- a dotted module path found as a string constant

    Only files inside ``repo_root`` are followed; stdlib and third-party imports
    are ignored.
    """
    entrypoint = entrypoint.resolve()
    repo_root = repo_root.resolve()

    seen: set = set()
    out: Dict[str, str] = {}
    stack: List[Tuple[Path, str]] = [(entrypoint, "entrypoint")]

    while stack:
        current, reason = stack.pop()
        try:
            resolved = current.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        try:
            rel = resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        seen.add(resolved)
        # Keep the strongest provenance if a file is reachable several ways.
        if rel not in out or reason == "static_import":
            out[rel] = reason

        try:
            tree = ast.parse(resolved.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        for mod in _imported_modules(tree, resolved, repo_root):
            for cand in _module_to_paths(mod, repo_root):
                if cand.is_file():
                    kind = "package_init" if cand.name == "__init__.py" else "static_import"
                    stack.append((cand, kind))

        for mod in _dynamic_module_candidates(tree):
            for cand in _module_to_paths(mod, repo_root):
                if cand.is_file():
                    kind = (
                        "package_init" if cand.name == "__init__.py" else "dynamic_string_literal"
                    )
                    stack.append((cand, kind))

    return dict(sorted(out.items()))


def resolve_repo_local_closure(entrypoint: Path, repo_root: Path) -> List[str]:
    """Sorted repo-relative paths of the execution closure (see the detailed form)."""
    return sorted(resolve_repo_local_closure_detailed(entrypoint, repo_root))


def hash_closure(paths: Sequence[str], repo_root: Path) -> Dict[str, Optional[str]]:
    return {p: sha256_file(repo_root / p) for p in sorted(paths)}


def selected_closure_paths(fixtures: Sequence[FixtureSpec], repo_root: Path) -> frozenset:
    """Union of the repo-local import closures of the selected fixtures.

    This is the set of files that can influence what the legacy entrypoints
    execute, and therefore the set gate 3 protects.
    """
    paths: set = set()
    for fx in fixtures:
        entry = repo_root / fx.entrypoint
        if entry.is_file():
            paths.update(resolve_repo_local_closure(entry, repo_root))
    return frozenset(paths)


# ---------------------------------------------------------------------------
# Normalized output identity (plan §6)
# ---------------------------------------------------------------------------


def _canonical_cell(value: Any) -> str:
    """Renders any cell value as a deterministic string.

    NT position reports contain array-valued columns (``commissions`` is a list of
    ``Money``), which are unhashable and therefore unsortable. Canonicalising every
    cell to text first makes the identity total, order-invariant, and still fully
    sensitive to value changes.
    """
    import numpy as np

    if value is None:
        return ""
    if isinstance(value, float):
        return "" if value != value else format(value, ".12g")  # NaN -> ""
    if isinstance(value, (list, tuple, np.ndarray)):
        return "[" + ",".join(_canonical_cell(v) for v in list(value)) + "]"
    if isinstance(value, (np.floating,)):
        return format(float(value), ".12g")
    return str(value)


def normalized_parquet_identity(
    path: Path, volatile_columns: frozenset = VOLATILE_COLUMNS
) -> Dict[str, Any]:
    """Computes a deterministic, volatile-free identity for a parquet artifact.

    Every cell is canonicalised to text, rows are then sorted by all retained
    columns and hashed from a canonical CSV rendering, so the identity is
    invariant to row order and file-level metadata but sensitive to any value
    change.
    """
    import pandas as pd  # local import: keeps the module importable without pandas

    path = Path(path)
    df = pd.read_parquet(path)
    dropped = sorted(c for c in df.columns if c in volatile_columns)
    kept = [c for c in df.columns if c not in volatile_columns]
    slim = df[kept].copy()

    if kept:
        obj = slim.astype(object)
        canon = obj.map(_canonical_cell) if hasattr(obj, "map") else obj.applymap(_canonical_cell)
        if not canon.empty:
            canon = canon.sort_values(by=kept, kind="mergesort").reset_index(drop=True)
    else:
        canon = slim

    canonical = canon.to_csv(index=False)
    return {
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "columns_hashed": kept,
        "columns_excluded_volatile": dropped,
        "normalized_sha256": sha256_bytes(canonical.encode("utf-8")),
        "file_sha256": sha256_file(path),
        "file_size_bytes": path.stat().st_size,
    }


def compare_normalized(
    reference: Dict[str, Any],
    candidate: Dict[str, Any],
    float_rtol: float = 1e-9,
) -> Dict[str, Any]:
    """Compares two normalized identities under the plan's tolerance rules.

    Structural fields (row count, column set, normalized hash) must match
    exactly. ``float_rtol`` is carried for aggregate metric comparison performed
    by the caller; it is deliberately *not* applied to row-level values, because
    prices are tick-quantised and a deviation there is a behavioural change.
    """
    diffs: List[str] = []
    if reference.get("row_count") != candidate.get("row_count"):
        diffs.append(f"row_count {reference.get('row_count')} != {candidate.get('row_count')}")
    if reference.get("columns_hashed") != candidate.get("columns_hashed"):
        diffs.append("column set/order differs")
    if reference.get("normalized_sha256") != candidate.get("normalized_sha256"):
        diffs.append("normalized content hash differs")
    return {
        "equivalent": not diffs,
        "differences": diffs,
        "float_rtol": float_rtol,
    }


# ---------------------------------------------------------------------------
# Target lifecycle (plan §2)
# ---------------------------------------------------------------------------


@dataclass
class TargetState:
    spec: TargetSpec
    abs_path: Path
    preexisting: bool
    pre_sha256: Optional[str]
    pre_size: Optional[int]
    pre_mtime: Optional[float] = None
    post_mtime: Optional[float] = None
    quarantined: bool = False
    quarantine_path: Optional[Path] = None
    preserved_path: Optional[Path] = None
    preserved_abs: Optional[Path] = None
    post_exists: bool = False
    post_sha256: Optional[str] = None
    status: Optional[str] = None
    evidence_path: Optional[Path] = None
    identity: Optional[Dict[str, Any]] = None
    restored: Optional[bool] = None
    restore_verified_sha256: Optional[str] = None
    attribution_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_path": self.spec.path,
            "expectation": self.spec.expectation,
            "status": self.status,
            "preexisting_before_run": self.preexisting,
            "pre_sha256": self.pre_sha256,
            "pre_size_bytes": self.pre_size,
            "quarantined_to_prove_absence": self.quarantined,
            "preserved_to": self.preserved_path.as_posix() if self.preserved_path else None,
            "post_run_exists": self.post_exists,
            "post_sha256": self.post_sha256,
            "evidence_copy": self.evidence_path.as_posix() if self.evidence_path else None,
            "normalized_identity": self.identity,
            "absence_cause": self.spec.absence_cause if not self.post_exists else None,
            "attribution_note": self.attribution_note,
            "restored_to_original_state": self.restored,
            "restore_verified_sha256": self.restore_verified_sha256,
        }


def classify_target(
    preexisting: bool,
    quarantined: bool,
    post_exists: bool,
    pre_sha256: Optional[str],
    post_sha256: Optional[str],
    pre_mtime: Optional[float] = None,
    post_mtime: Optional[float] = None,
) -> Tuple[str, Optional[str]]:
    """Pure classification of a single target into one of the four statuses.

    ``quarantined`` means the pre-existing file was moved aside before execution,
    so the target path was demonstrably clean when the run started.

    Attribution for a non-quarantined pre-existing path follows the plan's §1
    definition of ``produced_by_current_run`` -- "verifiable by file creation/
    modification timestamp **and** post-run hash comparison". A file that the run
    never touched is therefore neither produced nor provably absent.
    """
    path_was_clean = (not preexisting) or quarantined

    if post_exists:
        if path_was_clean:
            return STATUS_PRODUCED, None
        if pre_sha256 is not None and post_sha256 != pre_sha256:
            return STATUS_PRODUCED, "Overwrote a pre-existing file; original preserved and restored."
        # Red Team M2: modification time alone is NOT evidence of production. An
        # mtime can advance without a write, and a byte-identical file at an
        # unquarantined path is indistinguishable from a stale one. Attribution
        # requires either a content change or a demonstrably clean start.
        return (
            STATUS_ABSENT_UNVERIFIED,
            "Pre-existing file is byte-identical after the run and the target was not "
            "quarantined; production cannot be established. Modification time is not accepted "
            "as evidence of production.",
        )

    # Not present after the run.
    if path_was_clean:
        return STATUS_ABSENT_VERIFIED, None
    return STATUS_ABSENT_UNVERIFIED, None


def snapshot_targets(fixture: FixtureSpec, repo_root: Path) -> List[TargetState]:
    states: List[TargetState] = []
    for spec in fixture.targets:
        p = repo_root / spec.path
        exists = p.is_file()
        states.append(
            TargetState(
                spec=spec,
                abs_path=p,
                preexisting=exists,
                pre_sha256=sha256_file(p) if exists else None,
                pre_size=p.stat().st_size if exists else None,
                pre_mtime=p.stat().st_mtime if exists else None,
            )
        )
    return states


def scan_stale_unmanaged(
    fixture: FixtureSpec, repo_root: Path
) -> List[Dict[str, Any]]:
    """Finds files at target-shaped paths that this run configuration cannot produce."""
    declared = {(repo_root / t.path).resolve() for t in fixture.targets}
    found: List[Dict[str, Any]] = []
    for pattern in fixture.stale_watch_globs:
        for match in sorted(repo_root.glob(pattern)):
            if match.resolve() in declared or not match.is_file():
                continue
            found.append(
                {
                    "path": match.relative_to(repo_root).as_posix(),
                    "status": STATUS_STALE_UNMANAGED,
                    "sha256": sha256_file(match),
                    "size_bytes": match.stat().st_size,
                    "note": "Not produced by this run configuration. Preserved in place; never attributed.",
                }
            )
    return found


# ---------------------------------------------------------------------------
# Catalog / external input probes
# ---------------------------------------------------------------------------


def probe_catalog_bounds(probe: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    """Runs the catalog bounds probe in a child process to bound parent memory."""
    payload = json.dumps(probe)
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--internal-catalog-probe", payload],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"status": "probe_failed", "returncode": proc.returncode, "stderr": proc.stderr[-4000:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as err:
        return {"status": "probe_unparseable", "error": str(err), "stdout": proc.stdout[-4000:]}


def _run_catalog_probe(probe: Dict[str, Any]) -> Dict[str, Any]:
    import pandas as pd
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    catalog = ParquetDataCatalog(probe["catalog"])
    start = pd.Timestamp(probe["start"], tz="UTC")
    end = pd.Timestamp(probe["end"], tz="UTC")

    out: Dict[str, Any] = {
        "status": "ok",
        "catalog_path": probe["catalog"],
        "window_start": str(start),
        "window_end": str(end),
        "bar_types": {},
    }
    for bt in probe["bar_types"]:
        bars = catalog.bars(bar_types=[bt], start=start, end=end)
        if bars:
            out["bar_types"][bt] = {
                "row_count": len(bars),
                "first_ts_event": int(bars[0].ts_event),
                "last_ts_event": int(bars[-1].ts_event),
                "first_ts_init": int(bars[0].ts_init),
                "last_ts_init": int(bars[-1].ts_init),
            }
        else:
            out["bar_types"][bt] = {"row_count": 0}
        del bars

    # Red Team W3: row counts and ts bounds do not detect a changed bar VALUE inside
    # the window. Hash the content of every catalog parquet partition that could
    # supply data to this fixture.
    out["partitions"] = _hash_catalog_partitions(Path(probe["catalog"]), start, end)
    return out


_PARTITION_TS_RE = re.compile(r"(\d{16,19})")


def _partition_intersects_window(path: Path, start_ns: int, end_ns: int) -> bool:
    """True when a partition filename's embedded ts range overlaps the window.

    NT names bar partitions with epoch-nanosecond bounds. When a filename carries
    no parseable range we keep the partition: over-inclusion is the safe direction
    for provenance.
    """
    stamps = [int(s) for s in _PARTITION_TS_RE.findall(path.stem)]
    if len(stamps) < 2:
        return True
    lo, hi = min(stamps), max(stamps)
    return not (hi < start_ns or lo > end_ns)


def _hash_catalog_partitions(catalog: Path, start, end) -> Dict[str, Any]:
    start_ns, end_ns = int(start.value), int(end.value)
    entries: List[Dict[str, Any]] = []
    if not catalog.is_dir():
        return {"status": "catalog_not_found", "path": str(catalog), "files": []}

    for parquet in sorted(catalog.rglob("*.parquet")):
        if not _partition_intersects_window(parquet, start_ns, end_ns):
            continue
        entries.append({
            "path": parquet.relative_to(catalog).as_posix(),
            "sha256": sha256_file(parquet),
            "size_bytes": parquet.stat().st_size,
        })

    composite = hashlib.sha256(
        json.dumps([(e["path"], e["sha256"]) for e in entries], sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ok",
        "file_count": len(entries),
        "composite_sha256": composite,
        "selection_rule": (
            "every *.parquet under the catalog whose filename ts range intersects the load "
            "window; partitions with no parseable range are included"
        ),
        "files": entries,
    }


def probe_external_input(rel_path: str, repo_root: Path) -> Dict[str, Any]:
    p = repo_root / rel_path
    info: Dict[str, Any] = {"path": rel_path, "exists": p.is_file()}
    if not p.is_file():
        return info
    info["sha256"] = sha256_file(p)
    info["size_bytes"] = p.stat().st_size
    if rel_path.endswith("weakness_checkpoint_predictions.parquet"):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--internal-predictions-probe", rel_path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            try:
                info.update(json.loads(proc.stdout.strip().splitlines()[-1]))
            except (ValueError, IndexError):
                info["row_count_probe"] = "unparseable"
        else:
            info["row_count_probe"] = "failed"
    return info


def _run_predictions_probe(rel_path: str) -> Dict[str, Any]:
    import pandas as pd

    df = pd.read_parquet(rel_path, columns=["observation_time"])
    dt = pd.to_datetime(df["observation_time"], unit="ns", utc=True)
    return {
        "total_row_count": int(len(df)),
        "row_count_year_2023": int((dt.dt.year == 2023).sum()),
    }


# ---------------------------------------------------------------------------
# Warmup evidence
# ---------------------------------------------------------------------------


def parse_loaded_bar_counts(stdout: str) -> Dict[str, Any]:
    """Extracts bar-load counts the legacy runners print deterministically."""
    import re

    counts: Dict[str, Any] = {}
    m = re.search(r"Loaded ([\d,]+) 1s bars and ([\d,]+) 1m bars", stdout)
    if m:
        counts["1s"] = int(m.group(1).replace(",", ""))
        counts["1m"] = int(m.group(2).replace(",", ""))
    for tf in ("1s", "1m"):
        m2 = re.search(rf"Loaded ([\d,]+) {tf} bars \(", stdout)
        if m2:
            counts[tf] = int(m2.group(1).replace(",", ""))
    return counts


def snapshot_resolved_config(fixture: FixtureSpec, repo_root: Path) -> Dict[str, Any]:
    """Captures the fully resolved StrategyConfig the legacy entrypoint constructs.

    Phase 1 forbids instrumenting the run, so the config is reconstructed from the
    entrypoint's source (the literal kwargs it passes) and then *materialised* by
    instantiating the real config class, which fills in every inherited default.
    That distinction is recorded: values are observed from the config class, while
    the kwargs are declared by the entrypoint.
    """
    spec = fixture.resolved_config_spec
    if not spec:
        return {"status": "not_declared"}

    out: Dict[str, Any] = {
        "status": "unknown",
        "config_class": spec["config_class"],
        "entrypoint_kwargs": spec["kwargs"],
        "kwargs_provenance": spec.get("provenance"),
    }
    module_path, _, cls_name = spec["config_class"].rpartition(".")
    try:
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, cls_name)
        instance = cls(**spec["kwargs"])
        fields = getattr(cls, "__struct_fields__", None) or list(
            getattr(cls, "__annotations__", {})
        )
        out["resolved_fields"] = {f: _jsonable(getattr(instance, f, None)) for f in fields}
        out["resolved_field_count"] = len(out["resolved_fields"])
        out["status"] = "observed_from_config_class"
    except Exception as err:  # noqa: BLE001 - recorded, never fatal
        out["status"] = "unavailable_config_class_unimportable"
        out["error"] = f"{type(err).__name__}: {err}"
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def build_fill_evidence(fixture: FixtureSpec) -> Dict[str, Any]:
    """Records fill-level evidence, or an explicit statement that none exists."""
    return {
        "fill_artifact_present": False,
        "statement": fixture.fill_evidence_statement,
        "rationale": (
            "The legacy entrypoint does not call generate_order_fills_report() and does not "
            "persist fills. Producing one would require instrumenting the run, which Phase 1 "
            "forbids. Absence of a fill artifact is therefore stated explicitly rather than "
            "left as a silent gap."
        ),
    }


def build_warmup_evidence(fixture: FixtureSpec, stdout: str, repo_root: Path) -> Dict[str, Any]:
    """Records loaded-bar counts separately from *dispatched* callbacks (plan §5.5).

    Callback dispatch cannot be observed without instrumenting the legacy script,
    which Phase 1 forbids, so it is reported as ``unavailable_uninstrumented``
    with any derived, non-invasive evidence recorded alongside it.
    """
    evidence: Dict[str, Any] = {
        "bars_loaded_by_timeframe": parse_loaded_bar_counts(stdout),
        "bar_callbacks_dispatched": "unavailable_uninstrumented",
        "rationale": (
            "Phase 1 executes the legacy entrypoint verbatim; observing per-bar callbacks would "
            "require instrumenting it, which would invalidate the authoritative run."
        ),
        "derived_observations": [],
    }

    if fixture.fixture_id == "fixture_1_score_fanning":
        ckpt_dir = repo_root / "backtests/results/checkpoints"
        pkls = sorted(p.name for p in ckpt_dir.glob("checkpoint_*.pkl")) if ckpt_dir.is_dir() else []
        evidence["derived_observations"].append(
            {
                "observation": "daily_checkpoint_files_present",
                "value": pkls,
                "interpretation": (
                    "ScoreFanningStrategy.save_daily_checkpoint fires on a ts_event day rollover. "
                    "A checkpoint for the day before --start-date indicates at least one pre-start "
                    "bar was dispatched by ts_event labelling (bars are OPEN-stamped, ts_init=close), "
                    "and is NOT by itself proof that the full 5-day lead-in was replayed."
                ),
            }
        )
    return evidence


# ---------------------------------------------------------------------------
# Capture orchestration
# ---------------------------------------------------------------------------


def _default_subprocess_runner(cmd: Sequence[str], cwd: Path) -> Dict[str, Any]:
    started = utcnow_iso()
    proc = subprocess.run(list(cmd), cwd=str(cwd), capture_output=True, text=True, check=False)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "started_utc": started,
        "finished_utc": utcnow_iso(),
    }


def capture_fixture(
    fixture: FixtureSpec,
    capture_dir: Path,
    repo_root: Path = REPO_ROOT,
    runner: Callable[[Sequence[str], Path], Dict[str, Any]] = _default_subprocess_runner,
    collect_catalog_bounds: bool = True,
) -> Dict[str, Any]:
    """Executes one fixture end-to-end and returns its manifest section."""
    fx_dir = capture_dir / fixture.fixture_id
    fx_dir.mkdir(parents=True, exist_ok=True)
    preserved_dir = capture_dir / "preserved_preexisting" / fixture.fixture_id
    preserved_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = capture_dir / "_quarantine" / fixture.fixture_id
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    entry_path = repo_root / fixture.entrypoint
    if not entry_path.is_file():
        return {
            "fixture_id": fixture.fixture_id,
            "status": "BLOCKED_ENTRYPOINT_MISSING",
            "entrypoint": fixture.entrypoint,
        }

    # --- 1. Source identity BEFORE ------------------------------------------
    closure_detail = resolve_repo_local_closure_detailed(entry_path, repo_root)
    closure = sorted(closure_detail)
    closure_before = hash_closure(closure, repo_root)

    # --- 2. Inputs -----------------------------------------------------------
    external = [probe_external_input(p, repo_root) for p in fixture.external_inputs]
    catalog_bounds: Dict[str, Any] = {"status": "not_collected"}
    if collect_catalog_bounds and fixture.catalog_probe:
        catalog_bounds = probe_catalog_bounds(fixture.catalog_probe, repo_root)

    # --- 3. Preserve / quarantine targets -----------------------------------
    states = snapshot_targets(fixture, repo_root)
    stale = scan_stale_unmanaged(fixture, repo_root)

    for st in states:
        if not st.preexisting:
            continue
        preserved = preserved_dir / st.abs_path.name
        shutil.copy2(st.abs_path, preserved)
        st.preserved_path = preserved.relative_to(capture_dir)
        st.preserved_abs = preserved
        if st.spec.quarantine_required:
            q = quarantine_dir / st.abs_path.name
            shutil.move(str(st.abs_path), str(q))
            st.quarantined = True
            st.quarantine_path = q

    side_effect_before = _snapshot_dirs(fixture, repo_root)

    # --- 4. Authoritative run (verbatim, unmodified) ------------------------
    result = runner(fixture.command, repo_root)

    (fx_dir / "stdout.log").write_text(result.get("stdout", ""), encoding="utf-8", errors="replace")
    (fx_dir / "stderr.log").write_text(result.get("stderr", ""), encoding="utf-8", errors="replace")

    run_ok = result.get("returncode") == 0

    # --- 5. Source identity AFTER -------------------------------------------
    closure_after = hash_closure(closure, repo_root)
    source_stable = closure_before == closure_after
    drifted = sorted(k for k in closure_before if closure_before[k] != closure_after.get(k))

    # --- 6. Classify, copy evidence, restore --------------------------------
    for st in states:
        st.post_exists = st.abs_path.is_file()
        st.post_sha256 = sha256_file(st.abs_path) if st.post_exists else None
        st.post_mtime = st.abs_path.stat().st_mtime if st.post_exists else None
        st.status, st.attribution_note = classify_target(
            preexisting=st.preexisting,
            quarantined=st.quarantined,
            post_exists=st.post_exists,
            pre_sha256=st.pre_sha256,
            post_sha256=st.post_sha256,
            pre_mtime=st.pre_mtime,
            post_mtime=st.post_mtime,
        )
        assert st.status in VALID_STATUSES, f"invalid status {st.status}"

        if st.post_exists:
            evidence = fx_dir / st.abs_path.name
            shutil.copy2(st.abs_path, evidence)
            st.evidence_path = evidence.relative_to(capture_dir)
            if st.spec.hash_output and st.abs_path.suffix == ".parquet":
                try:
                    st.identity = normalized_parquet_identity(evidence)
                except Exception as err:  # noqa: BLE001 - recorded, never fatal
                    st.identity = {"error": f"{type(err).__name__}: {err}"}

        _restore_target(st)

    # --- 7. Side-effect delta ------------------------------------------------
    side_effect_after = _snapshot_dirs(fixture, repo_root)
    undeclared = _diff_dirs(side_effect_before, side_effect_after)

    warmup = build_warmup_evidence(fixture, result.get("stdout", ""), repo_root)
    resolved_config = snapshot_resolved_config(fixture, repo_root)
    _write_json_file(fx_dir / "resolved_config.json", resolved_config)
    _write_json_file(fx_dir / "catalog_bounds.json", catalog_bounds)

    _cleanup_quarantine(quarantine_dir)

    # Red Team M1: a declared `produced` target that was not actually produced by
    # this run invalidates the fixture. Previously the fixture reported SUCCESS and
    # baseline_valid while a stale file's identity was published as the reference.
    unproduced = [
        s.spec.path for s in states
        if s.spec.expectation == "produced" and s.status != STATUS_PRODUCED
    ]

    status = "SUCCESS" if run_ok and source_stable else "FAILED_UNMODIFIED"
    if run_ok and not source_stable:
        status = "INVALIDATED_SOURCE_CHANGED_DURING_RUN"
    if status == "SUCCESS" and unproduced:
        status = "FAILED_REQUIRED_TARGET_NOT_PRODUCED"

    section = {
        "fixture_id": fixture.fixture_id,
        "description": fixture.description,
        "status": status,
        # A per-fixture flag: one fixture failing unmodified must not strip another
        # fixture of its independently valid baseline.
        "baseline_valid": status == "SUCCESS",
        "command": fixture.command,
        "command_display": " ".join([Path(fixture.command[0]).name, *fixture.command[1:]]),
        "returncode": result.get("returncode"),
        "started_utc": result.get("started_utc"),
        "finished_utc": result.get("finished_utc"),
        "entrypoint": fixture.entrypoint,
        "source_closure": {
            "file_count": len(closure),
            "stable_across_run": source_stable,
            "drifted_files": drifted,
            "discovery": closure_detail,
            "discovery_counts": {
                kind: sum(1 for v in closure_detail.values() if v == kind)
                for kind in sorted(set(closure_detail.values()))
            },
            "resolver": (
                "AST transitive walk over repo-local imports, including ancestor package "
                "__init__.py files and dotted module paths appearing as string literals "
                "(dynamic strategy/config resolution). Not a curated filename list."
            ),
            "hashes_before": closure_before,
            "hashes_after": closure_after,
        },
        "external_inputs": external,
        "catalog_bounds": catalog_bounds,
        "resolved_config": resolved_config,
        "fill_evidence": build_fill_evidence(fixture),
        "warmup_evidence": warmup,
        "required_targets_not_produced": unproduced,
        "targets": [s.to_dict() for s in states],
        "preexisting_stale_unmanaged": stale,
        "undeclared_side_effects": undeclared,
        "notes": list(fixture.notes),
    }
    (fx_dir / "status.json").write_text(json.dumps(section, indent=2), encoding="utf-8")
    return section


def _restore_target(st: TargetState) -> None:
    """Returns the working tree to exactly the state found before the run."""
    if st.preexisting:
        if st.quarantined and st.quarantine_path is not None:
            if st.abs_path.is_file():
                st.abs_path.unlink()
            shutil.move(str(st.quarantine_path), str(st.abs_path))
        elif st.post_exists and st.post_sha256 != st.pre_sha256:
            # Overwritten by the run: restore the preserved original bytes.
            if st.preserved_abs is not None and st.preserved_abs.is_file():
                shutil.copy2(st.preserved_abs, st.abs_path)
        st.restore_verified_sha256 = sha256_file(st.abs_path)
        st.restored = st.restore_verified_sha256 == st.pre_sha256
    else:
        # Absent before the run: evidence is already copied, so remove the new file.
        if st.post_exists and st.abs_path.is_file():
            st.abs_path.unlink()
        st.restored = not st.abs_path.exists()
        st.restore_verified_sha256 = None


def _snapshot_dirs(fixture: FixtureSpec, repo_root: Path) -> Dict[str, Dict[str, float]]:
    snap: Dict[str, Dict[str, float]] = {}
    for rel in fixture.side_effect_dirs:
        d = repo_root / rel
        entry: Dict[str, float] = {}
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file():
                    entry[p.relative_to(repo_root).as_posix()] = p.stat().st_mtime
        snap[rel] = entry
    return snap


def _diff_dirs(
    before: Dict[str, Dict[str, float]], after: Dict[str, Dict[str, float]]
) -> Dict[str, Any]:
    created: List[str] = []
    modified: List[str] = []
    for rel, post in after.items():
        pre = before.get(rel, {})
        for path, mtime in post.items():
            if path not in pre:
                created.append(path)
            elif pre[path] != mtime:
                modified.append(path)
    return {
        "created": sorted(created),
        "modified": sorted(modified),
        "note": (
            "Undeclared side effects (NT logs, daily checkpoints) are recorded for provenance "
            "and intentionally left in place; they are not attributed as fixture outputs."
        ),
    }


def _cleanup_quarantine(quarantine_dir: Path) -> None:
    try:
        if quarantine_dir.is_dir() and not any(quarantine_dir.iterdir()):
            quarantine_dir.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def build_dry_run_plan(fixture: FixtureSpec, repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    entry = repo_root / fixture.entrypoint
    closure = resolve_repo_local_closure(entry, repo_root) if entry.is_file() else []
    states = snapshot_targets(fixture, repo_root)
    return {
        "fixture_id": fixture.fixture_id,
        "entrypoint": fixture.entrypoint,
        "entrypoint_exists": entry.is_file(),
        "command_display": " ".join([Path(fixture.command[0]).name, *fixture.command[1:]]),
        "source_closure_file_count": len(closure),
        "external_inputs": [
            {"path": p, "exists": (repo_root / p).is_file()} for p in fixture.external_inputs
        ],
        "catalog_probe": fixture.catalog_probe,
        "planned_target_actions": [
            {
                "target_path": s.spec.path,
                "expectation": s.spec.expectation,
                "preexisting": s.preexisting,
                "action": (
                    "quarantine -> run -> restore"
                    if s.preexisting and s.spec.quarantine_required
                    else "preserve copy -> run -> restore"
                    if s.preexisting
                    else "run -> copy to evidence -> remove new file"
                ),
                "provable_absence": (not s.preexisting) or s.spec.quarantine_required,
            }
            for s in states
        ],
        "stale_watch_matches": scan_stale_unmanaged(fixture, repo_root),
        "notes": list(fixture.notes),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Capture immutable baseline fixtures from legacy runners.")
    ap.add_argument("--fixture", action="append", choices=[f.fixture_id for f in FIXTURES],
                    help="Fixture id (repeatable). Default: all fixtures.")
    ap.add_argument("--dry-run", action="store_true", help="Print the resolved plan; execute nothing.")
    ap.add_argument("--skip-catalog-bounds", action="store_true",
                    help="Skip the catalog bounds probe (faster; manifest records not_collected).")
    ap.add_argument("--output-root", default="backtests/fixtures",
                    help="Root directory for capture evidence.")
    ap.add_argument("--force", action="store_true",
                    help="Proceed even if a blocking worktree gate fails (recorded in the manifest).")
    ap.add_argument("--internal-catalog-probe", help=argparse.SUPPRESS)
    ap.add_argument("--internal-predictions-probe", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.internal_catalog_probe:
        print(json.dumps(_run_catalog_probe(json.loads(args.internal_catalog_probe))))
        return 0
    if args.internal_predictions_probe:
        print(json.dumps(_run_predictions_probe(args.internal_predictions_probe)))
        return 0

    selected = [get_fixture(f) for f in (args.fixture or [f.fixture_id for f in FIXTURES])]
    protected = selected_closure_paths(selected, REPO_ROOT)

    if args.dry_run:
        plan = {
            "mode": "dry_run",
            "generated_utc": utcnow_iso(),
            "worktree_gates": check_worktree_gates(REPO_ROOT, protected_paths=protected).to_dict(),
            "capture_script_sha256": sha256_file(Path(__file__).resolve()),
            "fixtures": [build_dry_run_plan(f) for f in selected],
        }
        print(json.dumps(plan, indent=2))
        return 0

    gates = check_worktree_gates(REPO_ROOT, protected_paths=protected)
    if not gates.passed and not args.force:
        print(f"BLOCKED: {gates.blocking_reason}", file=sys.stderr)
        return 2

    script_path = Path(__file__).resolve()
    script_sha_before = sha256_file(script_path)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    capture_dir = REPO_ROOT / args.output_root / f"baseline_capture_{stamp}"
    capture_dir.mkdir(parents=True, exist_ok=True)

    git_commit = _default_git_runner(["rev-parse", "HEAD"], REPO_ROOT).strip()

    sections = []
    for fx in selected:
        print(f"[capture] {fx.fixture_id}: {' '.join(fx.command[1:])}", flush=True)
        sections.append(
            capture_fixture(
                fx,
                capture_dir,
                repo_root=REPO_ROOT,
                collect_catalog_bounds=not args.skip_catalog_bounds,
            )
        )

    script_sha_after = sha256_file(script_path)

    script_stable = script_sha_before == script_sha_after
    env_ok = script_stable and gates.passed

    successes = [s for s in sections if s.get("status") == "SUCCESS"]
    failures = [s for s in sections if s.get("status") != "SUCCESS"]

    # A capture-wide environment problem (script mutated mid-run, blocking gate)
    # invalidates everything. Otherwise each fixture stands on its own evidence.
    if not env_ok:
        for s in sections:
            s["baseline_valid"] = False
        overall = "INVALIDATED"
    elif not successes:
        overall = "INVALIDATED"
    elif failures:
        overall = "PARTIALLY_VALID"
    else:
        overall = "VALID"

    manifest = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "status": overall,
        "status_semantics": {
            "VALID": "every selected fixture produced a usable baseline",
            "PARTIALLY_VALID": "at least one fixture produced a usable baseline and at least one "
                               "failed unmodified; use per-fixture 'baseline_valid'",
            "INVALIDATED": "no usable baseline, or a capture-wide integrity problem",
        },
        "capture_timestamp_utc": stamp,
        "generated_utc": utcnow_iso(),
        "git_commit": git_commit,
        "repo_path": str(REPO_ROOT),
        "evidence_directory": capture_dir.relative_to(REPO_ROOT).as_posix(),
        "capture_script": {
            "path": script_path.relative_to(REPO_ROOT).as_posix(),
            "sha256_before": script_sha_before,
            "sha256_after": script_sha_after,
            "stable": script_stable,
        },
        "worktree_gates": gates.to_dict(),
        "python": {"executable": sys.executable, "version": sys.version},
        "dependency_versions": dependency_versions(),
        "comparison_rules": {
            "exact_match_required": [
                "row counts", "event timestamps", "order sides", "quantities",
                "tick-quantised prices", "exit reason strings",
            ],
            "float_relative_tolerance": 1e-9,
            "volatile_columns_excluded": sorted(VOLATILE_COLUMNS),
        },
        "module_trace": {
            "collected": False,
            "policy": "DIAGNOSTIC_ONLY - supplemental evidence, never a replacement for the "
                      "authoritative Phase 1 CLI run.",
        },
        "fixtures": sections,
    }
    if overall != "VALID":
        manifest["reason"] = _invalidation_reason(sections, script_stable, gates)

    (capture_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    pointer = {
        "status": overall,
        "latest_capture_timestamp": stamp,
        "latest_capture_dir": capture_dir.relative_to(REPO_ROOT).as_posix(),
        "latest_manifest": (capture_dir / "manifest.json").relative_to(REPO_ROOT).as_posix(),
        "git_commit": git_commit,
        "fixture_status": {s["fixture_id"]: s.get("status") for s in sections},
        "baseline_valid": {s["fixture_id"]: s.get("baseline_valid", False) for s in sections},
    }
    if overall != "VALID":
        pointer["reason"] = manifest["reason"]
    (REPO_ROOT / args.output_root / "baseline_fixtures.json").write_text(
        json.dumps(pointer, indent=2), encoding="utf-8"
    )

    print(json.dumps(pointer, indent=2))
    return {"VALID": 0, "PARTIALLY_VALID": 1}.get(overall, 2)


def produced_reference_identities(section: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Golden-reference identities, restricted to genuinely produced artifacts.

    Red Team M1: a stale pre-existing file's normalized identity was published as
    the reference and fed straight into golden equivalence. Only a target with
    ``status == produced_by_current_run`` may serve as a reference.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for target in section.get("targets", []):
        if target.get("status") != STATUS_PRODUCED:
            continue
        identity = target.get("normalized_identity") or {}
        if "normalized_sha256" not in identity:
            continue
        out[Path(target["target_path"]).name] = target
    return out


def find_latest_baseline(
    fixture_id: str, fixtures_root: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Returns the newest capture section for ``fixture_id`` whose baseline is valid.

    Equivalence tests use this so they fail loudly (skip/xfail) when no trustworthy
    baseline exists, rather than silently comparing against invalidated evidence.
    """
    root = fixtures_root or (REPO_ROOT / "backtests" / "fixtures")
    if not root.is_dir():
        return None
    for cap in sorted(root.glob("baseline_capture_*"), reverse=True):
        manifest = cap / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError:
            continue
        sections = data.get("fixtures")
        if not isinstance(sections, list):
            # Foreign/legacy manifest schema (the 2026-08-15 captures stored
            # `fixtures` as a mapping). Never interpret it as a baseline.
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get("fixture_id") == fixture_id and section.get("baseline_valid"):
                section = dict(section)
                section["_capture_dir"] = cap.as_posix()
                section["_manifest"] = manifest.as_posix()
                return section
    return None


def _invalidation_reason(sections, script_stable: bool, gates: GateResult) -> str:
    reasons = []
    if not gates.passed:
        reasons.append(f"worktree gate: {gates.blocking_reason}")
    if not script_stable:
        reasons.append("capture script changed during execution")
    for s in sections:
        if s.get("status") != "SUCCESS":
            reasons.append(f"{s.get('fixture_id')}: {s.get('status')}")
    return "; ".join(reasons) or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
