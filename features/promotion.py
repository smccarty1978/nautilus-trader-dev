"""Feature definition promotion: a definition is verified by evidence about ITSELF.

Before this module, a canonical definition became ``verified`` for active resolution only by
being written into the authority bundle (``features/authority/``) -- which happened through a
legacy-alias parity inventory (migration-only) or a scoped promotion record from a sealed
authorizing study.  A genuinely new definition had neither: no alias to compare against and
no sealed study, because it could not compile.  A sealed study proves a feature was used once;
it never proved the feature computes what its definition claims.

Three requirements, each of which a new definition can actually satisfy, all executed here:

1. **Golden values** -- ``features/definitions/golden/<name>.json``: known inputs (an event tape)
   to known outputs (expected snapshot values, derived independently and written down).  The
   fixture is replayed through the SAME runtime path a study uses (``ProviderHost`` and the
   provider family adapter), never through the provider class directly.
2. **Causal availability** -- reuses the existing availability machinery, it does not invent a
   second one: the definition's declared input contracts must cover every stream the adapter
   actually consumes, each expected value must be produced with only events available at or
   before its decision epoch dispatched, and the host's own ``SNAPSHOT_BEFORE_LATEST_RUNTIME_EVENT``
   guard must be exercised by the fixture (an event after the last snapshot is mandatory).
3. **Determinism** -- the replay runs twice on fresh hosts and the observed rows must be
   byte-identical.

``promote`` writes ``features/definitions/promotions/<name>.json`` binding the definition record,
the golden fixture and the provider module by content hash.  ``features.registry`` treats a
catalogue definition as verified only while that record exists AND its hashes still match; the
compiler additionally re-executes the fixture for every promoted definition a study binds, and
``scripts/check_feature_promotion.py`` re-executes every record at preflight.  An unevidenced
definition, or one whose evidence no longer matches, is refused -- at promote, at compile and at
preflight.

Substitution guard: a promotion is refused when the canonical name already exists in the
authority bundle (shadowing an existing identity), equals any existing alias (bundle alias,
physical catalogue entry, legacy instance override) or when an instance's generated physical
alias collides with an alias already owned by a different canonical name.  A promoted feature
therefore cannot silently take the place of a differently-named one.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "features" / "definitions" / "golden"
PROMOTIONS_DIR = REPO_ROOT / "features" / "definitions" / "promotions"
RECORD_DIR = REPO_ROOT / "features" / "definitions" / "canonical"
FIXTURE_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 1
_REL_TOL = 1e-12
_ABS_TOL = 1e-12


class FeaturePromotionRefused(RuntimeError):
    """Fail-closed: the code is the first token of the message."""


def content_sha256(path: Path) -> str:
    """SHA-256 of a text file's LOGICAL content: line endings normalised to LF.

    Same rule as the seal system's ``canonical_file_sha256`` (W7): this repository is checked
    out with ``core.autocrlf=true``, so the working tree holds CRLF while blobs hold LF. A
    byte-exact hash of a record, a fixture or a provider module would differ between a Windows
    and a Linux checkout of identical committed content, and a valid promotion would look stale
    purely because of a git setting. Every hash a promotion record binds uses this function.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


_sha256 = content_sha256


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def promotion_path(name: str) -> Path:
    return PROMOTIONS_DIR / f"{name}.json"


def record_path(name: str) -> Path:
    return RECORD_DIR / f"{name}.py"


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:   # a sandboxed evidence directory (tests): report the absolute path
        return path.resolve().as_posix()


def _provider_module_path(implementation: str) -> Path:
    module = implementation.rsplit(".", 1)[0]
    return REPO_ROOT.joinpath(*module.split(".")).with_suffix(".py")


# --------------------------------------------------------------------------- #
# fixture
# --------------------------------------------------------------------------- #
def load_fixture(name: str) -> Dict[str, Any]:
    path = golden_path(name)
    if not path.is_file():
        raise FeaturePromotionRefused(
            f"GOLDEN_FIXTURE_MISSING: {_rel(path)} -- a definition is verified by golden values "
            "(known inputs to known outputs); declare them before promoting")
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise FeaturePromotionRefused(f"GOLDEN_FIXTURE_INVALID: {_rel(path)}: {exc}") from exc
    problems: List[str] = []
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        problems.append(f"schema_version must be {FIXTURE_SCHEMA_VERSION}")
    if fixture.get("feature") != name:
        problems.append(f"feature must be {name!r}, got {fixture.get('feature')!r}")
    instances = fixture.get("instances")
    if not isinstance(instances, list) or not instances or not all(isinstance(i, dict) for i in instances):
        problems.append("instances must be a non-empty list of {parameters: {...}}")
    tape = fixture.get("tape")
    if not isinstance(tape, list) or not tape or not all(isinstance(e, dict) and "type" in e and isinstance(e.get("event"), dict) for e in tape):
        problems.append("tape must be a non-empty list of {type, event}")
    snaps = fixture.get("snapshots")
    if not isinstance(snaps, list) or not snaps:
        problems.append("snapshots must be a non-empty list")
    else:
        for i, s in enumerate(snaps):
            if not isinstance(s, dict) or "decision_ts" not in s or "price" not in s or "atr" not in s:
                problems.append(f"snapshots[{i}] needs decision_ts, price, atr")
            elif not isinstance(s.get("expected"), dict) or not s["expected"]:
                problems.append(f"snapshots[{i}].expected must name at least one alias -> value")
        if not problems and [s["decision_ts"] for s in snaps] != sorted(s["decision_ts"] for s in snaps):
            problems.append("snapshots must be in non-decreasing decision_ts order")
    if not str(fixture.get("derivation") or "").strip():
        problems.append("derivation (how the expected values were obtained independently of the code) is required")
    if problems:
        raise FeaturePromotionRefused(f"GOLDEN_FIXTURE_INVALID: {_rel(path)}: " + "; ".join(problems))
    return fixture


# --------------------------------------------------------------------------- #
# instance specs (catalogue-side: verification status is deliberately NOT consulted)
# --------------------------------------------------------------------------- #
def _instance_specs(name: str, instances: Sequence[Mapping[str, Any]]):
    from features.registry import (FeatureInstance, FeatureInstanceError, derive_instance_input_requirements,
                                   generate_physical_alias, validate_feature_instance, _canonical_definitions)
    from research_workflow.provider_host import InstanceSpec

    definitions = _canonical_definitions()
    if name not in definitions:
        raise FeaturePromotionRefused(
            f"FEATURE_DEFINITION_UNKNOWN: {name!r} has no record under {_rel(RECORD_DIR)}/")
    definition = definitions[name]
    specs: List[InstanceSpec] = []
    for item in instances:
        inst = FeatureInstance(name, dict(item.get("parameters") or {}), item.get("physical_alias"))
        try:
            params = validate_feature_instance(inst)
            alias = generate_physical_alias(inst)
            reqs = derive_instance_input_requirements(inst)
        except FeatureInstanceError as exc:
            raise FeaturePromotionRefused(f"GOLDEN_FIXTURE_INVALID: instance {dict(inst.parameters)}: {exc}") from exc
        specs.append(InstanceSpec(canonical_name=name, parameters=dict(params), physical_alias=alias,
                                  canonical_provider=definition.implementation,
                                  required_streams=tuple(reqs.get("required_streams") or ())))
    aliases = [s.physical_alias for s in specs]
    if len(aliases) != len(set(aliases)):
        raise FeaturePromotionRefused(f"GOLDEN_FIXTURE_INVALID: duplicate physical aliases {aliases}")
    return definition, specs


def declared_input_streams(definition: Any) -> List[str]:
    """The availability contract a definition declares, as host stream keys."""
    tokens = [t for t in str(getattr(definition, "source_timeframe", "") or "").split("+") if t]
    return sorted(f"completed_{t}" for t in tokens)


# --------------------------------------------------------------------------- #
# substitution guard
# --------------------------------------------------------------------------- #
def check_no_substitution(name: str, specs) -> Dict[str, Any]:
    from features import registry as R

    bundle = R._canonical_bundle("active")
    bundle_names = {d["canonical_name"] for d in (bundle or {}).get("registry", {}).get("definitions", [])}
    bundle_aliases = dict((bundle or {}).get("aliases", {}).get("aliases", {}))
    if name in bundle_names:
        raise FeaturePromotionRefused(
            f"FEATURE_ALREADY_IN_AUTHORITY_BUNDLE: {name!r} is a migrated identity; the bundle record is "
            "authoritative and cannot be shadowed by a catalogue promotion")
    owners: Dict[str, str] = {}
    for alias, rec in bundle_aliases.items():
        owners[alias] = str(rec.get("canonical_feature"))
    for alias, inst in R._instance_overrides().items():
        owners.setdefault(alias, inst.canonical_name)
    for phys in R._feature_registry():
        owners.setdefault(phys, phys)
    for other in R._canonical_definitions():
        if other != name:
            owners.setdefault(other, other)
    if name in owners and owners[name] != name:
        raise FeaturePromotionRefused(
            f"FEATURE_NAME_COLLIDES_WITH_ALIAS: {name!r} is already an alias of {owners[name]!r}")
    if name in owners:
        raise FeaturePromotionRefused(f"FEATURE_NAME_COLLIDES_WITH_ALIAS: {name!r} is an existing physical name")
    for spec in specs:
        owner = owners.get(spec.physical_alias)
        if owner is not None and owner != name:
            raise FeaturePromotionRefused(
                f"PHYSICAL_ALIAS_COLLISION: instance {dict(spec.parameters)} renders {spec.physical_alias!r}, "
                f"already owned by {owner!r}")
    return {"aliases_checked": len(owners), "bundle_definitions": len(bundle_names)}


# --------------------------------------------------------------------------- #
# replay
# --------------------------------------------------------------------------- #
def _replay(specs, fixture: Mapping[str, Any]) -> Dict[str, Any]:
    from research_workflow.provider_host import (ProviderHost, SnapshotBeforeLatestRuntimeEvent,
                                                 _event_avail_ts)

    try:
        host = ProviderHost.from_instance_specs(tuple(specs))
    except Exception as exc:  # binding failure is a refusal, not a crash
        raise FeaturePromotionRefused(f"FEATURE_HOST_CANNOT_BIND: {type(exc).__name__}: {exc}") from exc
    proof = host.verify_bindings()
    if not proof.get("passed"):
        raise FeaturePromotionRefused(f"FEATURE_HOST_CANNOT_BIND: unbound {sorted(proof.get('unbound') or [])}")
    tape = list(fixture["tape"])
    pointer = 0
    observed: List[Dict[str, Any]] = []
    last_ts: Optional[int] = None
    for snap in fixture["snapshots"]:
        decision_ts = int(snap["decision_ts"])
        while pointer < len(tape):
            ev = tape[pointer]
            avail = _event_avail_ts(str(ev["type"]), ev["event"])
            if avail is not None and avail > decision_ts:
                break
            host.dispatch(str(ev["type"]), dict(ev["event"]))
            pointer += 1
        kwargs: Dict[str, Any] = {"decision_ts": decision_ts, "price": float(snap["price"]), "atr": float(snap["atr"]),
                                  "episode_state": dict(snap.get("episode_state") or {})}
        if snap.get("family_a_atr") is not None:
            kwargs["family_a_atr"] = float(snap["family_a_atr"])
        row = host.snapshot(**kwargs)
        observed.append({"decision_ts": decision_ts, "events_dispatched": pointer, "row": dict(row)})
        last_ts = decision_ts
    # Requirement 2, mechanical part: the fixture must exercise the host's own availability guard.
    later = None
    while pointer < len(tape):
        ev = tape[pointer]
        avail = _event_avail_ts(str(ev["type"]), ev["event"])
        pointer += 1
        if avail is not None and last_ts is not None and avail > last_ts:
            later = (str(ev["type"]), dict(ev["event"]), avail)
            break
    if later is None:
        raise FeaturePromotionRefused(
            "GOLDEN_FIXTURE_NO_POST_SNAPSHOT_EVENT: the tape must carry at least one event available after the "
            "last snapshot so the availability guard (SNAPSHOT_BEFORE_LATEST_RUNTIME_EVENT) is exercised")
    host.dispatch(later[0], later[1])
    guard = None
    try:
        host.snapshot(decision_ts=int(last_ts), price=float(fixture["snapshots"][-1]["price"]),
                      atr=float(fixture["snapshots"][-1]["atr"]),
                      episode_state=dict(fixture["snapshots"][-1].get("episode_state") or {}))
    except SnapshotBeforeLatestRuntimeEvent as exc:
        guard = str(exc).split(":")[0]
    if guard != "SNAPSHOT_BEFORE_LATEST_RUNTIME_EVENT":
        raise FeaturePromotionRefused(
            "CAUSAL_GUARD_NOT_ENFORCED: a snapshot at the last decision epoch succeeded after a later event was "
            "dispatched; the runtime availability guard did not fire")
    return {"observed": observed, "required_streams": sorted(host.required_streams()),
            "adapters": sorted(type(a).__name__ for a in host.adapters), "causal_guard": guard,
            "post_snapshot_event": {"type": later[0], "avail_ts": later[2]}}


def _values_match(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(expected), float(actual), rel_tol=_REL_TOL, abs_tol=_ABS_TOL)
    return expected == actual


def verify(name: str) -> Dict[str, Any]:
    """Execute the three evidence requirements for ``name``; raise FeaturePromotionRefused on any failure."""
    fixture = load_fixture(name)
    definition, specs = _instance_specs(name, fixture["instances"])
    substitution = check_no_substitution(name, specs)
    first = _replay(specs, fixture)
    second = _replay(specs, fixture)
    first_bytes = json.dumps(first["observed"], sort_keys=True, default=str)
    second_bytes = json.dumps(second["observed"], sort_keys=True, default=str)
    if first_bytes != second_bytes:
        raise FeaturePromotionRefused("FEATURE_NONDETERMINISTIC: two replays of the golden tape produced different rows")
    declared = declared_input_streams(definition)
    consumed = first["required_streams"]
    undeclared = sorted(set(consumed) - set(declared))
    if undeclared:
        raise FeaturePromotionRefused(
            f"FEATURE_AVAILABILITY_CONTRACT_UNDERDECLARED: adapter consumes {undeclared} which "
            f"source_timeframe={definition.source_timeframe!r} does not declare")
    mismatches: List[Dict[str, Any]] = []
    aliases = {s.physical_alias for s in specs}
    for snap, obs in zip(fixture["snapshots"], first["observed"]):
        for alias, expected in snap["expected"].items():
            if alias not in aliases:
                mismatches.append({"decision_ts": obs["decision_ts"], "alias": alias, "error": "alias not an instance of this definition"})
                continue
            actual = obs["row"].get(alias)
            if not _values_match(expected, actual):
                mismatches.append({"decision_ts": obs["decision_ts"], "alias": alias, "expected": expected, "actual": actual})
    if mismatches:
        raise FeaturePromotionRefused(f"GOLDEN_VALUE_MISMATCH: {json.dumps(mismatches, default=str)}")
    provider_module = _provider_module_path(definition.implementation)
    if not provider_module.is_file():
        raise FeaturePromotionRefused(f"FEATURE_PROVIDER_MODULE_MISSING: {definition.implementation}")
    from research_workflow import provider_host as _ph
    return {
        "feature": name,
        "definition_record": _rel(record_path(name)), "definition_sha256": _sha256(record_path(name)),
        "golden_fixture": _rel(golden_path(name)), "golden_sha256": _sha256(golden_path(name)),
        "provider": definition.implementation, "provider_module": _rel(provider_module),
        "provider_sha256": _sha256(provider_module),
        "runtime_adapters": first["adapters"], "adapter_module": _rel(Path(_ph.__file__)),
        "adapter_sha256_informational": _sha256(Path(_ph.__file__)),
        "physical_aliases": sorted(aliases), "instances": [dict(s.parameters) for s in specs],
        "declared_input_contracts": declared, "consumed_streams": consumed,
        "snapshots": len(first["observed"]), "observed_sha256": hashlib.sha256(first_bytes.encode("utf-8")).hexdigest(),
        "determinism": {"runs": 2, "identical": True},
        "causal_guard": first["causal_guard"], "post_snapshot_event": first["post_snapshot_event"],
        "substitution_guard": substitution,
    }


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #
def promote(name: str, *, promoted_by: str = "research feature promote") -> Dict[str, Any]:
    """Verify ``name`` and write its promotion record.  Returns the record."""
    evidence = verify(name)
    record = {"schema_version": RECORD_SCHEMA_VERSION, **evidence,
              "promoted_at_utc": datetime.now(timezone.utc).isoformat(), "promoted_by": promoted_by}
    PROMOTIONS_DIR.mkdir(parents=True, exist_ok=True)
    promotion_path(name).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    from features import registry as R
    R.invalidate_promotion_cache()
    return record


def read_record(name: str) -> Optional[Dict[str, Any]]:
    path = promotion_path(name)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def record_binding_errors(name: str, record: Optional[Mapping[str, Any]] = None) -> List[str]:
    """Cheap (hash-only) check that a promotion record still describes the tree it was written against."""
    record = read_record(name) if record is None else record
    if record is None:
        return ["PROMOTION_RECORD_MISSING"]
    errors: List[str] = []
    if record.get("schema_version") != RECORD_SCHEMA_VERSION:
        errors.append("PROMOTION_RECORD_SCHEMA")
    if record.get("feature") != name:
        errors.append("PROMOTION_RECORD_FEATURE_MISMATCH")
    for key, path in (("definition_sha256", record_path(name)), ("golden_sha256", golden_path(name))):
        if not path.is_file() or record.get(key) != _sha256(path):
            errors.append(f"PROMOTION_RECORD_{key.upper()}_STALE")
    provider_module = REPO_ROOT / str(record.get("provider_module") or "")
    if not str(record.get("provider_module") or "") or not provider_module.is_file() or record.get("provider_sha256") != _sha256(provider_module):
        errors.append("PROMOTION_RECORD_PROVIDER_SHA256_STALE")
    if not record.get("observed_sha256") or not record.get("causal_guard") or not (record.get("determinism") or {}).get("identical"):
        errors.append("PROMOTION_RECORD_EVIDENCE_INCOMPLETE")
    return errors


def promoted_names() -> Tuple[str, ...]:
    if not PROMOTIONS_DIR.is_dir():
        return ()
    return tuple(sorted(p.stem for p in PROMOTIONS_DIR.glob("*.json")))


def evidence_files() -> Tuple[str, ...]:
    """Repo-relative golden fixtures and promotion records (closure seeds: they decide verified-ness)."""
    out = []
    for directory in (GOLDEN_DIR, PROMOTIONS_DIR):
        if directory.is_dir():
            out.extend(_rel(p) for p in sorted(directory.glob("*.json")))
    return tuple(out)


def check_record(name: str, *, execute: bool = True) -> Dict[str, Any]:
    """Validate one promotion record: hash binding, and (default) re-execution of its evidence."""
    record = read_record(name)
    errors = record_binding_errors(name, record)
    report: Dict[str, Any] = {"feature": name, "record": _rel(promotion_path(name)), "binding_errors": errors}
    if errors:
        report["passed"] = False
        return report
    if execute:
        try:
            evidence = verify(name)
        except FeaturePromotionRefused as exc:
            report.update({"passed": False, "execution_error": str(exc)})
            return report
        if evidence["observed_sha256"] != record.get("observed_sha256"):
            report.update({"passed": False, "execution_error": "PROMOTION_RECORD_OBSERVED_SHA256_STALE"})
            return report
    report["passed"] = True
    return report


def check_all(*, execute: bool = True) -> Dict[str, Any]:
    reports = [check_record(n, execute=execute) for n in promoted_names()]
    return {"passed": all(r["passed"] for r in reports), "records": reports, "count": len(reports)}


__all__ = ["FeaturePromotionRefused", "verify", "promote", "check_record", "check_all", "read_record",
           "record_binding_errors", "promoted_names", "evidence_files", "golden_path", "promotion_path",
           "record_path", "load_fixture", "declared_input_streams", "check_no_substitution"]
