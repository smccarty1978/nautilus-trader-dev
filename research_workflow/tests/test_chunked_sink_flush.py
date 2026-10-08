"""Logical equivalence: chunked (bounded-memory) vs unchunked collection on the golden
synthetic fixture, for both an outcome-bearing barrier study and an outcome: none
(descriptive) study. Compares the FULL candidate and observation populations, every field,
every row -- never sampled -- across several small chunked batch sizes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


@pytest.fixture(scope="module")
def synthetic_bars():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    return bars, expected


def _plan(spec_text: str, repo_root: Path):
    from research_workflow.grammar.compiler import compile_study
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    import yaml
    spec = yaml.safe_load(spec_text)
    out = compile_study(spec, repo_root=repo_root, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, (out.gaps.to_dict() if not out.ok else None)
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "compiled_plan.json"
    out.plan.write(tmp)
    return json.loads(tmp.read_text(encoding="utf-8"))


def _run(plan, bars, session, chunked_batch_rows, tmp_path, tag, chunked_batch_bytes=0):
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    table = build_session_table(session)
    if chunked_batch_rows <= 0 and chunked_batch_bytes <= 0:
        run = run_plan_on_bars(plan, bars, session_table=table)
        return run["candidates"], run["observations"], run["stats"]
    from research_workflow.host.chunked_writer import ChunkedParquetWriter
    from research_workflow.host.strategy import plan_output_columns
    cand_cols, obs_cols = plan_output_columns(plan)
    out_dir = tmp_path / tag
    # batch_rows=1 means "every row is its own physical batch unless bytes govern instead" --
    # a big row-threshold combined with a small byte-threshold exercises the BYTES trigger
    # specifically (test_barrier_study_chunked_matches_unchunked_byte_threshold below).
    writer_batch_rows = chunked_batch_rows if chunked_batch_rows > 0 else 1_000_000
    cand_w = ChunkedParquetWriter(out_dir / "candidates.parquet", cand_cols, batch_rows=writer_batch_rows, batch_bytes=chunked_batch_bytes)
    obs_w = ChunkedParquetWriter(out_dir / "observations.parquet", obs_cols, batch_rows=writer_batch_rows, batch_bytes=chunked_batch_bytes)
    run = run_plan_on_bars(plan, bars, session_table=table, chunked_writers=(cand_w, obs_w),
                           chunked_flush_every=writer_batch_rows, chunked_flush_bytes=chunked_batch_bytes)
    cand_m, obs_m = cand_w.finalize(), obs_w.finalize()
    import pandas as pd
    cands = pd.read_parquet(out_dir / "candidates.parquet")
    obs = pd.read_parquet(out_dir / "observations.parquet")
    return cands, obs, run["stats"]


def _assert_frames_equal(unchunked, chunked, label):
    import pandas as pd
    assert list(unchunked.columns) == list(chunked.columns), f"{label}: column order differs"
    assert len(unchunked) == len(chunked), f"{label}: row count differs ({len(unchunked)} vs {len(chunked)})"
    u = unchunked.reset_index(drop=True)
    c = chunked.reset_index(drop=True)
    for col in u.columns:
        pd.testing.assert_series_equal(u[col], c[col], check_dtype=False, check_names=False, obj=f"{label}.{col}")


@pytest.mark.parametrize("batch_rows", [1, 2, 3, 7, 10_000])
def test_barrier_study_chunked_matches_unchunked(tmp_path, synthetic_bars, batch_rows):
    bars, expected = synthetic_bars
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    spec_text = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")
    plan = _plan(spec_text, ROOT)
    unch_c, unch_o, unch_stats = _run(plan, bars, session, 0, tmp_path, "unchunked")
    ch_c, ch_o, ch_stats = _run(plan, bars, session, batch_rows, tmp_path, f"chunked_{batch_rows}")
    assert len(unch_c) > 0 and len(unch_o) > 0, "fixture produced no rows -- test would be vacuous"
    _assert_frames_equal(unch_c, ch_c, "candidates")
    _assert_frames_equal(unch_o, ch_o, "observations")
    assert unch_stats["candidates"] == ch_stats["candidates"]
    assert unch_stats["observations"] == ch_stats["observations"]
    assert unch_stats["pending_at_end"] == ch_stats["pending_at_end"] == 0


def test_barrier_study_chunked_matches_unchunked_byte_threshold(tmp_path, synthetic_bars):
    """Req 1 (byte threshold): flush governed by estimated BYTES, not row count, end-to-end
    through run_plan_on_bars -> HostCore -> CollectionSink -> ColumnarBuffer -> writer -- the
    full population must still match the unchunked run exactly."""
    bars, expected = synthetic_bars
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    spec_text = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")
    plan = _plan(spec_text, ROOT)
    unch_c, unch_o, unch_stats = _run(plan, bars, session, 0, tmp_path, "unchunked_bytes")
    ch_c, ch_o, ch_stats = _run(plan, bars, session, 0, tmp_path, "chunked_bytes", chunked_batch_bytes=256)
    assert len(unch_c) > 0 and len(unch_o) > 0
    _assert_frames_equal(unch_c, ch_c, "candidates")
    _assert_frames_equal(unch_o, ch_o, "observations")
    assert unch_stats["candidates"] == ch_stats["candidates"]
    assert unch_stats["observations"] == ch_stats["observations"]


def _plan_from_spec_dict(spec: dict, repo_root: Path):
    from research_workflow.grammar.compiler import compile_study
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    import tempfile
    out = compile_study(spec, repo_root=repo_root, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, (out.gaps.to_dict() if not out.ok else None)
    tmp = Path(tempfile.mkdtemp()) / "compiled_plan.json"
    out.plan.write(tmp)
    return json.loads(tmp.read_text(encoding="utf-8"))


def test_descriptive_outcome_none_study_chunked_matches_unchunked(tmp_path, synthetic_bars):
    import yaml
    bars, expected = synthetic_bars
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    spec = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    spec["outcome"] = "none"  # descriptive mode: a bare string, see research_workflow/tests/test_outcome_none.py
    spec["population"].pop("direction", None)
    spec["chronology"]["dev"] = []
    plan = _plan_from_spec_dict(spec, ROOT)
    assert plan["outcome"]["kernel"] == "none", "the outcome:none rewrite did not take (fixture text drifted)"
    unch_c, unch_o, unch_stats = _run(plan, bars, session, 0, tmp_path, "unchunked_none")
    ch_c, ch_o, ch_stats = _run(plan, bars, session, 3, tmp_path, "chunked_none")
    assert len(unch_c) > 0
    _assert_frames_equal(unch_c, ch_c, "candidates")
    _assert_frames_equal(unch_o, ch_o, "observations")
