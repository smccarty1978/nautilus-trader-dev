"""Replay-closure identity: the partition-reuse key (W2-prime, chore/collection_latency).

A collected partition is a deterministic function of exactly four things:

    replay_closure_sha256 = H( compiled-plan collection-stage closure composite
                             + the replay-affecting subset of the compiled plan
                             + dataset identity (id + logical digest)
                             + partition interval (period / year / primary / run_end / warmup / windows)
                             + experiment authorization identity )

This module DERIVES that key from the compiled plan; nothing here is an enumerated file list.
The collection-stage closure is ``CompiledPlan.closure.stages.collection`` -- the bound host,
provider and tracker modules plus everything they import from the repository, as resolved by
``research_workflow.grammar.compiler._resolve_closure`` -- and it is always a subset of the
90-file frozen execution manifest.  The seal, the manifest and every audit are untouched: the key
is a *second, narrower* identity used only to decide whether an existing partition may be served
instead of re-replayed, and ``V2Lifecycle.reconcile`` re-attests every reuse from the artifact.

Fail-closed rules:

* anything not provably outside the replay path stays inside the key (the plan subset below
  excludes only declarations consumed strictly after collection);
* a module imported during the smoke replay that is NOT in the collection-stage closure is a
  hard failure (``ReplayClosureEscape``), never an automatic widening;
* a partition whose manifest carries no binding, or whose recorded components do not re-hash to
  the recorded key, or whose parquet bytes do not match the manifest, is never reused.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from research_workflow.grammar.plan import canonical_json

# Compiled-plan keys that are consumed strictly AFTER collection (analysis, model fitting) or that
# are identities of the plan/spec themselves. Everything else in the plan is replay-affecting and
# stays in the key. ``study`` carries only id/question/description; ``notes`` is free text. A change
# to any excluded key is proven output-neutral by research_workflow/tests/test_replay_closure.py.
REPLAY_PLAN_EXCLUDED_KEYS: Tuple[str, ...] = ("analysis", "model", "notes", "study", "plan_sha256", "spec_sha256", "closure")
# chronology.partition_reuse is the reuse *policy*; it never changes what a replay emits.
REPLAY_CHRONOLOGY_EXCLUDED_KEYS: Tuple[str, ...] = ("partition_reuse",)

REPLAY_CLOSURE_SCHEMA_VERSION = 1
REUSE_MODE_OFF = "off"
REUSE_MODE_REPLAY_CLOSURE = "replay_closure"
SHADOW_EVERY_RUN = "every_run"
SHADOW_SAMPLED = "sampled"
SHADOW_SAMPLED_ONE_IN = 4
# Proposed bake-in: every reuse run recomputes one partition until this many consecutive studies
# have cleared shadow verification; only then may a study declare ``partition_reuse_shadow: sampled``.
SHADOW_BAKE_IN_CLEAN_STUDIES = 5


class ReplayClosureError(RuntimeError):
    """A partition-reuse binding could not be derived or verified."""


class ReplayClosureEscape(ReplayClosureError):
    """A module was imported during the replay that is not in the collection-stage closure."""


# -- key derivation ---------------------------------------------------------------------------------
def collection_closure(plan: Mapping[str, Any]) -> Dict[str, Any]:
    """The module set the reuse key binds: the compiler's ``replay`` stage (seeded at the host and the
    bound provider/tracker modules, stopping before the compiler -- Reading 2), falling back to the
    ``collection`` stage for plans compiled before the replay stage existed (strictly larger: fail-closed)."""
    stages = ((plan.get("closure") or {}).get("stages") or {})
    for stage in ("replay", "collection"):
        col = stages.get(stage) or {}
        if col.get("composite_sha256") and col.get("files"):
            return {"composite_sha256": col["composite_sha256"], "files": list(col["files"]), "stage": stage,
                    "hash_algorithm": (plan.get("closure") or {}).get("hash_algorithm")}
    raise ReplayClosureError("REPLAY_CLOSURE_UNDERIVABLE: compiled plan carries no replay/collection-stage closure")


def merge_trace_union(path: Path, entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist one traced run (smoke or partition) into the study's cumulative trace artifact and
    return the updated document: ``runs`` (every recorded run), ``union`` (every repo file ever traced
    on this study's replay path) and the latest run's summary fields at the top level."""
    doc: Dict[str, Any] = {}
    if Path(path).is_file():
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            doc = {}
    runs = list(doc.get("runs") or [])
    runs.append(dict(entry))
    union = sorted(set(doc.get("union") or []) | set(entry.get("traced_repo_files") or []))
    doc = {**{k: v for k, v in doc.items() if k not in ("runs", "union")}, **dict(entry), "runs": runs, "union": union,
           "policy": "every smoke and every partition run traces its imports; a repo file first imported during the replay "
                     "that is outside the plan's replay-stage closure halts the run (REPLAY_CLOSURE_ESCAPE); the key is never widened by a trace"}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    return doc


def replay_plan_subset(plan: Mapping[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in plan.items() if k not in REPLAY_PLAN_EXCLUDED_KEYS}
    ch = dict(out.get("chronology") or {})
    for k in REPLAY_CHRONOLOGY_EXCLUDED_KEYS:
        ch.pop(k, None)
    out["chronology"] = ch
    return out


def replay_plan_sha256(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(replay_plan_subset(plan)).encode("utf-8")).hexdigest()


def binding_sha256(components: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(components)).encode("utf-8")).hexdigest()


# Non-Python inputs read on the replay path (P3, 2026-09-06): the feature-definition promotion records are
# read by features.registry.canonical_definition_status when provider_host resolves the feature instances
# at replay (provider_host.py:981 -> registry.resolve_feature_instances). The frozen manifest hashes .py
# files only, so the reuse key binds this file's bytes explicitly. Any other replay-time read is either
# hashed through the plan (dataset digest, session reference digest, model ids) or verified at launch
# (catalog bytes against the dataset digest).
REPLAY_DATA_FILES: Tuple[str, ...] = ("features/feature_definition_promotions.json",)


def replay_data_file_hashes(repo_root: Optional[Path]) -> Dict[str, Optional[str]]:
    if repo_root is None:
        return {}
    return {rel: _sha(Path(repo_root) / rel) for rel in REPLAY_DATA_FILES}


def replay_closure_binding(plan: Mapping[str, Any], *, dataset: Mapping[str, Any] | None, partition: Mapping[str, Any],
                           authorization_sha256: Optional[str], warmup_days: int, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """The reuse key for ONE partition of ONE compiled plan.

    ``partition`` carries period/year/primary_start/primary_end/run_end and the declared windows
    (``[{id, primary_start, primary_end}]`` or ``[]``). ``dataset`` is the resolved dataset record
    the replay actually read (``{dataset_id, logical_digest}``). ``repo_root`` binds the replay-time
    data files (REPLAY_DATA_FILES); the lifecycle always passes it.
    """
    col = collection_closure(plan)
    components = {
        "schema_version": REPLAY_CLOSURE_SCHEMA_VERSION,
        "replay_data_files": replay_data_file_hashes(repo_root),
        "replay_closure_composite_sha256": col["composite_sha256"],
        "replay_closure_stage": col["stage"],
        "replay_closure_file_count": len(col["files"]),
        "hash_algorithm": col["hash_algorithm"],
        "replay_plan_sha256": replay_plan_sha256(plan),
        "dataset": {"dataset_id": (dataset or {}).get("dataset_id"), "logical_digest": (dataset or {}).get("logical_digest")},
        "partition": {"period": partition["period"], "year": int(partition["year"]),
                      "primary_start": partition["primary_start"], "primary_end": partition["primary_end"],
                      "run_end": partition.get("run_end"), "warmup_days": int(warmup_days),
                      "windows": [{"id": w["id"], "primary_start": w["primary_start"], "primary_end": w["primary_end"]}
                                  for w in (partition.get("windows") or [])]},
        "authorization_sha256": authorization_sha256,
    }
    return {"components": components, "replay_closure_sha256": binding_sha256(components)}


def reuse_policy(plan: Mapping[str, Any]) -> Dict[str, str]:
    pr = ((plan.get("chronology") or {}).get("partition_reuse") or {})
    mode = str(pr.get("mode") or REUSE_MODE_OFF)
    shadow = str(pr.get("shadow") or SHADOW_EVERY_RUN)
    return {"mode": mode, "shadow": shadow}


# -- verification -----------------------------------------------------------------------------------
def _sha(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_reusable(manifest: Mapping[str, Any], out_dir: Path, expected: Mapping[str, Any]) -> Tuple[bool, str]:
    """Deterministic reuse proof for one existing partition directory.

    Order: manifest PASS -> manifest carries a binding -> recorded components re-hash to the recorded
    key (the sidecar is internally consistent) -> recorded key equals the key derived from the CURRENT
    plan -> parquet bytes match the manifest. Any failure returns (False, reason).
    """
    if manifest.get("status") != "PASS":
        return False, "MANIFEST_NOT_PASS"
    rc = manifest.get("replay_closure") or {}
    if not rc.get("replay_closure_sha256") or not rc.get("components"):
        return False, "NO_REPLAY_CLOSURE_BINDING"
    if binding_sha256(rc["components"]) != rc["replay_closure_sha256"]:
        return False, "RECORDED_BINDING_INCONSISTENT"
    if rc["replay_closure_sha256"] != expected["replay_closure_sha256"]:
        diff = [k for k in expected["components"] if expected["components"].get(k) != rc["components"].get(k)]
        return False, "REPLAY_CLOSURE_CHANGED:" + ",".join(diff)
    if _sha(out_dir / "candidates.parquet") != manifest.get("candidates_sha256") or _sha(out_dir / "observations.parquet") != manifest.get("observations_sha256"):
        return False, "ARTIFACT_BYTES_MISMATCH"
    return True, "REUSABLE"


def select_shadow(reused_ids: Sequence[str], seed_hex: str, *, shadow_policy: str) -> Optional[str]:
    """Pick the partition to recompute this run. Uniform over the reused partitions, seeded by the
    seal so the choice is reproducible for a given sealed study; ``sampled`` runs a shadow on one
    run in SHADOW_SAMPLED_ONE_IN."""
    if not reused_ids:
        return None
    seed = int(hashlib.sha256(str(seed_hex).encode("utf-8")).hexdigest()[:16], 16)
    if shadow_policy == SHADOW_SAMPLED and seed % SHADOW_SAMPLED_ONE_IN != 0:
        return None
    return random.Random(seed).choice(sorted(reused_ids))


# -- import tracing (empirical membership proof) ------------------------------------------------------
class ImportTrace:
    """Record every module imported while active (a ``sys.meta_path`` observer that never loads)."""

    def __init__(self) -> None:
        self.names: List[str] = []

    def find_spec(self, name, path=None, target=None):  # importlib finder protocol
        self.names.append(name)
        return None

    def __enter__(self) -> "ImportTrace":
        sys.meta_path.insert(0, self)
        return self

    def __exit__(self, *exc) -> None:
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass


def repo_files_for_modules(names: Iterable[str], repo_root: Path) -> List[str]:
    """Repo-relative file paths of the named modules that resolved to files under ``repo_root``
    (test modules excluded, matching the compiler's closure walk)."""
    repo_root = Path(repo_root).resolve()
    out: Set[str] = set()
    for name in names:
        mod = sys.modules.get(name)
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        try:
            rel = Path(f).resolve().relative_to(repo_root).as_posix()
        except ValueError:
            continue
        parts = Path(rel).parts
        if "tests" in parts or "__pycache__" in parts or not rel.endswith(".py"):
            continue
        out.add(rel)
    return sorted(out)


def assert_within_closure(traced_files: Iterable[str], closure_files: Iterable[str]) -> List[str]:
    """Every traced repo file must be in the collection-stage closure. Returns the escapes (empty
    when clean) and raises ReplayClosureEscape when any exist."""
    escapes = sorted(set(traced_files) - set(closure_files))
    if escapes:
        raise ReplayClosureEscape("REPLAY_CLOSURE_ESCAPE: imported during replay but outside the collection-stage closure: " + ", ".join(escapes))
    return escapes


__all__ = ["REPLAY_PLAN_EXCLUDED_KEYS", "REPLAY_CHRONOLOGY_EXCLUDED_KEYS", "REUSE_MODE_OFF", "REUSE_MODE_REPLAY_CLOSURE",
           "SHADOW_EVERY_RUN", "SHADOW_SAMPLED", "SHADOW_SAMPLED_ONE_IN", "SHADOW_BAKE_IN_CLEAN_STUDIES",
           "ReplayClosureError", "ReplayClosureEscape", "collection_closure", "replay_plan_subset", "replay_plan_sha256",
           "binding_sha256", "replay_closure_binding", "reuse_policy", "verify_reusable", "select_shadow",
           "ImportTrace", "repo_files_for_modules", "assert_within_closure", "merge_trace_union"]
