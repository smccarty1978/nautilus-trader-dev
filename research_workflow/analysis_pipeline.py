"""The declared analysis pipeline runner, shared by the study `analyze` stage and EXPLORE.

A compiled pipeline is a list of steps (registered ``analysis_ops``, each reading ``rows`` and
optional extra ``inputs`` that name the built-in frame(s) or an EARLIER step) and a list of
declared artifacts (``json`` payload, ``frame`` or ``observations`` parquet) that name a step. The
compiler (``grammar/compiler.py: _check_analysis_pipeline``) proves the shape before anything
runs; this module only executes it, in declaration order, and writes ONLY the declared artifacts.

Two callers, one runner:

* ``lifecycle_v2.V2Lifecycle._declared_analysis`` -- the study's own ``analysis:`` over its own
  collected frame (plus ``train_frame`` / own model scores when declared), under the study's
  seal and deliverable table.
* ``research_workflow.explore.run_explore`` -- THE FOUR STAGES step 4: the same ops over a
  REGISTERED frame by id, with no study, no seal, no audit and no claim.

Nothing here imports the lifecycle or the store: the runner takes frames and writes files.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional


class AnalysisPipelineError(RuntimeError):
    pass


def write_json(path: Path, data: Mapping[str, Any]) -> Path:
    """Atomic, sorted, indented JSON (the lifecycle's artifact writer; byte-identical output)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def sha256_file(path: Path) -> Optional[str]:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_pipeline(steps: List[Mapping[str, Any]], artifacts: List[Mapping[str, Any]], frames: MutableMapping[str, Any], *,
                 out_dir: Path, context: Mapping[str, Any]) -> Dict[str, Any]:
    """Run compiled ``steps`` over ``frames`` (mutated: every step's frame is added under its id)
    and write the declared ``artifacts`` under ``out_dir``.

    Returns ``{"steps": [...], "artifacts": [...], "payloads": {...}}`` -- the per-step row counts,
    the written artifacts with their sha256, and every step's JSON payload. ``context`` is the
    machine-local resolution context handed to ops that declare ``needs_context`` (never part of
    any identity).
    """
    from research.analysis.ops import run_op
    out_dir = Path(out_dir)
    extras: Dict[str, Any] = {}
    payloads: Dict[str, Any] = {}
    ran: List[Dict[str, Any]] = []
    for step in steps:
        rows = frames[step["rows"]]
        inputs = {name: frames[ref] for name, ref in (step.get("inputs") or {}).items()}
        result = run_op(step["op"], rows, inputs=inputs, params=step.get("params") or {}, context=dict(context))
        frames[step["id"]] = result["frame"]
        payloads[step["id"]] = result.get("payload") or {}
        if result.get("observations") is not None:
            extras[step["id"]] = result["observations"]
        ran.append({"id": step["id"], "op": step["op"], "rows_in": int(len(rows)), "rows_out": int(len(result["frame"]))})
    written: List[Dict[str, Any]] = []
    for art in artifacts:
        path = out_dir / art["name"]
        if art["kind"] == "json":
            write_json(path, payloads.get(art["source"]) or {})
        elif art["kind"] == "frame":
            path.parent.mkdir(parents=True, exist_ok=True)
            frames[art["source"]].to_parquet(path, index=False)
        else:
            if art["source"] not in extras:
                raise AnalysisPipelineError(f"ANALYSIS_ARTIFACT_UNAVAILABLE: step {art['source']!r} produced no observations frame")
            path.parent.mkdir(parents=True, exist_ok=True)
            extras[art["source"]].to_parquet(path, index=False)
        written.append({"name": art["name"], "kind": art["kind"], "source": art["source"], "sha256": sha256_file(path)})
    return {"steps": ran, "artifacts": written, "payloads": payloads}


__all__ = ["AnalysisPipelineError", "run_pipeline", "write_json", "sha256_file"]
