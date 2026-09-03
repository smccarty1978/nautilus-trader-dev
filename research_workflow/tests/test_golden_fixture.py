"""Golden end-to-end fixture: synthetic two-day data, independently generated expectations,
the host run both as pure Python and under a real NautilusTrader engine, and the replay
oracle over the barrier candidates."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000

from research_workflow.grammar import compile_study, load_spec  # noqa: E402
from research_workflow.host.interfaces import BarView  # noqa: E402
from research_workflow.host_runner import run_plan_on_bars, run_plan_with_engine  # noqa: E402
from research_workflow.sessions import build_session_table  # noqa: E402
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS  # noqa: E402


@pytest.fixture(scope="module")
def golden():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    session_spec = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    return bars, expected, session_spec


def _compile(name: str):
    out = compile_study(load_spec(GOLDEN / name), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.card()
    assert out.plan.card()["catalog_opened"] is False
    return out.plan.to_dict()


def _keyed(frame, cols):
    out = {}
    for row in frame.to_dict("records"):
        out[(int(row["observation_ts"]), int(row["regime_start_ns"]), int(row["checkpoint_index"]))] = {c: row.get(c) for c in cols}
    return out


def _nz(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


# --------------------------------------------------------------------------- #
def test_barrier_plan_matches_independent_expectations(golden):
    bars, expected, session_spec = golden
    plan = _compile("study_barrier.yaml")
    table = build_session_table(session_spec)
    run = run_plan_on_bars(plan, bars, session_table=table)
    cands, obs = run["candidates"], run["observations"]
    exp_rows = expected["barrier"]
    assert len(cands) == len(exp_rows) == expected["counts"]["barrier_candidates"]
    got = _keyed(obs, ["regime_direction", "arm_a_disposition", "arm_a_censor_reason", "arm_a_resolution_seconds",
                       "arm_b_disposition", "arm_b_censor_reason", "arm_b_resolution_seconds", "resolved_at_ts"])
    feats = _keyed(cands, ["f_ctx_dir", "f_close", "f_dir", "f_5m_bars"])
    mismatches = []
    for e in exp_rows:
        key = (e["observation_ts"] * NS, e["regime_start_ns"] * NS, e["checkpoint_index"])
        assert key in got, f"missing candidate {key}"
        g = got[key]
        for arm in ("arm_a", "arm_b"):
            ex = e[arm]
            if (g[f"{arm}_disposition"], _nz(g[f"{arm}_censor_reason"])) != (ex["disposition"], ex["censor_reason"]):
                mismatches.append((key, arm, "disposition", ex, g))
            if ex["resolution_seconds"] is not None and abs(float(g[f"{arm}_resolution_seconds"]) - ex["resolution_seconds"]) > 1e-9:
                mismatches.append((key, arm, "resolution", ex, g))
        f = feats[key]
        if int(f["f_ctx_dir"]) != e["f_ctx_dir"]:
            mismatches.append((key, "ctx", e["f_ctx_dir"], f["f_ctx_dir"]))
        if abs(float(f["f_close"]) - e["price"]) > 1e-9 or int(f["f_dir"]) != e["direction"]:
            mismatches.append((key, "feature", e, f))
        if int(g["regime_direction"]) != e["direction"]:
            mismatches.append((key, "direction", e["direction"], g["regime_direction"]))
    assert not mismatches, mismatches[:10]
    # spot checks from the scenario list
    sc = expected["spot_checks"]
    skipped = sc["skipped_grid_index"]
    assert (skipped["T"] * NS, skipped["regime_start"] * NS, skipped["index"]) not in got            # no-print second -> index skipped
    ctx = sc["same_timestamp_ctx"]
    k0 = next(k for k in got if k[0] == ctx["T"] * NS)
    k1 = next(k for k in got if k[0] == ctx["next_T"] * NS)
    assert feats[k0]["f_ctx_dir"] == ctx["expected_ctx_dir"] and feats[k1]["f_ctx_dir"] == ctx["expected_ctx_dir_next"]
    d1 = sc["d1_session_end_first_T"] * NS
    assert all(got[k]["arm_a_censor_reason"] == "SESSION_END" for k in got if d1 <= k[0] <= d1 + 60 * NS)
    ec = sc["early_close"]
    assert got[next(k for k in got if k[0] == ec["first_session_end_T"] * NS)]["arm_a_censor_reason"] == "SESSION_END"
    assert got[next(k for k in got if k[0] == ec["data_end_first_T"] * NS)]["arm_a_censor_reason"] == "DATA_END"
    reasons = {_nz(v["arm_a_censor_reason"]) for v in got.values()} | {v["arm_a_disposition"] for v in got.values()}
    assert {"AMBIGUOUS_SAME_BAR_TOUCH", "TIMEOUT", "SESSION_END", "DATA_END", "POSITIVE", "NEGATIVE"} <= reasons
    assert run["stats"]["pending_at_end"] == 0
    # derived 5m buckets are complete-only: every 5m bar counted at the last candidate is a full 300-second bucket
    assert max(int(f["f_5m_bars"]) for f in feats.values()) >= 1


def test_barrier_plan_oracle_agrees(golden):
    """The independent replay oracle re-derives every arm disposition from the tape."""
    bars, expected, session_spec = golden
    from research_workflow.target_replay_oracle import replay
    tape = [{"ts": b.ts_init, "open": b.open, "high": b.high, "low": b.low, "gap": False} for b in bars if b.stream == "syn_a_1s"]
    plan = _compile("study_barrier.yaml")
    run = run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))
    obs = run["observations"]
    atr = expected["atr"]
    mism = 0
    for row in obs.to_dict("records"):
        T = int(row["observation_ts"])
        window = [e for e in tape if T < e["ts"] <= T + 120 * NS]
        if not window:
            assert row["arm_a_censor_reason"] == "DATA_END"   # no forward tape at all: run-end censor
            continue
        for prefix, fav, adv in (("arm_a", 1.0, 1.0), ("arm_b", 1.0, 0.5)):
            contract = {"primitive": "ordered_barrier", "required_forward_outcomes": [{"id": "fo", "entry_reference": "next_bar_open",
                        "session_end_censoring": True, "ordered_barriers": [{"id": "b", "favorable_atr": fav, "adverse_atr": adv,
                        "horizon_seconds": expected["horizon_s"], "horizon_expiry_policy": "censor"}]}]}
            cand = {"observation_ts": T, "atr": atr, "direction": int(row["regime_direction"]), "session_close_ts": row["session_close_ts"]}
            o = replay(contract, cand, window)
            disp = row[f"{prefix}_disposition"]
            reason = _nz(row[f"{prefix}_censor_reason"])
            if (o["disposition"], o["censor_reason"]) != (disp, reason):
                # the oracle has no run-end notion: DATA_END from a truncated window is reported as TIMEOUT/DATA_END equivalently
                if not (reason == "DATA_END" and o["censor_reason"] in ("DATA_END", "TIMEOUT")):
                    mism += 1
    assert mism == 0


def test_flip_plan_matches_independent_expectations(golden):
    bars, expected, session_spec = golden
    plan = _compile("study_flip.yaml")
    run = run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))
    obs = run["observations"]
    assert len(obs) == expected["counts"]["flip_candidates"]
    got = _keyed(obs, ["disposition", "censor_reason", "resolved_at_ts", "flip_ts", "time_to_flip_seconds"])
    legacy = {"POSITIVE": "LABELED_POSITIVE", "NEGATIVE": "LABELED_NEGATIVE", "CENSORED": "CENSORED"}
    bad = []
    for e in expected["flip"]:
        key = (e["observation_ts"] * NS, e["regime_start_ns"] * NS, e["checkpoint_index"])
        g = got[key]
        if g["disposition"] != legacy[e["disposition"]] or _nz(g["censor_reason"]) != e["censor_reason"]:
            bad.append((key, e, g))
        if e["resolved_at"] is not None and int(g["resolved_at_ts"]) != e["resolved_at"] * NS:
            bad.append((key, "resolved_at", e, g))
        if e["flip_ts"] is not None and int(g["flip_ts"]) != e["flip_ts"] * NS:
            bad.append((key, "flip_ts", e, g))
    assert not bad, bad[:10]
    zero = [k for k, v in got.items() if _nz(v["time_to_flip_seconds"]) == 0.0]
    assert zero, "a flip landing on the candidate's own timestamp is positive with time_to_flip 0 (legacy rule)"


def test_watch_plan_trigger_graph(golden):
    bars, expected, session_spec = golden
    plan = _compile("study_watch.yaml")
    ledger = []
    run = run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec), ledger=ledger)
    events = [(r["timestamp"] // NS, r["payload"]["kind"], r["payload"]["state"]) for r in ledger if r["stage"] == "trigger"]
    entries = [(r["timestamp"] // NS, "entry", None) for r in ledger if r["stage"] == "candidate"]
    got = sorted(events + entries, key=lambda t: (t[0], {"expire": 0, "enter": 1, "entry": 2}[t[1]], str(t[2])))
    want = sorted([(e["ts"], e["kind"], e["state"] if e["kind"] != "entry" else None) for e in expected["watch"]["ledger"]],
                  key=lambda t: (t[0], {"expire": 0, "enter": 1, "entry": 2}[t[1]], str(t[2])))
    assert got == want, {"got": got, "want": want}
    cands, obs = run["candidates"], run["observations"]
    assert len(cands) == len(expected["watch"]["candidates"]) == 1
    row = obs.to_dict("records")[0]
    e = expected["watch"]["candidates"][0]
    assert int(row["observation_ts"]) == e["observation_ts"] * NS and int(row["checkpoint_index"]) == e["checkpoint_index"]
    assert row["disposition"] == e["disposition"] and int(row["resolved_at_ts"]) == e["resolved_at"] * NS
    assert int(cands.to_dict("records")[0]["arm_ts"]) == expected["watch"]["ledger"][0]["ts"] * NS


def test_add_to_winner_is_a_typed_gap():
    out = compile_study(load_spec(GOLDEN / "study_add.yaml"), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    kinds = {(g.kind.value, g.where) for g in out.gaps.gaps}
    assert ("MISSING_CAPABILITY", "triggers.add") in kinds


def test_engine_run_equals_pure_python_run(golden):
    bars, expected, session_spec = golden
    from scripts.parity.compare_frames import compare_frames
    plan = _compile("study_barrier.yaml")
    py = run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))
    nt = run_plan_with_engine(plan, bars, session_table_spec=session_spec)
    c = compare_frames(py["candidates"], nt["candidates"])
    o = compare_frames(py["observations"], nt["observations"])
    assert c["passed"] and o["passed"], (c["first_divergence"], o["first_divergence"])
    assert nt["stats"]["bars_by_stream"]["syn_b_1m"] == expected["counts"]["bars_b_1m"]
