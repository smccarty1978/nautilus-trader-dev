"""Partition reuse under the replay-closure key (``chronology.partition_reuse: replay_closure``).

The key is DERIVED from the compiled plan (collection-stage closure composite + replay-affecting plan
subset + dataset + partition interval + authorization) and never enumerated. These tests pin:

V1  a change to a real replay module REFUSES reuse (the one that matters);
V2  a post-collection-only change (study text, an audit-stage module) REUSES, and the served bytes equal
    a forced full recompute;
V4  ``off`` (the default) is the pre-existing behaviour and produces the same bytes as ``replay_closure``;
V5  shadow verification recomputes one reused partition and a mismatch is terminal;
    reconcile re-attests every reuse from the artifact and refuses tampering / missing receipts;
    the smoke replay's imports are proven inside the collection-stage closure, and an escape rejects smoke.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_workflow.grammar.compiler import compile_study, load_spec
from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options, load_plan
from research_workflow import replay_closure as rc

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


def _spec_path(tmp_path: Path, *, study_id: str = "reuse_probe", chronology: dict | None = None, question: str | None = None) -> Path:
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = study_id
    if question:
        body["study"]["question"] = question
    body["chronology"] = chronology or {"train": [2029, 2030], "dev": [], "prohibited": [], "partition_reuse": "replay_closure", "partition_reuse_shadow": "every_run"}
    study = tmp_path / "studies" / study_id
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return study


@pytest.fixture(scope="module")
def synthetic_bars():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    return bars, json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


def _lifecycle(study: Path, synthetic_bars, **extra) -> V2Lifecycle:
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    bars, expected = synthetic_bars
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=True, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True,
                     **{"smoke_date": "2030-01-01", **extra})
    return V2Lifecycle(study, repo_root=ROOT, options=opts)


def _seal(study: Path, tag: str) -> None:
    (study / "artifacts").mkdir(exist_ok=True)
    (study / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(
        {"composite_seal_hash": f"seal-{tag}", "execution_manifest_composite_sha256": f"mfst-{tag}"}), encoding="utf-8")


def _prepare_and_seal(lc: V2Lifecycle, tag: str, *, smoke: bool = True) -> dict:
    lc.compile()
    assert (lc.study / "compiled_plan.json").is_file()
    lc.prepare()
    _seal(lc.study, tag)
    if smoke:
        assert lc.smoke()["status"] == "PASS"   # smoke seeds the key: reuse needs a clean trace for THIS plan
    return load_plan(lc.study)


def _shas(study: Path, years=(2029, 2030)) -> dict:
    out = {}
    for y in years:
        m = json.loads((study / "_work" / "controller" / "partitions" / "train" / str(y) / "manifest.json").read_text(encoding="utf-8"))
        out[y] = (m["candidates_sha256"], m["observations_sha256"], m["plan_sha256"])
    return out


def _receipt(study: Path) -> dict:
    return json.loads((study / "_work" / "controller" / "train_partition_reuse.json").read_text(encoding="utf-8"))


# -- key derivation -------------------------------------------------------------------------------------
def test_collection_stage_closure_is_a_subset_of_the_frozen_manifest(tmp_path, synthetic_bars):
    study = _spec_path(tmp_path)
    _lifecycle(study, synthetic_bars).compile()
    plan = load_plan(study)
    closure = plan["closure"]
    col, rep = closure["stages"]["collection"], closure["stages"]["replay"]
    assert set(rep["files"]) <= set(col["files"]) <= set(closure["files"]), "replay within collection within frozen manifest"
    assert rep["composite_sha256"] and col["composite_sha256"] and closure["composite_sha256"]
    # Reading 2: the compiler, the controller and the analysis modules are not replay code
    for f in ("research_workflow/grammar/compiler.py", "research_workflow/lifecycle_v2.py", "research/analysis/diagnostic_ops.py"):
        assert f not in set(rep["files"]), f
    assert "research_workflow/host/strategy.py" in set(rep["files"])
    assert plan["chronology"]["partition_reuse"] == {"mode": "replay_closure", "shadow": "every_run"}


def test_key_ignores_post_collection_declarations_and_binds_replay_ones(tmp_path, synthetic_bars):
    study = _spec_path(tmp_path)
    _lifecycle(study, synthetic_bars).compile()
    plan = load_plan(study)
    part = {"period": "train", "year": 2030, "primary_start": "2030-01-01", "primary_end": "2030-12-31", "run_end": "2030-12-31", "windows": []}
    base = rc.replay_closure_binding(plan, dataset={"dataset_id": "SYN_A", "logical_digest": None}, partition=part, authorization_sha256="auth", warmup_days=5)

    def key(p):
        return rc.replay_closure_binding(p, dataset={"dataset_id": "SYN_A", "logical_digest": None}, partition=part, authorization_sha256="auth", warmup_days=5)["replay_closure_sha256"]

    # post-collection / identity keys: no effect on the key
    for mutate in (lambda p: p.__setitem__("analysis", {"ops": ["anything"]}),
                   lambda p: p.__setitem__("model", {"mode": "fit", "family": "x"}),
                   lambda p: p["study"].__setitem__("question", "a different question"),
                   lambda p: p.__setitem__("plan_sha256", "0" * 64),
                   lambda p: p["chronology"].__setitem__("partition_reuse", {"mode": "off", "shadow": "sampled"})):
        p = json.loads(json.dumps(plan)); mutate(p)
        assert key(p) == base["replay_closure_sha256"]
    # replay-affecting declarations: the key changes
    for mutate in (lambda p: p["population"].__setitem__("qualify", "regime.age_s >= 20s"),
                   lambda p: p["outcome"].__setitem__("horizon_ns", 120 * NS),
                   lambda p: p["closure"]["stages"]["replay"].__setitem__("composite_sha256", "f" * 64),
                   lambda p: p["chronology"].__setitem__("train", [2030]),
                   lambda p: p["instruments"]["SYN_A"].__setitem__("dataset_digest", "d" * 64)):
        p = json.loads(json.dumps(plan)); mutate(p)
        assert key(p) != base["replay_closure_sha256"]
    # interval, authorization and dataset are bound
    assert rc.replay_closure_binding(plan, dataset={"dataset_id": "SYN_A", "logical_digest": None}, partition={**part, "year": 2029, "primary_start": "2029-01-01", "primary_end": "2029-12-31", "run_end": "2029-12-31"},
                                     authorization_sha256="auth", warmup_days=5)["replay_closure_sha256"] != base["replay_closure_sha256"]
    assert rc.replay_closure_binding(plan, dataset={"dataset_id": "SYN_A", "logical_digest": None}, partition=part, authorization_sha256="other", warmup_days=5)["replay_closure_sha256"] != base["replay_closure_sha256"]
    assert rc.replay_closure_binding(plan, dataset={"dataset_id": "SYN_A", "logical_digest": "x"}, partition=part, authorization_sha256="auth", warmup_days=5)["replay_closure_sha256"] != base["replay_closure_sha256"]
    assert rc.binding_sha256(base["components"]) == base["replay_closure_sha256"]


# -- V4: off is the pre-existing behaviour, and produces the same bytes as replay_closure --------------------
def test_off_by_default_and_same_bytes_as_reuse_mode(tmp_path, synthetic_bars):
    off = _spec_path(tmp_path, study_id="off_probe", chronology={"train": [2029, 2030], "dev": [], "prohibited": []})
    lc_off = _lifecycle(off, synthetic_bars); plan_off = _prepare_and_seal(lc_off, "a")
    assert plan_off["chronology"]["partition_reuse"] == {"mode": "off", "shadow": "sampled"}
    r = lc_off.collection()
    assert r["status"] == "PASS" and "partition_reuse" not in r
    assert not (off / "_work" / "controller" / "train_partition_reuse.json").exists()
    first = _shas(off)
    # a re-seal with an unchanged plan recomputes under `off` (pre-existing behaviour) and reproduces the bytes
    _seal(off, "b"); lc_off.collection()
    second = _shas(off)
    assert {y: v[:2] for y, v in first.items()} == {y: v[:2] for y, v in second.items()}

    on = _spec_path(tmp_path, study_id="on_probe")
    lc_on = _lifecycle(on, synthetic_bars); _prepare_and_seal(lc_on, "a")
    lc_on.collection()
    assert {y: v[:2] for y, v in _shas(on).items()} == {y: v[:2] for y, v in first.items()}, "reuse mode must not change the collected bytes"
    rec = _receipt(on)
    assert rec["reused"] == [] and rec["recomputed"] == ["train-2029", "train-2030"]


# -- V2: post-collection-only changes reuse, bytes equal a forced recompute --------------------------------
def test_study_text_change_reuses_both_partitions_and_shadow_is_identical(tmp_path, synthetic_bars):
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); plan1 = _prepare_and_seal(lc, "a")
    lc.collection(); before = _shas(study)

    # an edit consumed only after collection: the plan hash changes, the replay key does not
    _spec_path(tmp_path, question="rephrased after the collection finished")
    plan2 = _prepare_and_seal(lc, "b")
    assert plan2["plan_sha256"] != plan1["plan_sha256"]
    preview = lc.partition_reuse_preview("train")
    assert preview["would_reuse"] == ["train-2029", "train-2030"], preview

    r = lc.collection()
    assert r["partition_reuse"] == {"reused": ["train-2029", "train-2030"], "recomputed": []}
    after = _shas(study)
    assert after == before, "reused partitions are served byte-for-byte, manifests untouched"
    rec = _receipt(study)
    assert [x["id"] for x in rec["reused"]] == ["train-2029", "train-2030"] and rec["shadow"]["status"] == "IDENTICAL"
    shadow = json.loads((study / "_work" / "controller" / "partition_reuse_shadow.json").read_text(encoding="utf-8"))
    assert shadow["selected"] in {"train-2029", "train-2030"} and shadow["status"] == "IDENTICAL"
    assert shadow["comparison"]["candidates"]["served"] == shadow["comparison"]["candidates"]["shadow"]

    # forced full recompute in a fresh study copy with reuse off: identical bytes
    forced = _spec_path(tmp_path, study_id="forced", chronology={"train": [2029, 2030], "dev": [], "prohibited": []}, question="rephrased after the collection finished")
    lc_f = _lifecycle(forced, synthetic_bars); _prepare_and_seal(lc_f, "b"); lc_f.collection()
    assert {y: v[:2] for y, v in _shas(forced).items()} == {y: v[:2] for y, v in after.items()}

    # reconcile re-attests the reuse and passes
    assert lc.reconcile()["status"] == "PASS"
    recon = json.loads((study / "_work" / "controller" / "reconcile.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in recon["partition_reuse"]["reattested"]] == ["train-2029", "train-2030"]
    assert all(x["reusable"] and x["receipt_recorded"] for x in recon["partition_reuse"]["reattested"])
    assert recon["partition_reuse"]["shadow"]["status"] == "IDENTICAL"


def test_audit_stage_module_change_reuses_but_replay_module_change_refuses(tmp_path, synthetic_bars, monkeypatch):
    """V1 / V2 at the derivation layer: the compiler re-hashes every closure file; a changed hash of a file
    OUTSIDE the collection stage keeps the key, a changed hash of a bound replay module changes it."""
    import research_workflow.closure_hash as ch
    real = ch.hash_file_v2
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); plan1 = _prepare_and_seal(lc, "a")
    lc.collection(); before = _shas(study)
    col_files = set(plan1["closure"]["stages"]["replay"]["files"])
    outside = sorted(set(plan1["closure"]["files"]) - col_files)
    assert outside, "the frozen manifest must carry stage-only modules outside the replay closure"

    def perturb(rel_suffix):
        def fake(path, **kw):
            h = real(path, **kw)
            return ("deadbeef" + h[8:]) if Path(path).as_posix().endswith(rel_suffix) else h
        return fake

    # (V2) an audit/lifecycle-stage-only module "changed": manifest composite moves, collection composite does not
    monkeypatch.setattr(ch, "hash_file_v2", perturb(outside[0]))
    plan2 = _prepare_and_seal(lc, "b")
    assert plan2["closure"]["composite_sha256"] != plan1["closure"]["composite_sha256"]
    assert plan2["closure"]["stages"]["replay"]["composite_sha256"] == plan1["closure"]["stages"]["replay"]["composite_sha256"]
    r = lc.collection()
    assert r["partition_reuse"]["reused"] == ["train-2029", "train-2030"] and _shas(study) == before

    # (V1) a bound replay module "changed": reuse is REFUSED for every partition, all are recomputed
    bound = next(f for f in col_files if f.startswith("research_workflow/host/strategy.py"))
    monkeypatch.setattr(ch, "hash_file_v2", perturb(bound))
    plan3 = _prepare_and_seal(lc, "c")
    assert plan3["closure"]["stages"]["replay"]["composite_sha256"] != plan1["closure"]["stages"]["replay"]["composite_sha256"]
    assert lc.partition_reuse_preview("train")["would_reuse"] == []
    r = lc.collection()
    assert r["partition_reuse"] == {"reused": [], "recomputed": ["train-2029", "train-2030"]}
    rec = _receipt(study)
    assert all(x["reason"].startswith("REPLAY_CLOSURE_CHANGED") and "replay_closure_composite_sha256" in x["reason"] for x in rec["refused"])
    assert all(v[2] == plan3["plan_sha256"] for v in _shas(study).values())


def test_population_change_refuses_reuse(tmp_path, synthetic_bars):
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); _prepare_and_seal(lc, "a"); lc.collection()
    body = yaml.safe_load((study / "study.yaml").read_text(encoding="utf-8"))
    body["population"]["qualify"] = "regime.age_s >= 20s and regime.frozen_atr > 0"
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    _prepare_and_seal(lc, "b")
    r = lc.collection()
    assert r["partition_reuse"]["reused"] == []
    assert all("replay_plan_sha256" in x["reason"] for x in _receipt(study)["refused"])


# -- V5: shadow mismatch is terminal --------------------------------------------------------------------------
def test_shadow_mismatch_is_terminal(tmp_path, synthetic_bars, monkeypatch):
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); _prepare_and_seal(lc, "a"); lc.collection()
    _spec_path(tmp_path, question="changed text"); _prepare_and_seal(lc, "b")
    real = V2Lifecycle._run_window

    def tampered(self, plan, start, end, primary, **kw):
        run = real(self, plan, start, end, primary, **kw)
        run["candidates"] = run["candidates"].iloc[:-1].reset_index(drop=True)
        run["observations"] = run["observations"].iloc[:-1].reset_index(drop=True)
        return run

    monkeypatch.setattr(V2Lifecycle, "_run_window", tampered)
    with pytest.raises(LifecycleV2Error, match="PARTITION_REUSE_SHADOW_MISMATCH"):
        lc.collection()
    shadow = json.loads((study / "_work" / "controller" / "partition_reuse_shadow.json").read_text(encoding="utf-8"))
    assert shadow["status"] == "MISMATCH"
    monkeypatch.setattr(V2Lifecycle, "_run_window", real)
    with pytest.raises(LifecycleV2Error, match="shadow verification MISMATCH"):
        lc.reconcile()


# -- reconcile refuses tampering and missing receipts --------------------------------------------------------
def test_reconcile_refuses_missing_receipt_and_tampered_binding(tmp_path, synthetic_bars):
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); _prepare_and_seal(lc, "a"); lc.collection()
    _spec_path(tmp_path, question="changed text"); _prepare_and_seal(lc, "b"); lc.collection()
    assert lc.reconcile()["status"] == "PASS"
    work = study / "_work" / "controller"
    receipt = work / "train_partition_reuse.json"
    saved = receipt.read_text(encoding="utf-8"); receipt.unlink()
    with pytest.raises(LifecycleV2Error, match="reused without a collection receipt"):
        lc.reconcile()
    receipt.write_text(saved, encoding="utf-8")
    mpath = work / "partitions" / "train" / "2030" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["replay_closure"]["components"]["authorization_sha256"] = "forged"
    mpath.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(LifecycleV2Error, match="RECORDED_BINDING_INCONSISTENT"):
        lc.reconcile()
    # a partition served under another plan with reuse OFF is a finding, never silently accepted
    off = _spec_path(tmp_path, study_id="off_recon", chronology={"train": [2029, 2030], "dev": [], "prohibited": []})
    lc2 = _lifecycle(off, synthetic_bars); _prepare_and_seal(lc2, "a"); lc2.collection()
    shutil.copytree(work / "partitions" / "train" / "2029", off / "_work" / "controller" / "partitions" / "train" / "2029", dirs_exist_ok=True)
    with pytest.raises(LifecycleV2Error, match="partition_reuse is off"):
        lc2.reconcile()


# -- smoke import trace ----------------------------------------------------------------------------------------
def test_smoke_proves_replay_imports_inside_the_collection_closure(tmp_path, synthetic_bars, monkeypatch):
    study = _spec_path(tmp_path, chronology={"train": [2030], "dev": [], "prohibited": []})
    lc = _lifecycle(study, synthetic_bars, smoke_date="2030-01-01"); plan = _prepare_and_seal(lc, "a")
    assert lc.smoke()["status"] == "PASS"
    trace = json.loads((study / "artifacts" / "replay_closure_trace.json").read_text(encoding="utf-8"))
    assert trace["verdict"] == "WITHIN_CLOSURE" and trace["escapes"] == []
    assert set(trace["traced_repo_files"]) <= set(plan["closure"]["stages"]["replay"]["files"])
    assert trace["closure_stage"] == "replay" and trace["runs"][-1]["kind"] == "smoke" and set(trace["union"]) >= set(trace["traced_repo_files"])
    acc = json.loads((study / "artifacts" / "smoke_acceptance.json").read_text(encoding="utf-8"))
    assert acc["checks"]["replay_imports_within_collection_closure"] is True

    outside = sorted(set(plan["closure"]["files"]) - set(plan["closure"]["stages"]["replay"]["files"]))
    escape_mod = "research_workflow.audit_packets_v2"
    assert "research_workflow/audit_packets_v2.py" in outside
    real = V2Lifecycle._run_window

    def escaping(self, *a, **kw):
        sys.modules.pop(escape_mod, None)
        __import__(escape_mod)
        return real(self, *a, **kw)

    monkeypatch.setattr(V2Lifecycle, "_run_window", escaping)
    with pytest.raises(LifecycleV2Error, match="SMOKE_REJECTED: .*replay_imports_within_collection_closure"):
        lc.smoke()
    trace = json.loads((study / "artifacts" / "replay_closure_trace.json").read_text(encoding="utf-8"))
    assert trace["verdict"] == "REPLAY_CLOSURE_ESCAPE" and trace["escapes"] == ["research_workflow/audit_packets_v2.py"]


def test_contract_packet_carries_the_reuse_decision(tmp_path, synthetic_bars):
    from research_workflow.audit_packets_v2 import contract_packet
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); _prepare_and_seal(lc, "a"); lc.collection()
    _spec_path(tmp_path, question="changed text"); plan = _prepare_and_seal(lc, "b")
    preview = lc.partition_reuse_preview("train")
    packet = contract_packet(plan, study_id="reuse_probe", execution_composite="x", dirty_paths=[], test_summary={}, partition_reuse=preview)
    assert packet["partition_reuse"]["declared"] == {"mode": "replay_closure", "shadow": "every_run"}
    assert packet["partition_reuse"]["would_reuse"] == ["train-2029", "train-2030"]
    assert {p["reason"] for p in packet["partition_reuse"]["partitions"]} == {"REUSABLE"}
    bare = contract_packet(plan, study_id="reuse_probe", execution_composite="x", dirty_paths=[], test_summary={})
    assert bare["partition_reuse"]["declared"]["mode"] == "replay_closure"


def test_select_shadow_is_uniform_seeded_and_sampled_policy_skips():
    ids = ["train-2020", "train-2021", "train-2022", "train-2023"]
    picks = {rc.select_shadow(ids, f"seal-{i}", shadow_policy="every_run") for i in range(64)}
    assert picks == set(ids)
    assert rc.select_shadow(ids, "seal-x", shadow_policy="every_run") == rc.select_shadow(ids, "seal-x", shadow_policy="every_run")
    sampled = [rc.select_shadow(ids, f"seal-{i}", shadow_policy="sampled") for i in range(64)]
    assert 0 < sum(1 for s in sampled if s is not None) < 64
    assert rc.select_shadow([], "seal", shadow_policy="every_run") is None


# -- Reading 2: V7 both directions ------------------------------------------------------------------------------
def test_compiler_change_reuses_unless_it_alters_the_plan(tmp_path, synthetic_bars, monkeypatch):
    """The compiler is not replay code: a compiler-module change that leaves the plan's replay content
    unchanged permits reuse; one that changes the plan's replay content is refused through the plan hash."""
    import research_workflow.closure_hash as ch
    import research_workflow.grammar.compiler as comp
    real = ch.hash_file_v2
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); plan1 = _prepare_and_seal(lc, "a"); lc.collection(); before = _shas(study)
    assert "research_workflow/grammar/compiler.py" not in set(plan1["closure"]["stages"]["replay"]["files"])
    assert "research_workflow/grammar/compiler.py" in set(plan1["closure"]["files"])

    def perturb(rel_suffix):
        def fake(path, **kw):
            h = real(path, **kw)
            return ("deadbeef" + h[8:]) if Path(path).as_posix().endswith(rel_suffix) else h
        return fake

    # (a) compiler module "changed", plan content identical: manifest moves, replay key does not -> REUSED
    monkeypatch.setattr(ch, "hash_file_v2", perturb("research_workflow/grammar/compiler.py"))
    plan2 = _prepare_and_seal(lc, "b")
    assert plan2["closure"]["composite_sha256"] != plan1["closure"]["composite_sha256"]
    assert plan2["closure"]["stages"]["replay"]["composite_sha256"] == plan1["closure"]["stages"]["replay"]["composite_sha256"]
    r = lc.collection()
    assert r["partition_reuse"]["reused"] == ["train-2029", "train-2030"] and _shas(study) == before
    monkeypatch.setattr(ch, "hash_file_v2", real)

    # (b) compiler change that alters what the plan says about replay (the warmup fact): REFUSED via the plan hash
    real_warmup = comp._resolve_warmup_and_availability

    def altered(ctx):
        warmup, availability = real_warmup(ctx)
        return {**warmup, "days_before_partition": int(warmup["days_before_partition"]) + 1}, availability

    monkeypatch.setattr(comp, "_resolve_warmup_and_availability", altered)
    plan3 = _prepare_and_seal(lc, "c")
    assert plan3["closure"]["stages"]["replay"]["composite_sha256"] == plan1["closure"]["stages"]["replay"]["composite_sha256"]
    assert plan3["warmup"]["days_before_partition"] == plan1["warmup"]["days_before_partition"] + 1
    assert lc.partition_reuse_preview("train")["would_reuse"] == []
    r = lc.collection()
    assert r["partition_reuse"]["reused"] == []
    assert all("replay_plan_sha256" in x["reason"] for x in _receipt(study)["refused"])


# -- Reading 2: V8 trace halt on a partition run ---------------------------------------------------------------
def test_partition_run_halts_on_a_replay_module_outside_the_key(tmp_path, synthetic_bars, monkeypatch):
    study = _spec_path(tmp_path, chronology={"train": [2030], "dev": [], "prohibited": [], "partition_reuse": "replay_closure", "partition_reuse_shadow": "every_run"})
    lc = _lifecycle(study, synthetic_bars); plan = _prepare_and_seal(lc, "a")
    outside = "research_workflow.audit_packets_v2"
    assert "research_workflow/audit_packets_v2.py" not in set(plan["closure"]["stages"]["replay"]["files"])
    real = V2Lifecycle._run_window

    def escaping(self, *a, **kw):
        sys.modules.pop(outside, None); __import__(outside)
        return real(self, *a, **kw)

    monkeypatch.setattr(V2Lifecycle, "_run_window", escaping)
    out_dir = study / "_work" / "controller" / "partitions" / "train" / "2030"
    with pytest.raises(LifecycleV2Error, match="REPLAY_CLOSURE_ESCAPE"):
        lc.run_partition(2030, "train", out_dir)
    assert not (out_dir / "manifest.json").exists(), "an escaping partition is never persisted"
    trace = json.loads((out_dir / "replay_trace.json").read_text(encoding="utf-8"))
    assert trace["verdict"] == "REPLAY_CLOSURE_ESCAPE" and trace["escapes"] == ["research_workflow/audit_packets_v2.py"]
    with pytest.raises(LifecycleV2Error, match="REPLAY_CLOSURE_ESCAPE"):
        lc.collection()
    monkeypatch.setattr(V2Lifecycle, "_run_window", real)
    assert lc.collection()["status"] == "PASS"
    union = json.loads((study / "artifacts" / "replay_closure_trace.json").read_text(encoding="utf-8"))
    assert [r["kind"] for r in union["runs"]] == ["smoke", "partition"] and (out_dir / "replay_trace.json").is_file()
    assert set(union["union"]) <= set(plan["closure"]["stages"]["replay"]["files"])


def test_reuse_requires_a_clean_smoke_trace_for_the_current_plan(tmp_path, synthetic_bars):
    study = _spec_path(tmp_path)
    lc = _lifecycle(study, synthetic_bars); _prepare_and_seal(lc, "a"); lc.collection()
    _spec_path(tmp_path, question="changed text")
    _prepare_and_seal(lc, "b", smoke=False)          # new plan, no smoke yet
    preview = lc.partition_reuse_preview("train")
    assert preview["would_reuse"] == [] and {p["reason"] for p in preview["partitions"]} == {"NO_CLEAN_SMOKE_TRACE_FOR_PLAN"}
    assert lc.smoke()["status"] == "PASS"
    assert lc.partition_reuse_preview("train")["would_reuse"] == ["train-2029", "train-2030"]


def test_key_binds_replay_time_data_files(tmp_path, synthetic_bars):
    """features/feature_definition_promotions.json is read at replay (registry.resolve_feature_instances via
    provider_host); the frozen manifest hashes .py files only, so the reuse key binds its bytes explicitly."""
    study = _spec_path(tmp_path)
    _lifecycle(study, synthetic_bars).compile()
    plan = load_plan(study)
    part = {"period": "train", "year": 2030, "primary_start": "2030-01-01", "primary_end": "2030-12-31", "run_end": "2030-12-31", "windows": []}
    kw = dict(dataset={"dataset_id": "SYN_A", "logical_digest": None}, partition=part, authorization_sha256="auth", warmup_days=5)
    with_root = rc.replay_closure_binding(plan, repo_root=ROOT, **kw)
    assert with_root["components"]["replay_data_files"]["features/feature_definition_promotions.json"]
    fake = tmp_path / "repo"; (fake / "features").mkdir(parents=True)
    (fake / "features" / "feature_definition_promotions.json").write_text('{"promotions": []}', encoding="utf-8")
    assert rc.replay_closure_binding(plan, repo_root=fake, **kw)["replay_closure_sha256"] != with_root["replay_closure_sha256"]
