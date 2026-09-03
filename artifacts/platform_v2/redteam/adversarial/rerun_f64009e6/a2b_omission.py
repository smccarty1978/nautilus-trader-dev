"""A2b: concrete closure-omission probe. For each candidate module, perturb its hash and show
whether the plan's execution composite moves. A module that can change a governed stage's
behaviour but leaves the composite unchanged is an omission."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_study, lifecycle, ROOT  # noqa

import research_workflow.closure_hash as ch
import research_workflow.grammar.compiler as C

CANDIDATES = [
    ("research_workflow/seal.py", "policy.verify_historical_authority (lifecycle stage) calls seal.seal_body_hash to authenticate a v1 study's historical execution authority"),
    ("research_workflow/workspace.py", "writer-lease ownership consumed by governed_controller_v2._check_writer_lease"),
    ("research_workflow/model_migration.py", "mints model-store manifests carrying legacy identity rules"),
    ("research/analysis/spec.py", "module-level import of research/analysis/modeling.py, which IS in the modeling closure"),
    ("research/analysis/errors.py", "InvalidAnalysisSpec raised by _build_estimator, the estimator factory v2 fit() uses"),
    ("research/analysis/loader.py", "analysis-harness partition loader"),
    ("research_workflow/capabilities.py", "resolves the capability registry the compiler binds trackers through"),
    ("features/registry.py", "FeatureInstance resolution for features.host: features"),
    ("features/engine.py", "feature computation engine"),
    ("utils/runner/data.py", "CausalDataLoader.load_bars"),
    ("research_workflow/host/outcomes.py", "the outcome kernel (control: MUST be hashed)"),
    ("research_workflow/policy.py", "control: MUST be hashed"),
]

_real = ch.hash_file_v2
out = []
with tempfile.TemporaryDirectory() as td:
    study = build_study(Path(td), "adv_omit2")
    lc = lifecycle(study, execute=True)
    lc.compile()
    plan = json.loads((study / "compiled_plan.json").read_text())
    base = plan["closure"]["composite_sha256"]
    files = plan["closure"]["files"]
    for rel, why in CANDIDATES:
        exists = (ROOT / rel).is_file()
        if not exists:
            out.append({"module": rel, "exists": False, "hashed": None, "composite_moves": None, "why": why})
            continue

        def fake(p, _m=rel):
            v = _real(p)
            try:
                r = Path(p).resolve().relative_to(ROOT).as_posix()
            except Exception:
                r = str(p)
            return "deadbeef" + v[8:] if r == _m else v

        ch.hash_file_v2 = fake
        try:
            o = C.compile_study(C.load_spec(study), repo_root=ROOT, datasets_dir=lc.opts.datasets_dir,
                                extra_bindings=lc.opts.extra_bindings)
            moved = o.plan.closure["composite_sha256"] != base
        finally:
            ch.hash_file_v2 = _real
        out.append({"module": rel, "exists": True, "hashed": rel in files, "composite_moves": moved, "why": why})

print(json.dumps(out, indent=1))
Path(__file__).with_name("a2b_results.json").write_text(json.dumps(out, indent=1))
print("\nUNHASHED:", json.dumps([o for o in out if o["exists"] and not o["hashed"]], indent=1))
