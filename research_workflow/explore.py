"""EXPLORE (THE FOUR STAGES, step 4): declared analysis over a REGISTERED frame, by id.

A collect study registers an immutable frame (`research_workflow.frame_store`). EXPLORE reads that
frame by id and produces tables from the same registered ``analysis_ops`` the study `analyze`
stage composes (`research/analysis/ops.py`), with the same compile-time proof
(`grammar/compiler.py: _check_analysis_pipeline`) and the same runner
(`research_workflow.analysis_pipeline`). What it deliberately does NOT have:

* no study, no seal, no contract audit, no closure vocabulary, no deliverable gate -- an EXPLORE
  run makes no claim, so there is nothing to audit against intent;
* no replay -- the frame is already collected, so a changed filter or a new table costs the
  pipeline, not the hour of replay plus two agent audits it costs inside a study;
* no write to the frame -- the frame is verified before and after the run (bytes hash to the
  record) and the outputs go to a separate directory.

An ``explore.yaml`` is the study's ``analysis:`` block detached from the study::

    explore: {id: t6_census, question: "1m flips per session-day, censored counts"}
    frame: <frame_id>                # optional; the CLI's --frame must match when both are given
    analysis:
      steps:
        - {id: census, op: analysis.classify.precedence, rows: frame, params: {...}}
      artifacts:
        - {name: census.json, source: census, kind: json}

``source`` / ``train_frame`` / ``model_scores`` do not exist here: the only built-in frame is
``frame`` (the registered frame, candidates joined with observations), and ops that read a
study's own execution artifacts (``needs_context``) are refused at compile time -- there is no
study to read. Claims come from a research study that BINDS the frame (step 2), never from here.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml
from pydantic import Field

from research_workflow.grammar.gaps import CapabilityGapReport, GapKind
from research_workflow.grammar.plan import canonical_json
from research_workflow.grammar.spec import AnalysisArtifactSpec, AnalysisStepSpec, _Strict

EXPLORE_SCHEMA_VERSION = 1
EXPLORE_RECORD = "explore.json"


class ExploreError(RuntimeError):
    pass


# -- spec -------------------------------------------------------------------------------------------
class ExploreSection(_Strict):
    id: Optional[str] = None
    question: Optional[str] = None
    description: Optional[str] = None


class ExploreAnalysisSpec(_Strict):
    """The study `analysis:` block without `source` / `model_scores`: one built-in frame, `frame`."""
    steps: List[AnalysisStepSpec] = Field(default_factory=list)
    artifacts: List[AnalysisArtifactSpec] = Field(default_factory=list)


class ExploreSpec(_Strict):
    explore: ExploreSection = Field(default_factory=ExploreSection)
    frame: Optional[str] = None                            # the registered frame id this spec is written against
    analysis: ExploreAnalysisSpec


def load_explore_spec(path: Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise ExploreError(f"EXPLORE_SPEC_MISSING: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ExploreError(f"EXPLORE_SPEC_INVALID: {p} is not a mapping")
    return data


def spec_sha256(raw: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(raw)).encode("utf-8")).hexdigest()


# -- compile ----------------------------------------------------------------------------------------
def compile_explore(spec_data: Mapping[str, Any], *, registry: Optional[Mapping[str, Any]] = None
                    ) -> Tuple[Optional[Dict[str, Any]], CapabilityGapReport]:
    """Prove an explore spec before it runs: the same pipeline proof the study compiler applies
    (registered ops, bound inputs, DAG in declaration order, named artifacts), with `frame` as the
    only built-in and context-reading ops refused. Returns ``(compiled, gaps)``; ``compiled`` is
    None when there is any gap."""
    raw = dict(spec_data)
    report = CapabilityGapReport(str((raw.get("explore") or {}).get("id") or "explore"))
    try:
        spec = ExploreSpec.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(x) for x in e.get("loc", ()))
                report.add(GapKind.INVALID_PARAMETERIZATION, loc or "spec", e.get("msg", str(exc)))
        else:
            report.add(GapKind.INVALID_PARAMETERIZATION, "spec", str(exc))
        return None, report
    if registry is None:
        from research_workflow.capabilities import load_registry
        registry = load_registry()
    from research.analysis.ops import context_ops
    from research_workflow.grammar.compiler import _check_analysis_pipeline
    registered = {e["id"] for e in registry.get("kinds", {}).get("analysis_ops", [])}
    if not spec.analysis.steps:
        report.add(GapKind.INVALID_PARAMETERIZATION, "analysis.steps", "declare at least one analysis step")
    builtin = {"frame"}

    def _unbound(ref: str) -> str:
        if ref == "train_frame":
            return "'train_frame' belongs to a study's analysis under source: oos; EXPLORE reads one registered frame, 'frame'"
        return f"{ref!r} is neither 'frame' (the registered frame) nor an earlier step"

    steps, artifacts = _check_analysis_pipeline(report.add, spec.analysis.steps, spec.analysis.artifacts,
                                                registered=registered, builtin=builtin, unbound=_unbound)
    needs_study = context_ops()
    for i, step in enumerate(spec.analysis.steps):
        if step.op in needs_study:
            report.add(GapKind.UNSUPPORTED_COMPOSITION, f"analysis.steps[{i}].op",
                       f"{step.op} reads a study's own execution artifacts (needs_context); EXPLORE has no study -- "
                       "declare it in the analysis of a research study that binds the frame")
    if not report.ok:
        return None, report
    compiled = {"schema_version": EXPLORE_SCHEMA_VERSION, "kind": "explore",
                "explore": {"id": spec.explore.id, "question": spec.explore.question, "description": spec.explore.description},
                "frame": spec.frame, "steps": steps, "artifacts": artifacts, "ops": sorted({s["op"] for s in steps}),
                "spec_sha256": spec_sha256(raw)}
    return compiled, report


# -- run --------------------------------------------------------------------------------------------
def default_explore_root(frame_root: str | Path | None = None) -> Path:
    """Sibling `explore/` of the frame root: machine-local, like the frames themselves."""
    from research_workflow.frame_store import resolve_frame_root
    return resolve_frame_root(frame_root).parent / "explore"


def run_explore(frame_id: str, spec_path: Path, *, out_dir: str | Path | None = None, frame_root: str | Path | None = None,
                registry: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Run an explore spec over a registered frame. Verifies the frame before and after (bytes hash to
    its record; the run leaves it byte-identical), runs the compiled pipeline, writes the declared
    artifacts plus `explore.json` under ``out_dir`` and returns a card. Re-runnable: the same spec
    over the same frame writes the same directory again."""
    from research_workflow.analysis_pipeline import AnalysisPipelineError, run_pipeline, write_json
    from research_workflow.frame_store import FrameStoreError, load_frame, load_frame_record, verify_frame
    t0 = time.perf_counter()
    raw = load_explore_spec(Path(spec_path))
    compiled, gaps = compile_explore(raw, registry=registry)
    if compiled is None:
        return {"STATUS": "CAPABILITY_GAP", "frame_id": frame_id, "spec": str(spec_path), **gaps.to_dict()}
    if compiled.get("frame") and str(compiled["frame"]) != str(frame_id):
        raise ExploreError(f"EXPLORE_FRAME_MISMATCH: the spec is written against frame {compiled['frame']} but --frame names {frame_id}")
    try:
        before = verify_frame(frame_id, frame_root)
    except FrameStoreError as exc:
        raise ExploreError(f"EXPLORE_FRAME_UNAVAILABLE: {exc}") from exc
    record = load_frame_record(frame_id, frame_root)
    t_verified = time.perf_counter()
    frame = load_frame(frame_id, frame_root, verify=False)   # verified a moment ago; the run never writes it
    t_loaded = time.perf_counter()
    out = Path(out_dir) if out_dir else default_explore_root(frame_root) / frame_id / compiled["spec_sha256"][:12]
    out.mkdir(parents=True, exist_ok=True)
    frames: Dict[str, Any] = {"frame": frame}
    context = {"studies_root": None, "study_dir": None, "artifacts_dir": str(out), "model_root": None}
    try:
        ran = run_pipeline(compiled["steps"], compiled["artifacts"], frames, out_dir=out, context=context)
    except AnalysisPipelineError as exc:
        raise ExploreError(str(exc)) from exc
    t_ran = time.perf_counter()
    after = verify_frame(frame_id, frame_root)
    unmodified = (before["frame_id"] == after["frame_id"] and record["candidates_sha256"] == load_frame_record(frame_id, frame_root)["candidates_sha256"]
                  and record["observations_sha256"] == load_frame_record(frame_id, frame_root)["observations_sha256"])
    if not unmodified:
        raise ExploreError("EXPLORE_FRAME_MODIFIED: the frame no longer hashes to its record after the run")
    elapsed = {"verify_s": round(t_verified - t0, 3), "load_s": round(t_loaded - t_verified, 3), "pipeline_s": round(t_ran - t_loaded, 3),
               "total_s": round(time.perf_counter() - t0, 3)}
    body = {"schema_version": EXPLORE_SCHEMA_VERSION, "kind": "explore", "frame_id": frame_id, "explore": compiled["explore"],
            "frame": {"dataset": (record.get("dataset") or {}).get("dataset_id"), "years": record.get("years"), "prohibited": record.get("prohibited"),
                      "windows": record.get("windows"), "rows": record.get("rows"), "permissive": (record.get("population") or {}).get("permissive"),
                      "candidates_sha256": record.get("candidates_sha256"), "observations_sha256": record.get("observations_sha256")},
            "spec_sha256": compiled["spec_sha256"], "spec_path": str(Path(spec_path).resolve()), "ops": compiled["ops"],
            "steps": ran["steps"], "artifacts": ran["artifacts"], "rows": int(len(frame)), "elapsed": elapsed,
            "frame_unmodified": True,
            # EXPLORE makes no claim: nothing here is sealed, audited, or closed, and nothing here is a deliverable.
            "governance": {"claim": None, "seal": None, "contract_audit": None, "closure": None, "deliverable_gate": None,
                           "note": "EXPLORE makes no claim; claims come from a research study that binds the frame"},
            "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json(out / EXPLORE_RECORD, body)
    return {"STATUS": "OK", "frame_id": frame_id, "out_dir": str(out), "rows": body["rows"], "steps": ran["steps"],
            "artifacts": [a["name"] for a in ran["artifacts"]], "elapsed": elapsed, "frame_unmodified": True, "record": str(out / EXPLORE_RECORD)}


__all__ = ["ExploreError", "ExploreSpec", "load_explore_spec", "compile_explore", "run_explore", "default_explore_root",
           "EXPLORE_SCHEMA_VERSION", "EXPLORE_RECORD"]
