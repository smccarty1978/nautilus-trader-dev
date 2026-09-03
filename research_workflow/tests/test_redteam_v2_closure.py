"""Red-team packet A / A2 -- the execution closure must be STAGE-SCOPED and must include
governance modules that were previously omitted entirely (lifecycle_v2.py,
governed_controller*.py, controller_contracts.py, policy.py, study_closure.py,
closure_hash.py, roots.py, forward_outcomes/guard.py, entry_references.py, experiment.py,
audit_packets_v2.py, and -- when the plan declares a model -- tuning.py, model_store.py,
research/analysis/{modeling,metrics,identity}.py).

Invariant: if executable code that can change a governed stage's scientific behavior
changes, that stage's closure (and the overall composite) must change; a change to code
outside every stage's closure (e.g. README.md) must not move any composite.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_workflow.grammar import compile_study, load_spec
from research_workflow.grammar.compiler import STAGE_CLOSURE_MODULES
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"

ALWAYS_ON_STAGES = ("lifecycle", "outcome", "oos", "audit")


def _compile_plan(model_block: str | None = None):
    spec = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")
    if model_block is not None:
        spec = spec.replace("chronology: {train: [2030], dev: [], prohibited: []}", "chronology: {train: [2029, 2030], dev: [], prohibited: []}")
        spec = spec.replace("model: none", model_block)
    out = compile_study(load_spec_text(spec), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.card()
    return out.plan.to_dict()


def load_spec_text(text: str):
    import yaml
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def plan_no_model():
    return _compile_plan()


@pytest.fixture(scope="module")
def plan_with_model():
    block = (
        "model:\n  family: lightgbm\n  params: {n_estimators: 20, max_depth: 2, num_leaves: 4, learning_rate: 0.1, verbosity: -1}\n"
        "  validation: {protocol: model_selection.random, tuning_years: [2029, 2030], final_train_validation_years: []}"
    )
    return _compile_plan(block)


def test_every_declared_governance_module_is_in_plan_closure_files(plan_no_model):
    files = set(plan_no_model["closure"]["files"])
    for stage in ALWAYS_ON_STAGES:
        for rel in STAGE_CLOSURE_MODULES[stage]:
            assert rel in files, f"{rel} (stage={stage}) missing from plan.closure.files"


def test_modeling_stage_only_present_when_model_declared(plan_no_model, plan_with_model):
    assert "modeling" not in plan_no_model["closure"]["stages"]
    assert "modeling" in plan_with_model["closure"]["stages"]
    files = set(plan_with_model["closure"]["files"])
    for rel in STAGE_CLOSURE_MODULES["modeling"]:
        assert rel in files


def test_readme_is_not_hashed(plan_no_model):
    assert "README.md" not in plan_no_model["closure"]["files"]
    assert not any(k.endswith("/README.md") for k in plan_no_model["closure"]["files"])


@pytest.mark.parametrize("stage", ALWAYS_ON_STAGES)
def test_each_governance_module_perturbation_moves_its_stage_and_the_composite_but_not_unrelated_stages(monkeypatch, plan_no_model, stage):
    for target_rel in STAGE_CLOSURE_MODULES[stage]:
        import research_workflow.closure_hash as closure_hash_mod

        real_hash_file_v2 = closure_hash_mod.hash_file_v2

        def perturbed(path, _target=target_rel, _real=real_hash_file_v2):
            digest = _real(path)
            rel = Path(path).resolve().relative_to(ROOT).as_posix() if Path(path).is_absolute() else str(path)
            if rel == _target:
                return ("f" if digest[0] != "f" else "e") + digest[1:]
            return digest

        monkeypatch.setattr(closure_hash_mod, "hash_file_v2", perturbed)
        # compiler imports hash_file_v2 locally inside _resolve_closure -- patch the module it
        # resolves `from research_workflow.closure_hash import hash_file_v2` against.
        out = compile_study(load_spec(GOLDEN / "study_barrier.yaml"), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
        assert out.ok, out.card()
        perturbed_plan = out.plan.to_dict()
        monkeypatch.undo()

        assert perturbed_plan["closure"]["composite_sha256"] != plan_no_model["closure"]["composite_sha256"], (
            f"perturbing {target_rel} (stage={stage}) did not move the overall composite"
        )
        assert perturbed_plan["closure"]["stages"][stage]["composite_sha256"] != plan_no_model["closure"]["stages"][stage]["composite_sha256"], (
            f"perturbing {target_rel} did not move its own stage ({stage}) composite"
        )
        for other in ALWAYS_ON_STAGES:
            if other == stage:
                continue
            if target_rel in STAGE_CLOSURE_MODULES[other]:
                continue  # legitimately shared between stages
            assert perturbed_plan["closure"]["stages"][other]["composite_sha256"] == plan_no_model["closure"]["stages"][other]["composite_sha256"], (
                f"perturbing {target_rel} (stage={stage}) moved unrelated stage {other}"
            )
