"""OOS access latch (G1) and OOS reconcile gate (G2) -- research_workflow.oos_access + lifecycle_v2.

Regression for the HV1 synthetic proof: N2 (decision thresholds loosened AFTER the held-out period was opened
re-sealed, re-froze, RE-COLLECTED OOS and flipped the class) and N8 (a TRAIN-year row inside the OOS partition,
manifest hashes recomputed, was analysed). Synthetic golden fixture: TRAIN 2029-2030, OOS 2031 (whole-day copies
of the golden D1 session), model none, a one-step declared analysis whose threshold is the "decision rule".
"""
from __future__ import annotations

import json
import multiprocessing as mp
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from research_workflow import oos_access
from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options, load_plan

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS, DAY = 1_000_000_000, 86_400
OFFSETS = {2029: [-1, 0], 2030: [2], 2031: [367, 368]}   # day copies of golden D1 (2029-12-31 = offset 0)
DELAY = {-1: 300, 0: 0, 2: 150, 367: 450, 368: 60}         # distinct session starts -> distinct rows per copy
SID = "oos_latch_probe"


class _Bars:
    def __init__(self) -> None:
        subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
        from research_workflow.host.interfaces import BarView
        raw = json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))
        exp = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
        d1, d2 = exp["seconds_base"]["D1"], exp["seconds_base"]["D2"]
        day1 = [b for b in raw if d1 * NS <= int(b["ts_event"]) < d2 * NS]
        out = [b for b in raw if int(b["ts_event"]) >= d2 * NS]
        (a1, b1), (a2, b2) = exp["sessions"]
        rows = [[a2 * NS, b2 * NS]]
        for offs in OFFSETS.values():
            for k in offs:
                sh = k * DAY * NS
                out += [{**b, "ts_event": int(b["ts_event"]) + sh, "ts_init": int(b["ts_init"]) + sh} for b in day1]
                rows.append([(a1 + DELAY[k]) * NS + sh, b1 * NS + sh])
        out.sort(key=lambda b: (int(b["ts_init"]), int(b["ts_event"])))
        self.bars = [BarView(**b) for b in out]
        self.ts = np.array([int(b.ts_event) for b in self.bars])
        self.session = {"kind": "calendar", "session": "RTH", "rows": sorted(rows)}
        self.calls: list = []
        self.fail_oos_once = False

    def source(self, start, end):
        lo, hi = int(pd.Timestamp(start, tz="UTC").value), int(pd.Timestamp(end, tz="UTC").value) + DAY * NS
        self.calls.append((str(start), str(end), self._study_record_exists()))
        if pd.Timestamp(end).year >= 2031 and self.fail_oos_once:
            self.fail_oos_once = False
            raise RuntimeError("SIMULATED_INTERRUPTION during the held-out replay")
        i, j = np.searchsorted(self.ts, lo, "left"), np.searchsorted(self.ts, hi, "left")
        return self.bars[i:j]

    study: Path | None = None

    def _study_record_exists(self) -> bool:
        return bool(self.study and (self.study / "artifacts" / oos_access.RECORD_NAME).exists())

    def oos_reads(self):
        return [c for c in self.calls if pd.Timestamp(c[1]).year >= 2031]


@pytest.fixture(scope="module")
def bars():
    return _Bars()


def _analysis(threshold: int = 30, column: str = "checkpoint_index") -> dict:
    return {"source": "oos",
            "steps": [{"id": "cls", "op": "analysis.classify.precedence", "rows": "frame",
                       "params": {"output_column": "decision", "rules": [{"label": "ABOVE", "when": [[column, "gte", threshold]]},
                                                                         {"label": "BELOW", "when": []}]}}],
            "artifacts": [{"name": "latch_decision.parquet", "source": "cls", "kind": "frame"}]}


def _write_spec(study: Path, *, dev=(2031,), analysis=None) -> None:
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = SID
    body["chronology"] = {"train": [2029, 2030], "dev": list(dev), "prohibited": [], "authorized_dates": ["2029-12-31"]}
    body["analysis"] = analysis or _analysis()
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")


def _lc(study: Path, bars: _Bars, **extra) -> V2Lifecycle:
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    bars.study = study
    opts = V2Options(execute=True, smoke_date="2029-12-31", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=bars.source, session_table_spec=bars.session, in_process_partitions=True, **extra)
    return V2Lifecycle(study, repo_root=ROOT, options=opts)


def _clear_audits(study: Path) -> None:
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))["frozen_execution_composite_sha256"]
    for name, kind in (("status.json", "causal"), ("contract_status.json", "contract")):
        (study / "audit" / name).write_text(json.dumps({"verdict": "CLEAR", "audited_execution_composite_sha256": frozen,
                                                         "auditor": f"{kind}-synthetic", "audit_report_sha256": "0" * 64}), encoding="utf-8")


def _through_seal(lc: V2Lifecycle) -> None:
    lc.compile(); lc.prepare(); _clear_audits(lc.study); lc.seal()


@pytest.fixture(scope="module")
def frozen_template(tmp_path_factory, bars):
    """One study through TRAIN freeze (OOS never opened); every test works on its own copy."""
    root = tmp_path_factory.mktemp("latch_template")
    study = root / "studies" / SID
    _write_spec(study)
    lc = _lc(study, bars)
    _through_seal(lc)
    lc.collection(); lc.reconcile(); lc.merge(); lc.fit(); lc.freeze()
    return study


@pytest.fixture()
def study(tmp_path, frozen_template, bars):
    dest = tmp_path / "studies" / SID
    shutil.copytree(frozen_template, dest)
    bars.calls.clear(); bars.fail_oos_once = False
    return dest


def _refused(fn, code: str) -> str:
    with pytest.raises(LifecycleV2Error) as err:
        fn()
    assert str(err.value).startswith(code), str(err.value)
    return str(err.value)


def _files(study: Path) -> dict:
    out = {}
    for p in sorted((study / "_work" / "controller" / "partitions" / "oos").rglob("*")) + [study / "artifacts" / oos_access.RECORD_NAME,
                                                                                            study / "artifacts" / oos_access.COMPLETION_NAME]:
        if p.is_file():
            out[p.relative_to(study).as_posix()] = p.read_bytes()
    return out


def _opened(study: Path, bars: _Bars) -> V2Lifecycle:
    lc = _lc(study, bars)
    r = lc.oos()
    assert r["oos_access"]["opening"] == "FIRST_OPENING"
    return lc


def _amend(study: Path, bars: _Bars, **spec) -> V2Lifecycle:
    _write_spec(study, **spec)
    lc = _lc(study, bars)
    lc.compile()
    return lc


# -- positive ------------------------------------------------------------------------------------------
def test_first_opening_recorded_before_any_held_out_bar_and_analysis_repeats_without_collection(study, bars):
    lc = _opened(study, bars)
    reads = bars.oos_reads()
    assert reads and all(rec_exists for _, _, rec_exists in reads), "every held-out bar request happened after the record existed"
    rec = oos_access.read_record(study / "artifacts")
    assert rec["identity"]["plan_sha256"] == load_plan(study)["plan_sha256"] and rec["identity"]["year_roles"]["oos"] == [2031]
    done = oos_access.read_completion(study / "artifacts")
    assert done["identity_sha256"] == rec["identity_sha256"] and set(done["partitions"]) == {"2031"}
    assert json.loads((study / "_work/controller/oos_reconcile.json").read_text(encoding="utf-8"))["passed"] is True
    before, n_reads = _files(study), len(bars.oos_reads())
    for _ in range(2):
        assert lc.analyze()["status"] == "PASS"
    assert lc.oos()["oos_access"]["opening"] == "RESUMED_UNDER_RECORDED_IDENTITY"
    assert _files(study) == before and len(bars.oos_reads()) == n_reads, "repeat analysis/oos never re-collects or rewrites evidence"


def test_resume_after_interruption_keeps_the_original_opening(study, bars):
    lc = _lc(study, bars)
    bars.fail_oos_once = True
    with pytest.raises(Exception, match="SIMULATED_INTERRUPTION"):
        lc.oos()
    rec = oos_access.read_record(study / "artifacts")
    assert rec is not None and oos_access.read_completion(study / "artifacts") is None
    _refused(lc.analyze, "OOS_COLLECTION_INCOMPLETE")
    r = lc.oos()
    assert r["oos_access"] == {"opening": "RESUMED_UNDER_RECORDED_IDENTITY", "identity_sha256": rec["identity_sha256"],
                               "opened_at_utc": rec["opened_at_utc"]}
    assert oos_access.read_record(study / "artifacts")["record_sha256"] == rec["record_sha256"]
    assert lc.analyze()["status"] == "PASS"


# -- negative: post-OOS amendments ---------------------------------------------------------------------
@pytest.mark.parametrize("amendment", [{"analysis": _analysis(threshold=1)},                         # decision threshold loosened
                                       {"analysis": _analysis(column="regime_start_ns", threshold=0)}],  # treatment redefined
                         ids=["threshold", "treatment"])
def test_post_oos_amendment_is_refused_at_every_stage_and_evidence_is_untouched(study, bars, amendment):
    _opened(study, bars)
    evidence, n_reads = _files(study), len(bars.oos_reads())
    lc = _amend(study, bars, **amendment)
    lc.prepare(); _clear_audits(study)
    msg = _refused(lc.seal, "OOS_IDENTITY_CONFLICT")
    assert "plan_sha256" in msg and "analysis_spec_sha256" in msg
    refusal = json.loads((study / "_work/controller" / oos_access.REFUSAL_NAME).read_text(encoding="utf-8"))
    assert refusal["code"] == "OOS_IDENTITY_CONFLICT" and refusal["stage"] == "seal"
    _refused(lc.freeze, "OOS_IDENTITY_CONFLICT")
    _refused(lc.analyze, "OOS_IDENTITY_CONFLICT")
    with pytest.raises(LifecycleV2Error):
        lc.oos()
    assert _files(study) == evidence and len(bars.oos_reads()) == n_reads


def test_reseal_cannot_reset_the_latch(study, bars):
    """Even a seal written outside seal() (forged for the amended plan) leaves oos/analyze refused."""
    _opened(study, bars)
    lc = _amend(study, bars, analysis=_analysis(threshold=1))
    lc.prepare(); _clear_audits(study)
    seal = json.loads((study / "artifacts/preexec_audit_seal.json").read_text(encoding="utf-8"))
    seal.update(plan_sha256=load_plan(study)["plan_sha256"], composite_seal_hash="f" * 64)
    (study / "artifacts/preexec_audit_seal.json").write_text(json.dumps(seal), encoding="utf-8")
    _refused(lc.analyze, "OOS_IDENTITY_CONFLICT")
    with pytest.raises(LifecycleV2Error):
        lc.oos()


def test_interrupted_opening_cannot_resume_under_a_different_plan(study, bars):
    lc = _lc(study, bars)
    bars.fail_oos_once = True
    with pytest.raises(Exception, match="SIMULATED_INTERRUPTION"):
        lc.oos()
    lc = _amend(study, bars, analysis=_analysis(threshold=1))
    lc.prepare(); _clear_audits(study)
    _refused(lc.seal, "OOS_IDENTITY_CONFLICT")
    _refused(lc.analyze, "OOS_IDENTITY_CONFLICT")


def test_changing_oos_years_is_refused(study, bars):
    _opened(study, bars)
    lc = _amend(study, bars, dev=(2031, 2032))
    lc.prepare()
    msg = _refused(lc.analyze, "OOS_IDENTITY_CONFLICT")
    assert "year_roles" in msg and "authorization_sha256" in msg


def test_unauthorized_year_request_is_refused(study, bars):
    _refused(_lc(study, bars, years=[2032]).oos, "YEARS_NOT_AUTHORIZED")
    assert not bars.oos_reads()


# -- negative: evidence replacement / removal ----------------------------------------------------------
@pytest.mark.parametrize("tamper", ["delete_manifest", "delete_partition", "recollect"])
def test_replacing_or_deleting_held_out_evidence_is_refused_without_recollection(study, bars, tamper):
    lc = _opened(study, bars)
    d = study / "_work/controller/partitions/oos/2031"
    n_reads = len(bars.oos_reads())
    if tamper == "delete_manifest":
        (d / "manifest.json").unlink()
    elif tamper == "delete_partition":
        shutil.rmtree(d)
    else:  # a second collection's bytes, internally consistent with a rewritten manifest
        c = pd.read_parquet(d / "candidates.parquet").iloc[1:]
        o = pd.read_parquet(d / "observations.parquet").iloc[1:]
        c.to_parquet(d / "candidates.parquet", index=False); o.to_parquet(d / "observations.parquet", index=False)
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        from research_workflow.lifecycle_v2 import _sha
        m.update(candidates_sha256=_sha(d / "candidates.parquet"), observations_sha256=_sha(d / "observations.parquet"))
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    _refused(lc.oos, "OOS_EVIDENCE_ALTERED")
    _refused(lc.analyze, "OOS_EVIDENCE_ALTERED")
    assert len(bars.oos_reads()) == n_reads, "the held-out period was not collected a second time"


def test_deleting_the_access_record_is_refused(study, bars):
    lc = _opened(study, bars)
    (study / "artifacts" / oos_access.RECORD_NAME).unlink()
    _refused(lc.oos, "OOS_ACCESS_RECORD_MISSING")
    _refused(lc.analyze, "OOS_ACCESS_RECORD_MISSING")
    # deleting the partitions as well still leaves the completion record: the latch does not reopen
    shutil.rmtree(study / "_work/controller/partitions/oos")
    _refused(lc.oos, "OOS_ACCESS_RECORD_MISSING")


def test_tampered_access_record_is_refused(study, bars):
    lc = _opened(study, bars)
    p = study / "artifacts" / oos_access.RECORD_NAME
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["identity"]["plan_sha256"] = load_plan(study)["plan_sha256"][::-1]
    p.write_text(json.dumps(rec), encoding="utf-8")
    _refused(lc.analyze, "OOS_ACCESS_RECORD_CORRUPT")


# -- negative: OOS population integrity (G2) -----------------------------------------------------------
def _inject_during_collection(lc: V2Lifecycle, monkeypatch, mutate) -> None:
    """A defective/forged collection: the partition and its manifest hashes agree, the rows do not."""
    from research_workflow.lifecycle_v2 import _sha
    real = lc._collect_period

    def collect(period):
        out = real(period)
        d = lc.work / "partitions" / "oos" / "2031"
        c, o = mutate(pd.read_parquet(d / "candidates.parquet"), pd.read_parquet(d / "observations.parquet"))
        c.to_parquet(d / "candidates.parquet", index=False); o.to_parquet(d / "observations.parquet", index=False)
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        m.update(candidates_sha256=_sha(d / "candidates.parquet"), observations_sha256=_sha(d / "observations.parquet"))
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        return out
    monkeypatch.setattr(lc, "_collect_period", collect)


def _shift_ts(frame: pd.DataFrame, days: int) -> pd.DataFrame:
    f = frame.copy()
    for col in [x for x in f.columns if x.endswith("_ts") or x in ("observation_ts", "regime_start_ns")]:
        if pd.api.types.is_integer_dtype(f[col]):
            f[col] = f[col] - days * DAY * NS
    return f


@pytest.mark.parametrize("defect,finding", [
    ("train_year_row", "rows outside the primary year"),
    ("duplicate_key", "duplicate candidate keys"),
    ("orphan_observation", "candidate keys != observation keys"),
], ids=["N8_train_year_row", "duplicate_key", "key_mismatch"])
def test_oos_partition_population_defects_are_refused(study, bars, monkeypatch, defect, finding):
    lc = _lc(study, bars)
    if defect == "train_year_row":       # one 2031 row moved into 2029 (a TRAIN year), in both files
        mutate = lambda c, o: (pd.concat([c, _shift_ts(c.iloc[[0]], 400)], ignore_index=True),
                               pd.concat([o, _shift_ts(o.iloc[[0]], 400)], ignore_index=True))
    elif defect == "duplicate_key":
        mutate = lambda c, o: (pd.concat([c, c.iloc[[0]]], ignore_index=True), pd.concat([o, o.iloc[[0]]], ignore_index=True))
    else:
        mutate = lambda c, o: (c, _shift_ts(o, 0).assign(checkpoint_index=o["checkpoint_index"] + 10_000))
    _inject_during_collection(lc, monkeypatch, mutate)
    msg = _refused(lc.oos, "OOS_RECONCILE_FAILED")
    assert finding in msg
    assert oos_access.read_completion(study / "artifacts") is None, "defective evidence is never pinned"
    rec = json.loads((study / "_work/controller/oos_reconcile.json").read_text(encoding="utf-8"))
    assert rec["passed"] is False and any(finding in f for f in rec["findings"])
    _refused(_lc(study, bars).analyze, "OOS_COLLECTION_INCOMPLETE")


# -- concurrency: the opening gate itself --------------------------------------------------------------
def _race(artifacts: str, identity: dict, barrier, out) -> None:
    barrier.wait()
    try:
        out.put(oos_access.open_access(Path(artifacts), identity, held_out_evidence_present=False)["opening"])
    except oos_access.OOSAccessRefused as exc:
        out.put(exc.code)


@pytest.mark.parametrize("same_identity", [False, True], ids=["conflicting", "identical"])
def test_two_processes_racing_the_opening_gate(tmp_path, same_identity):
    ctx = mp.get_context("spawn")
    for i in range(5):
        art = tmp_path / f"a{i}"
        art.mkdir()
        barrier, out = ctx.Barrier(2), ctx.Queue()
        ids = [{"plan_sha256": "a"}, {"plan_sha256": "a" if same_identity else "b"}]
        procs = [ctx.Process(target=_race, args=(str(art), ids[k], barrier, out)) for k in range(2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        results = sorted(out.get(timeout=5) for _ in procs)
        loser = "RESUMED_UNDER_RECORDED_IDENTITY" if same_identity else "OOS_IDENTITY_CONFLICT"
        assert results == sorted(["FIRST_OPENING", loser]), results
        assert oos_access.read_record(art) is not None
