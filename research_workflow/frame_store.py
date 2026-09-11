"""Frame store: an immutable, content-hashed collection that outlives the study that made it.

THE FOUR STAGES, step 1 (COLLECT). A `stage: collect` study runs the governed controller through
`merge` under a frame seal (closure composite + causal audit; no contract audit, no claim) and is
then REGISTERED here instead of closed. The frame is the first-class object; the study is its
provenance.

Frame identity is derived from what was COLLECTED, never from who collected it:

    frame_id = sha256( replay-closure composite            # host + bound provider/tracker modules
                     + replay plan subset sha256            # plan minus analysis/model/study/notes/ids
                     + replay data files                    # feature_definition_promotions.json bytes
                     + dataset {dataset_id, logical_digest}
                     + chronology content {train, prohibited, windows}
                     + per-partition interval + parquet byte hashes
                     + merged content identities )

Every component but the chronology content and the merged content identities is a component of
the partition reuse key (`research_workflow.replay_closure.replay_closure_binding`); the one
component of that key deliberately NOT here is `authorization_sha256`, which hashes the study id
and path. The reuse key itself is untouched: the frame id is a second, wider identity derived
beside it. Two studies with different ids that replay the same plan over the same years therefore
register the SAME frame (gate 2 of the packet).

The store is machine-local like the model store (`~/.nt_research/frames/<frame_id>/`; override with
`NT_RESEARCH_FRAME_ROOT`, or the `frame_root` argument). A registered frame is never overwritten:
re-registering an identical frame is idempotent and appends the registering study to `sources.json`
(provenance, outside the identity); a different frame under the same id is refused.

This module is CLI/registration-side only: nothing on the replay path imports it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from research_workflow.grammar.plan import canonical_json

FRAME_SCHEMA_VERSION = 1
FRAME_RECORD = "frame.json"
FRAME_SOURCES = "sources.json"
FRAME_FILES = ("candidates.parquet", "observations.parquet")
DEFAULT_FRAME_ROOT = Path.home() / ".nt_research" / "frames"


class FrameStoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> Optional[str]:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(path: Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _write(path: Path, data: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# -- root -------------------------------------------------------------------------------------------
def resolve_frame_root(explicit: str | Path | None = None, *, create: bool = False) -> Path:
    """Explicit argument > NT_RESEARCH_FRAME_ROOT > sibling of the configured model root > ~/.nt_research/frames."""
    if explicit:
        root = Path(explicit).expanduser()
    elif os.environ.get("NT_RESEARCH_FRAME_ROOT"):
        root = Path(os.environ["NT_RESEARCH_FRAME_ROOT"]).expanduser()
    else:
        root = DEFAULT_FRAME_ROOT
        try:
            from research_workflow.roots import load_config
            cfg = load_config()
            if cfg.model_root is not None and not os.environ.get("NT_RESEARCH_MODEL_ROOT"):
                root = Path(cfg.model_root).parent / "frames"
        except Exception:
            pass
    root = root.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def frame_dir(frame_id: str, frame_root: str | Path | None = None) -> Path:
    return resolve_frame_root(frame_root) / frame_id


# -- identity ---------------------------------------------------------------------------------------
def frame_identity_components(plan: Mapping[str, Any], partition_manifests: List[Mapping[str, Any]],
                              merged_identity: Mapping[str, Any]) -> Dict[str, Any]:
    """The identity payload of a frame. Pure function of the plan, the partition manifests and the
    merged content identities; contains no study id, path, seal, authorization or timestamp."""
    if not partition_manifests:
        raise FrameStoreError("FRAME_NO_PARTITIONS")
    bindings = [dict((m.get("replay_closure") or {}).get("components") or {}) for m in partition_manifests]
    if any(not b for b in bindings):
        raise FrameStoreError("FRAME_PARTITION_WITHOUT_REPLAY_BINDING: every partition manifest must record its replay_closure binding")
    shared_keys = ("replay_closure_composite_sha256", "replay_closure_stage", "replay_plan_sha256", "replay_data_files", "dataset", "hash_algorithm")
    shared = {k: bindings[0].get(k) for k in shared_keys}
    for b in bindings[1:]:
        for k in shared_keys:
            if b.get(k) != shared[k]:
                raise FrameStoreError(f"FRAME_PARTITIONS_DISAGREE: partitions differ on replay component {k!r}")
    partitions = []
    for m, b in sorted(zip(partition_manifests, bindings), key=lambda mb: int(mb[0]["year"])):
        interval = dict(b.get("partition") or {})
        partitions.append({"year": int(m["year"]), "primary_start": interval.get("primary_start"), "primary_end": interval.get("primary_end"),
                           "run_end": interval.get("run_end"), "warmup_days": interval.get("warmup_days"), "windows": interval.get("windows") or [],
                           "candidates_sha256": m.get("candidates_sha256"), "observations_sha256": m.get("observations_sha256"),
                           "rows": (m.get("rows") or {}).get("candidates")})
    ch = plan.get("chronology") or {}
    from research_workflow.lifecycle_v2 import windows_identity
    return {
        "schema_version": FRAME_SCHEMA_VERSION,
        **shared,
        "chronology": {"train": sorted(int(y) for y in ch.get("train") or []),
                       "prohibited": sorted(int(y) for y in ch.get("prohibited") or []),
                       "windows": windows_identity(ch.get("windows") or [])},
        "partitions": partitions,
        "content": {"candidates_identity": merged_identity.get("candidates_identity"),
                    "observations_identity": merged_identity.get("observations_identity")},
    }


def frame_id_of(components: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(components)).encode("utf-8")).hexdigest()


# -- registration -----------------------------------------------------------------------------------
def _collect_study_evidence(study: Path, *, repo_root: Optional[Path] = None, options: Any = None) -> Dict[str, Any]:
    """Everything `register_frame` needs from a collect study, verified: compiled plan of stage
    collect, frame seal against the frozen composite with the causal audit CLEAR, a merge receipt
    fresh against the current closure, partition manifests with byte-true parquet."""
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import load_plan
    study = Path(study).resolve()
    plan = load_plan(study)
    if plan.get("stage") != "collect":
        raise FrameStoreError("FRAME_STUDY_NOT_COLLECT: only a `stage: collect` study registers a frame; a research study closes")
    kwargs: Dict[str, Any] = {"options": options} if options is not None else {}
    if repo_root is not None:
        kwargs["repo_root"] = repo_root
    ctl = V2StudyController(study, **kwargs)
    fp = ctl._fingerprints()
    frozen = fp.get("execution_composite")
    if not frozen or fp.get("current_execution_composite") != frozen:
        raise FrameStoreError("FRAME_CLOSURE_STALE: the frozen execution composite is not the current closure; re-run the controller through merge")
    if not ctl._fresh_stage("seal", fp):
        raise FrameStoreError("FRAME_SEAL_NOT_FRESH: the frame seal (causal audit CLEAR against the frozen composite) is missing or stale")
    if not ctl._fresh_stage("merge", fp):
        raise FrameStoreError("FRAME_MERGE_NOT_FRESH: no fresh merge receipt for the current closure; re-run `study run --through merge --execute-authorized`")
    work = study / "_work" / "controller"
    seal = _read(study / "artifacts" / "preexec_audit_seal.json")
    if seal.get("seal_kind") != "frame":
        raise FrameStoreError("FRAME_SEAL_KIND: the seal is not a frame seal")
    causal = _read(study / "audit" / "status.json")
    if causal.get("verdict") != "CLEAR" or causal.get("audited_execution_composite_sha256") != frozen:
        raise FrameStoreError("FRAME_CAUSAL_AUDIT_NOT_CLEAR")
    merged = work / "merged"
    identity = _read(merged / "identity.json")
    for name in FRAME_FILES:
        if _sha(merged / name) != identity.get(f"{name.split('.')[0]}_sha256"):
            raise FrameStoreError(f"FRAME_MERGED_BYTES_DRIFTED: {name}")
    years = [int(y) for y in identity.get("years") or []]
    manifests = []
    for y in years:
        d = work / "partitions" / "train" / str(y)
        m = _read(d / "manifest.json")
        if m.get("status") != "PASS":
            raise FrameStoreError(f"FRAME_PARTITION_NOT_PASS: {y}")
        for name in FRAME_FILES:
            if _sha(d / name) != m.get(f"{name.split('.')[0]}_sha256"):
                raise FrameStoreError(f"FRAME_PARTITION_BYTES_DRIFTED: {y}/{name}")
        manifests.append(m)
    reconcile = _read(work / "reconcile.json")
    if not reconcile.get("passed"):
        raise FrameStoreError("FRAME_RECONCILE_NOT_PASSED")
    return {"study": study, "plan": plan, "frozen": frozen, "seal": seal, "causal": causal, "identity": identity,
            "manifests": manifests, "years": years, "work": work, "merged": merged}


def _platform_commit(repo_root: Optional[Path]) -> Optional[str]:
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root) if repo_root else None, capture_output=True, text=True, check=False)
        return r.stdout.strip() or None
    except Exception:
        return None


def register_frame(study: str | Path, *, frame_root: str | Path | None = None, repo_root: Optional[Path] = None,
                   options: Any = None) -> Dict[str, Any]:
    """Register the merged TRAIN frame of a collect study under its content-derived frame id.
    Idempotent for an identical frame; refuses to overwrite a different one. `options` is the
    study's V2Options (compile bindings, datasets dir) when it differs from the defaults."""
    ev = _collect_study_evidence(Path(study), repo_root=repo_root, options=options)
    plan, study_dir = ev["plan"], ev["study"]
    components = frame_identity_components(plan, ev["manifests"], ev["identity"])
    fid = frame_id_of(components)
    root = resolve_frame_root(frame_root, create=True)
    target = root / fid
    cols = plan.get("columns") or {}
    label_columns = [plan["outcome"].get("label_column")] if (plan.get("outcome") or {}).get("label_column") else []
    label_columns += [f"{a.get('prefix')}_label" for a in ((plan.get("outcome") or {}).get("arms") or []) if a.get("prefix")]
    record = {
        "schema_version": FRAME_SCHEMA_VERSION, "frame_id": fid, "kind": "frame",
        "components": components,
        "dataset": components["dataset"], "years": components["chronology"]["train"], "prohibited": components["chronology"]["prohibited"],
        "windows": components["chronology"]["windows"],
        "columns": {"identity": list(cols.get("identity") or []), "metadata": list(cols.get("metadata") or []),
                    "features": list(cols.get("features") or []), "derived": list(cols.get("derived") or []),
                    "labels": [c for c in label_columns if c]},
        "population": {"session": (plan.get("population") or {}).get("session"), "cadence": (plan.get("population") or {}).get("cadence"),
                       "qualify": ((plan.get("population") or {}).get("qualify") or {}).get("text"),
                       "triggers": (plan.get("triggers") or {}).get("kind"),
                       "permissive": not (plan.get("population") or {}).get("qualify")},
        "trackers": [{"id": t["id"], "capability": t.get("capability")} for t in plan.get("trackers") or []],
        "outcome": {"contract": (plan.get("outcome") or {}).get("contract"), "kernel": (plan.get("outcome") or {}).get("kernel")},
        "rows": int(ev["identity"].get("rows") or 0),
        "candidates_sha256": ev["identity"].get("candidates_sha256"), "observations_sha256": ev["identity"].get("observations_sha256"),
        "content": components["content"],
        "replay_closure_composite_sha256": components["replay_closure_composite_sha256"], "replay_plan_sha256": components["replay_plan_sha256"],
        "registered_at_utc": _now(),
    }
    # Provenance of THIS registration (who collected it, under which seal and audit). The seal hash
    # and the audit report name the study, so they live in sources.json, never in the record.
    source = {"study_id": plan["study"]["id"], "study_path": str(study_dir), "plan_sha256": plan["plan_sha256"],
              "execution_composite_sha256": ev["frozen"], "frame_seal_hash": ev["seal"].get("composite_seal_hash"),
              "causal_audit": {"auditor": ev["causal"].get("auditor"), "report_sha256": ev["causal"].get("audit_report_sha256"),
                               "audited_execution_composite_sha256": ev["causal"].get("audited_execution_composite_sha256")},
              "platform_commit": _platform_commit(repo_root), "registered_at_utc": record["registered_at_utc"]}
    existing = _read(target / FRAME_RECORD)
    if existing:
        stable = {k: v for k, v in existing.items() if k != "registered_at_utc"}
        mine = {k: v for k, v in record.items() if k != "registered_at_utc"}
        if stable != mine:
            raise FrameStoreError(f"FRAME_ID_COLLISION: {fid} is registered with a different record; a frame is never overwritten")
        verify_frame(fid, frame_root=root)
        sources = _read(target / FRAME_SOURCES).get("sources") or []
        if not any(s.get("study_id") == source["study_id"] and s.get("plan_sha256") == source["plan_sha256"] for s in sources):
            sources.append(source)
            _write(target / FRAME_SOURCES, {"frame_id": fid, "sources": sources})
        receipt = _write_receipt(study_dir, record, source, target, "already_registered")
        return {"STATUS": "OK", "frame_id": fid, "result": "already_registered", "frame_dir": str(target), "rows": record["rows"], "years": record["years"],
                "receipt": str(receipt)}
    staging = root / f".{fid}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        for name in FRAME_FILES:
            shutil.copy2(ev["merged"] / name, staging / name)
            if _sha(staging / name) != record[f"{name.split('.')[0]}_sha256"]:
                raise FrameStoreError(f"FRAME_COPY_MISMATCH: {name}")
        shutil.copy2(ev["merged"] / "identity.json", staging / "identity.json")
        shutil.copy2(study_dir / "compiled_plan.json", staging / "compiled_plan.json")
        prov = staging / "provenance"; prov.mkdir()
        for rel in ("audit/frozen_execution_manifest.json", "artifacts/preexec_audit_seal.json", "audit/status.json",
                    "artifacts/replay_closure_trace.json", "artifacts/smoke_acceptance.json", "artifacts/experiment_authorization.json"):
            src = study_dir / rel
            if src.is_file():
                shutil.copy2(src, prov / src.name)
        for md in sorted((study_dir / "audit").glob("pass_*.md")):
            shutil.copy2(md, prov / md.name)
        if (ev["work"] / "reconcile.json").is_file():
            shutil.copy2(ev["work"] / "reconcile.json", prov / "reconcile.json")
        for y in ev["years"]:
            d = ev["work"] / "partitions" / "train" / str(y)
            pd_ = prov / "partitions" / str(y); pd_.mkdir(parents=True)
            for name in ("manifest.json", "replay_trace.json"):
                if (d / name).is_file():
                    shutil.copy2(d / name, pd_ / name)
        _write(staging / FRAME_SOURCES, {"frame_id": fid, "sources": [source]})
        _write(staging / FRAME_RECORD, record)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_frame(fid, frame_root=root)
    receipt = _write_receipt(study_dir, record, source, target, "registered")
    return {"STATUS": "OK", "frame_id": fid, "result": "registered", "frame_dir": str(target), "rows": record["rows"], "years": record["years"],
            "receipt": str(receipt)}


FRAME_RECEIPT = "artifacts/frame_registration.json"


def _write_receipt(study_dir: Path, record: Mapping[str, Any], source: Mapping[str, Any], target: Path, result: str) -> Path:
    """The study-side receipt of a registration: `artifacts/frame_registration.json`. It is what a
    later reader (the research supervisor, a session handoff) derives FRAME_REGISTERED from, so it
    is shaped like a controller card (STATUS / state) and bound to the plan it registered."""
    return _write(study_dir / FRAME_RECEIPT, {
        "schema_version": 1, "kind": "frame_registration", "STATUS": "OK", "state": "FRAME_REGISTERED", "result": result,
        "frame_id": record["frame_id"], "frame_dir": str(target), "frame_root": str(target.parent),
        "rows": record["rows"], "years": record["years"], "dataset": (record.get("dataset") or {}).get("dataset_id"),
        "study_id": source["study_id"], "plan_sha256": source["plan_sha256"], "execution_composite_sha256": source["execution_composite_sha256"],
        "registered_at_utc": record["registered_at_utc"],
        "next": {"explore": f"python scripts/research.py explore run --frame {record['frame_id']} --spec <explore.yaml>",
                 "verify": f"python scripts/research.py frame verify {record['frame_id']}"}})


# -- reading ----------------------------------------------------------------------------------------
def load_frame_record(frame_id: str, frame_root: str | Path | None = None) -> Dict[str, Any]:
    p = frame_dir(frame_id, frame_root) / FRAME_RECORD
    rec = _read(p)
    if not rec:
        raise FrameStoreError(f"FRAME_MISSING: {frame_id}")
    return rec


def verify_frame(frame_id: str, frame_root: str | Path | None = None) -> Dict[str, Any]:
    """Bytes hash to the record, the record's components re-derive its id, the id names the directory."""
    d = frame_dir(frame_id, frame_root)
    rec = load_frame_record(frame_id, frame_root)
    problems: List[str] = []
    if rec.get("frame_id") != frame_id:
        problems.append("FRAME_RECORD_ID_MISMATCH")
    if frame_id_of(rec.get("components") or {}) != frame_id:
        problems.append("FRAME_ID_NOT_DERIVED_FROM_COMPONENTS")
    for name in FRAME_FILES:
        if _sha(d / name) != rec.get(f"{name.split('.')[0]}_sha256"):
            problems.append(f"FRAME_BYTES_DRIFTED:{name}")
    if problems:
        raise FrameStoreError("FRAME_VERIFY_FAILED: " + ", ".join(problems))
    return {"STATUS": "OK", "frame_id": frame_id, "frame_dir": str(d), "rows": rec.get("rows"), "years": rec.get("years"), "verified": True}


def list_frames(frame_root: str | Path | None = None) -> List[Dict[str, Any]]:
    root = resolve_frame_root(frame_root)
    out = []
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        rec = _read(d / FRAME_RECORD)
        if not rec:
            continue
        sources = _read(d / FRAME_SOURCES).get("sources") or []
        out.append({"frame_id": rec.get("frame_id"), "dataset": (rec.get("dataset") or {}).get("dataset_id"), "years": rec.get("years"),
                    "rows": rec.get("rows"), "permissive": (rec.get("population") or {}).get("permissive"),
                    "registered_at_utc": rec.get("registered_at_utc"), "sources": [s.get("study_id") for s in sources]})
    return out


def load_frame(frame_id: str, frame_root: str | Path | None = None, *, verify: bool = True):
    """The merged frame (candidates joined with every observation column) after verification."""
    import pandas as pd
    if verify:
        verify_frame(frame_id, frame_root)
    d = frame_dir(frame_id, frame_root)
    from research_workflow.lifecycle_v2 import KEY
    c = pd.read_parquet(d / "candidates.parquet"); o = pd.read_parquet(d / "observations.parquet")
    dup = [col for col in o.columns if col in c.columns and col not in KEY]
    return c.merge(o.drop(columns=dup), on=list(KEY), how="inner")


__all__ = ["FrameStoreError", "resolve_frame_root", "frame_dir", "frame_identity_components", "frame_id_of", "register_frame",
           "load_frame_record", "verify_frame", "list_frames", "load_frame", "FRAME_SCHEMA_VERSION", "FRAME_RECEIPT"]
