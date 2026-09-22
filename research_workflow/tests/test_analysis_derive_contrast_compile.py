"""Compiler + pipeline integration of analysis.derive.columns / contrast.nominate / replication.scorecard.

The production compiler proves, before execution, that every derive expression references only columns the
plan provides (identity + metadata + features + observation + ``_year``) or columns derived earlier, and the
production pipeline (``research_workflow.analysis_pipeline.run_pipeline``) executes the compiled steps over
the golden fixture's real collected frame.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from research_workflow.host.interfaces import BarView

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


def _outcome(o):
    o["event"] = "regime.flipped"
    o["composition"] = "OR"
    o["session_end"] = "truncate"
    o["entry_observation"] = True


DERIVE = {"id": "atlas", "op": "analysis.derive.columns", "params": {
    "keep": "checkpoint_index == 0 or checkpoint_index > 0",
    "columns": [
        {"name": "sd_{arm}", "expr": "f_dir * (executable_entry_price - f_close) / regime_atr_proxy", "each": {"arm": ["x"]}},
        {"name": "has_entry", "expr": "not_null(executable_entry_price)"},
        {"name": "bucket", "expr": "where(is_null(sd_x), 'NULL', cut(sd_x, [-0.5, 0, 0.5], ['<-0.5', '[-0.5,0)', '[0,0.5)', '>=0.5']))"},
        {"name": "win", "expr": "where(is_null(terminal_gross_pnl_points), null, where(terminal_gross_pnl_points > 0, 1, 0))"},
        {"name": "arm_a_hit", "expr": "where(arm_a_label == 1, 1, 0)"},
        {"name": "excluded", "expr": "is_null(executable_entry_price)"},
        {"name": "state", "expr": "where(f_dir == 1, 'L', 'S')"},
    ]}}


def _analysis(steps, artifacts):
    return {"source": "train", "steps": steps, "artifacts": artifacts}


def _compile(tmp_path, name, analysis, *, derive_atr="1.0"):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = name
    _outcome(body["outcome"])
    analysis = json.loads(json.dumps(analysis).replace("regime_atr_proxy", derive_atr))
    body["analysis"] = analysis
    study = tmp_path / "studies" / name
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS), study


def _gaps(out):
    return json.dumps(out.card())


def test_derive_compiles_and_the_closure_carries_its_modules(tmp_path):
    out, _ = _compile(tmp_path, "d_ok", _analysis([DERIVE], [{"name": "atlas.parquet", "source": "atlas", "kind": "frame"}]))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    assert "analysis.derive.columns" in plan["analysis"]["ops"]
    assert "research/analysis/derive_ops.py" in plan["closure"]["files"]
    assert "research/analysis/expressions.py" in plan["closure"]["files"], "the grammar is imported by the op; the closure must see it"


def test_derive_referencing_a_column_the_plan_lacks_is_refused(tmp_path):
    bad = copy.deepcopy(DERIVE)
    bad["params"]["columns"].append({"name": "leak", "expr": "future_price_after_exit - f_close"})
    out, _ = _compile(tmp_path, "d_bad", _analysis([bad], [{"name": "a.parquet", "source": "atlas", "kind": "frame"}]))
    assert not out.ok and "future_price_after_exit" in _gaps(out) and "DERIVE_COLUMN_UNKNOWN" in _gaps(out)


def test_derive_syntax_and_function_errors_are_compile_gaps(tmp_path):
    for expr, code in (("__import__('os')", "FUNCTION_UNKNOWN"), ("os.system", "EXPRESSION_SYNTAX"), ("exp(f_close)", "FUNCTION_UNKNOWN"), ("f_close +", "EXPRESSION_SYNTAX")):
        bad = copy.deepcopy(DERIVE)
        bad["params"]["columns"] = [{"name": "x", "expr": expr}]
        out, _ = _compile(tmp_path, "d_syn", _analysis([bad], [{"name": "a.parquet", "source": "atlas", "kind": "frame"}]))
        assert not out.ok and code in _gaps(out), expr


def test_derive_over_a_summary_is_provable_and_over_an_opaque_op_is_refused(tmp_path):
    describe = {"id": "summary", "op": "analysis.describe.grouped", "rows": "atlas",
                "params": {"value_columns": ["win"], "group_by": ["state"], "cluster_ts_column": "observation_ts"}}
    wilson = {"id": "wilson", "op": "analysis.derive.columns", "rows": "summary",
              "params": {"columns": [{"name": "lo", "expr": "(mean + 1.96 * 1.96 / (2 * n)) - 1.96 * sqrt(mean * (1 - mean) / n)"}]}}
    out, _ = _compile(tmp_path, "d_sum", _analysis([DERIVE, describe, wilson], [{"name": "w.parquet", "source": "wilson", "kind": "frame"}]))
    assert out.ok, out.card()
    nominate = {"id": "nom", "op": "analysis.contrast.nominate", "rows": "atlas", "params": {
        "parent_by": ["state"], "dimensions": ["bucket"], "metrics": ["win"], "cluster_ts_column": "observation_ts",
        "gates": {"min_child_n": 1, "min_parent_n": 1, "min_nominate_n": 1}, "materiality": {"max_bh_q": 1.0}}}
    after = {"id": "after", "op": "analysis.derive.columns", "rows": "nom", "params": {"columns": [{"name": "x", "expr": "estimate * 2"}]}}
    out2, _ = _compile(tmp_path, "d_opaque", _analysis([DERIVE, nominate, after], [{"name": "x.parquet", "source": "after", "kind": "frame"}]))
    assert not out2.ok and "provable at compile time" in _gaps(out2)


def test_nominate_naming_a_missing_column_is_refused(tmp_path):
    nominate = {"id": "nom", "op": "analysis.contrast.nominate", "rows": "atlas", "params": {
        "contrasts": [{"parent_by": ["state"], "dimensions": ["no_such_bucket"]}], "metrics": ["win"],
        "cluster_ts_column": "observation_ts", "gates": {"min_child_n": 1, "min_parent_n": 1, "min_nominate_n": 1},
        "materiality": {"max_bh_q": 1.0}}}
    out, _ = _compile(tmp_path, "n_bad", _analysis([DERIVE, nominate], [{"name": "c.json", "source": "nom", "kind": "json"}]))
    assert not out.ok and "no_such_bucket" in _gaps(out)


@pytest.fixture(scope="module")
def golden():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    session_spec = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    return bars, session_spec


def _frame(plan, golden_):
    """The analysis frame exactly as lifecycle_v2._train_frame_all_labels builds it."""
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    bars, session_spec = golden_
    r = run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))
    c, o = r["candidates"], r["observations"]
    key = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    frame = c.merge(o.drop(columns=[x for x in o.columns if x in c.columns and x not in key]), on=key, how="inner")
    frame["_year"] = pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year
    return frame


def test_pipeline_executes_derive_nominate_then_pinned_scorecard_on_the_golden_frame(tmp_path, golden):
    from research_workflow.analysis_pipeline import run_pipeline
    nominate = {"id": "nom", "op": "analysis.contrast.nominate", "rows": "atlas", "params": {
        "contrasts": [{"parent_by": [], "dimensions": ["state"]}, {"parent_by": ["state"], "dimensions": ["bucket"]}],
        "metrics": ["arm_a_hit"], "cluster_ts_column": "observation_ts", "censored_column": "excluded",
        "gates": {"min_child_n": 1, "min_parent_n": 1, "min_nominate_n": 1}, "materiality": {"max_bh_q": 1.0},
        "replication": {"min_ratio": 0.5, "min_child_n": 1, "rules": [
            {"class": "UNDERPOWERED", "requires": ["underpowered"]},
            {"class": "REPLICATED", "requires": ["same_sign", "ratio_ge_min", "ci_excludes_zero"]}]}}}
    arts = [{"name": "atlas.parquet", "source": "atlas", "kind": "frame"}, {"name": "claims.json", "source": "nom", "kind": "json"},
            {"name": "tests.parquet", "source": "nom", "kind": "frame"}]
    out, study = _compile(tmp_path, "e2e_disc", _analysis([DERIVE, nominate], arts))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    frame = _frame(plan, golden)
    assert "executable_entry_price" in frame.columns and frame["executable_entry_price"].notna().any()
    ran = run_pipeline(plan["analysis"]["steps"], plan["analysis"]["artifacts"], {"frame": frame},
                       out_dir=study / "artifacts", context={"study_dir": str(study)})
    atlas = pd.read_parquet(study / "artifacts" / "atlas.parquet")
    assert len(atlas) == len(frame) and {"sd_x", "bucket", "state"} <= set(atlas.columns)
    claims = json.loads((study / "artifacts" / "claims.json").read_text(encoding="utf-8"))
    assert claims["kind"] == "analysis.contrast.nominate" and claims["summary"]["n_contrasts"] > 0
    sha = hashlib.sha256((study / "artifacts" / "claims.json").read_bytes()).hexdigest()
    sc = {"id": "score", "op": "analysis.replication.scorecard", "rows": "atlas",
          "params": {"claims_path": "artifacts/claims.json", "claims_sha256": sha}}
    out2, study2 = _compile(tmp_path, "e2e_rep", _analysis([DERIVE, sc], [{"name": "card.json", "source": "score", "kind": "json"}]))
    assert out2.ok, out2.card()
    (study2 / "artifacts").mkdir(parents=True, exist_ok=True)
    (study2 / "artifacts" / "claims.json").write_bytes((study / "artifacts" / "claims.json").read_bytes())
    plan2 = out2.plan.to_dict()
    run_pipeline(plan2["analysis"]["steps"], plan2["analysis"]["artifacts"], {"frame": _frame(plan2, golden)},
                 out_dir=study2 / "artifacts", context={"study_dir": str(study2)})
    card = json.loads((study2 / "artifacts" / "card.json").read_text(encoding="utf-8"))
    assert [r["claim_id"] for r in card["rows"]] == [c["claim_id"] for c in claims["claims"]]
    assert ran["steps"][0]["rows_out"] == len(frame)


def test_existing_plans_without_derive_compile_unchanged(tmp_path):
    """A plan whose analysis uses only pre-existing ops gets no new gap from the column proof."""
    describe = {"id": "summary", "op": "analysis.describe.grouped",
                "params": {"value_columns": ["f_close"], "group_by": ["no_such_column_is_not_checked_here"], "cluster_ts_column": "observation_ts"}}
    out, _ = _compile(tmp_path, "legacy", _analysis([describe], [{"name": "s.json", "source": "summary", "kind": "json"}]))
    assert out.ok, out.card()
