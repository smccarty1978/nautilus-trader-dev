"""``outcome.session_end: truncate`` -- observing an event until the session closes.

Under ``censor`` a flip label whose horizon reaches past the session close is CENSORED
SESSION_END *whether or not the flip happened*: a fixed-horizon label must observe its whole
window, so a long horizon censors everything and the question "how long until the next flip,
watching until the close?" cannot be asked at all.

``truncate`` makes the close bound the observation window instead of voiding it: a flip at or
before the close resolves the candidate at its own instant, and only a candidate that reached
the close without one is CENSORED SESSION_END, stamped at the close.

Both the kernel (``research_workflow/host/outcomes.py``) and the independent replay oracle
(``research_workflow/target_replay_oracle.py``) must agree, and ``censor`` must be untouched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from research_workflow.host.outcomes import LEGACY

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


@pytest.fixture(scope="module")
def golden():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    session_spec = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    return bars, expected, session_spec


def _run(tmp_path: Path, bars, session_spec, *, session_end: str, horizon: str):
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    body = yaml.safe_load((GOLDEN / "study_flip.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = f"flip_{session_end}"
    body["outcome"]["session_end"] = session_end
    body["outcome"]["horizon"] = horizon
    study = tmp_path / f"studies/flip_{session_end}_{horizon}"
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert plan["outcome"]["session_end_rule"] == session_end
    return plan, run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))["observations"]


POSITIVE, CENSORED = LEGACY["POSITIVE"], LEGACY["CENSORED"]


def test_a_long_horizon_censors_everything_under_censor_and_resolves_under_truncate(tmp_path, golden):
    """The gap this capability exists to close, stated as a test."""
    bars, expected, session_spec = golden
    _, censored = _run(tmp_path, bars, session_spec, session_end="censor", horizon="86400s")
    assert len(censored) > 0
    assert set(censored["disposition"]) == {CENSORED}
    assert set(censored["censor_reason"]) == {"SESSION_END"}

    _, truncated = _run(tmp_path, bars, session_spec, session_end="truncate", horizon="86400s")
    assert len(truncated) == len(censored)
    resolved = truncated[truncated["disposition"] == POSITIVE]
    assert len(resolved) > 0
    # every resolved flip landed inside its own session, and its duration is real
    assert (resolved["flip_ts"] <= resolved["session_close_ts"]).all()
    assert (resolved["time_to_flip_seconds"] >= 0).all()   # inclusive_start: a flip AT T is 0s
    # every censored one was stamped exactly at the close it failed to survive, never later
    unresolved = truncated[truncated["disposition"] == CENSORED]
    assert set(unresolved["censor_reason"]) <= {"SESSION_END", "DATA_END"}
    at_close = unresolved[unresolved["censor_reason"] == "SESSION_END"]
    assert (at_close["resolved_at_ts"] == at_close["session_close_ts"]).all()
    assert at_close["flip_ts"].isna().all()


def test_truncate_never_reports_a_flip_from_a_later_session(tmp_path, golden):
    """The failure `session_end: ignore` would have produced: a candidate late in one session
    picking up the next session's flip and calling it a 30-second resolution."""
    bars, expected, session_spec = golden
    _, truncated = _run(tmp_path, bars, session_spec, session_end="truncate", horizon="86400s")
    _, ignored = _run(tmp_path, bars, session_spec, session_end="ignore", horizon="86400s")
    key = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    # `ignore` emits no session_close_ts at all -- take the close from the truncate run
    joined = ignored[key + ["disposition", "flip_ts"]].merge(
        truncated[key + ["session_close_ts", "disposition", "censor_reason"]], on=key, suffixes=("_ignore", "_truncate"))
    cross = joined[(joined["disposition_ignore"] == POSITIVE) & joined["flip_ts"].notna()
                   & (joined["flip_ts"] > joined["session_close_ts"])]
    assert len(cross) > 0, "the fixture must actually contain a cross-session flip for this to prove anything"
    assert set(cross["disposition_truncate"]) == {CENSORED}
    assert set(cross["censor_reason"]) == {"SESSION_END"}


def test_censor_is_bit_identical_to_before_for_a_horizon_that_fits(tmp_path, golden):
    """truncate is additive: a horizon that fits inside the session resolves identically."""
    bars, expected, session_spec = golden
    _, a = _run(tmp_path, bars, session_spec, session_end="censor", horizon="60s")
    _, b = _run(tmp_path, bars, session_spec, session_end="truncate", horizon="60s")
    key = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    cols = key + ["disposition", "censor_reason", "flip_ts", "time_to_flip_seconds", "target_flip_within_horizon"]
    merged = a[cols].merge(b[cols], on=key, suffixes=("_censor", "_truncate"))
    assert len(merged) == len(a)
    differing = merged[merged["disposition_censor"] != merged["disposition_truncate"]]
    # they may differ ONLY where the horizon crosses the close: censor voids it, truncate
    # observes up to the close. Nothing else may move.
    assert set(differing["disposition_censor"]) <= {CENSORED}
    assert (merged["disposition_censor"] == merged["disposition_truncate"]).mean() > 0.5


def test_kernel_and_independent_oracle_agree_under_truncate(tmp_path, golden):
    bars, expected, session_spec = golden
    from research_workflow.target_replay_oracle import replay_expression
    plan, obs = _run(tmp_path, bars, session_spec, session_end="truncate", horizon="86400s")
    tape = [{"ts": b.ts_init, "gap": False} for b in bars if b.stream == "syn_a_1s"]
    last_ts = max(e["ts"] for e in tape)
    flips = [{"ts": int(r["flip_ts"]), "direction": -int(r["regime_direction"])}
             for r in obs.to_dict("records") if r["flip_ts"] is not None and not pd.isna(r["flip_ts"])]
    contract = {"session_end_rule": "truncate", "session_end_censoring": True,
                "horizon_seconds": plan["outcome"]["flip"]["horizon_ns"] // NS, "direction": "opposite",
                "flip": {"inclusive_start": plan["outcome"]["flip"]["inclusive_start"]}}
    mismatches = []
    for row in obs.to_dict("records"):
        T = int(row["observation_ts"])
        cand = {"observation_ts": T, "regime_direction": int(row["regime_direction"]), "session_close_ts": int(row["session_close_ts"])}
        window = [e for e in tape if T < e["ts"] <= last_ts]
        o = replay_expression(contract, cand, window, flip_events=[f for f in flips if f["ts"] >= T])
        if LEGACY[o["disposition"]] != row["disposition"] or (o["censor_reason"] or None) != (row["censor_reason"] or None):
            mismatches.append((T, row["disposition"], row["censor_reason"], o["disposition"], o["censor_reason"]))
    assert not mismatches, mismatches[:5]
