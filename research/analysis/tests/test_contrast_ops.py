"""``analysis.contrast.nominate`` / ``analysis.replication.scorecard`` -- through ``run_op``."""
from __future__ import annotations

import hashlib
import itertools
import json

import numpy as np
import pandas as pd
import pytest

from research.analysis.contrast_ops import benjamini_hochberg
from research.analysis.ops import AnalysisOpError, context_ops, known_ops, run_op

# The requesting study's frozen numbers are CONFIGURATION, passed here as parameters.
GATES = {"min_child_n": 150, "min_parent_n": 300, "min_nominate_n": 300}
MATERIALITY = {"min_abs_difference": 0.05, "min_relative_difference": 0.25, "require_ci_excludes_zero": True, "max_bh_q": 0.10}
REPLICATION = {"min_ratio": 0.5, "min_child_n": 150, "rules": [
    {"class": "UNDERPOWERED", "requires": ["underpowered"]},
    {"class": "REPLICATED", "requires": ["same_sign", "ratio_ge_min", "ci_excludes_zero"]},
    {"class": "DIRECTIONALLY_CONSISTENT", "requires": ["same_sign", "ci_includes_zero"]},
    {"class": "NOT_REPLICATED", "requires": ["ratio_lt_min"]},
    {"class": "NOT_REPLICATED", "requires": ["opposite_sign", "ci_includes_zero"]},
    {"class": "CONTRADICTED", "requires": ["opposite_sign", "ci_excludes_zero"]},
]}


def synth(seed=0, *, days=240, per_day=12, effect=0.25, states=("L|L", "L|S"), flip_sign=False, n_scale=1.0):
    """Synthetic trades: a binary metric whose rate depends on (state, bucket). In state L|L bucket
    'near' carries a large effect; everything else is the base rate."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(days):
        day_shock = rng.normal(0, 0.03)
        for _ in range(int(per_day * n_scale)):
            st = states[rng.integers(len(states))]
            b = ["near", "mid", "far"][rng.integers(3)]
            p = 0.40 + day_shock
            if st == "L|L" and b == "near":
                p += (-effect if flip_sign else effect)
            rows.append({"state": st, "bucket": b, "win": float(rng.random() < min(max(p, 0.0), 1.0)),
                         "reach": float(rng.random() < 0.3), "day": f"2023-{1 + d // 28:02d}-{1 + d % 28:02d}", "excluded": False})
    return pd.DataFrame(rows)


def nominate(frame, **over):
    params = {"parent_by": ["state"], "dimensions": ["bucket"], "metrics": ["win", "reach"], "cluster_column": "day",
              "censored_column": "excluded", "gates": GATES, "materiality": MATERIALITY, "replication": REPLICATION}
    params.update(over)
    return run_op("analysis.contrast.nominate", frame, params=params)


def test_registered_and_context():
    assert {"analysis.contrast.nominate", "analysis.replication.scorecard"} <= known_ops()
    assert "analysis.replication.scorecard" in context_ops() and "analysis.contrast.nominate" not in context_ops()


# ------------------------------------------------------------------------------------------ #
# Benjamini-Hochberg
# ------------------------------------------------------------------------------------------ #
def _bh_reference(p):
    m = len(p)
    order = sorted(range(m), key=lambda i: p[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * m / rank, 1.0)
        q[i] = prev
    return q


def test_bh_matches_textbook_and_statsmodels_style_values():
    p = [0.01, 0.04, 0.03, 0.005, 0.20]
    q = benjamini_hochberg(p)
    assert q == pytest.approx(_bh_reference(p))
    assert q == pytest.approx([0.025, 0.05, 0.05, 0.025, 0.20])


def test_bh_ties_get_identical_q():
    q = benjamini_hochberg([0.02, 0.02, 0.02, 0.5])
    assert q[0] == q[1] == q[2] == pytest.approx(0.02 * 4 / 3)


def test_bh_ordering_invariance():
    p = [0.001, 0.2, 0.03, 0.03, 0.9, 0.049, 0.5]
    base = dict(zip(range(len(p)), benjamini_hochberg(p)))
    for perm in itertools.islice(itertools.permutations(range(len(p))), 200):
        q = benjamini_hochberg([p[i] for i in perm])
        assert {perm[j]: q[j] for j in range(len(p))} == pytest.approx(base)


def test_bh_null_policies():
    p = [0.01, None, 0.02]
    conservative = benjamini_hochberg(p, null_policy="count_as_one")
    exclude = benjamini_hochberg(p, null_policy="exclude")
    assert conservative[1] is None and exclude[1] is None
    assert conservative[0] == pytest.approx(0.01 * 3 / 1) and conservative[2] == pytest.approx(0.02 * 3 / 2)
    assert exclude[0] == pytest.approx(0.02) and exclude[2] == pytest.approx(0.02)
    assert benjamini_hochberg([None, None]) == [None, None]
    with pytest.raises(AnalysisOpError):
        benjamini_hochberg([1.5])


def test_bh_all_pass_none_pass_and_boundary():
    assert all(q <= 0.10 for q in benjamini_hochberg([0.001, 0.002, 0.003]))
    assert all(q > 0.10 for q in benjamini_hochberg([0.5, 0.6, 0.9]))
    # boundary: q exactly at the threshold passes (<=)
    q = benjamini_hochberg([0.05, 0.10])
    assert q == pytest.approx([0.10, 0.10])
    f = synth(1)
    out = nominate(f, materiality={**MATERIALITY, "max_bh_q": 1.0})["frame"]
    tested = out[out["tested"]]
    assert tested["pass_q"].all()


# ------------------------------------------------------------------------------------------ #
# nominate
# ------------------------------------------------------------------------------------------ #
def test_real_effect_is_nominated_and_null_cells_are_not():
    out = nominate(synth(2))
    frame, payload = out["frame"], out["payload"]
    hit = frame[(frame["parent.state"] == "L|L") & (frame["child_value"] == "near") & (frame["metric"] == "win")].iloc[0]
    assert hit["tested"] and hit["material"] and hit["claim_eligible"]
    assert hit["estimate"] > 0 and hit["ci_low"] > 0 and hit["q_value"] <= 0.10
    assert all(c["metric"] == "win" and c["child_value"] == "near" and c["parent"] == {"state": "L|L"} for c in payload["claims"])
    assert len(payload["claims"]) == 1
    # the reach metric carries no effect: never material
    assert not frame[frame["metric"] == "reach"]["material"].any()


def test_frozen_n_gates():
    small = synth(3, days=30, per_day=12)          # ~360 trades: children ~60 per bucket per state -> below 150
    out = nominate(small)
    assert out["frame"]["tested"].sum() == 0
    assert set(out["frame"]["not_tested_reason"]) <= {"CHILD_N_BELOW_MIN", "PARENT_N_BELOW_MIN"}
    assert out["payload"]["claims"] == []
    # a material contrast below min_nominate_n is material but not a claim
    mid = nominate(synth(2), gates={**GATES, "min_nominate_n": 10_000})
    assert mid["frame"]["material"].any() and mid["payload"]["claims"] == []


def test_materiality_gates_each_bind():
    f = synth(2)
    base = nominate(f)["frame"].set_index(["parent_key", "dimension", "child_value", "metric"])
    for key, strict in (("min_abs_difference", 0.99), ("min_relative_difference", 50.0)):
        out = nominate(f, materiality={**MATERIALITY, key: strict})["frame"]
        assert not out["material"].any(), key
    no_ci = nominate(f, materiality={k: v for k, v in MATERIALITY.items() if k != "require_ci_excludes_zero"})["frame"]
    assert "pass_ci" not in no_ci.columns
    assert base["material"].sum() >= 1


def test_significance_alone_never_qualifies():
    # a large sample, a tiny (1pp) but significant effect -> CI excludes 0, fails the 5pp gate
    f = synth(4, days=400, per_day=40, effect=0.01)
    out = nominate(f)["frame"]
    assert not out["material"].any()


def test_parameters_are_not_hard_coded():
    f = synth(2)
    loose = nominate(f, gates={"min_child_n": 1, "min_parent_n": 1, "min_nominate_n": 1},
                     materiality={"max_bh_q": 1.0})["frame"]
    assert loose["tested"].all() and loose["material"].all()


def test_ordering_invariance_of_the_whole_op():
    f = synth(5)
    a = nominate(f)
    b = nominate(f.sample(frac=1.0, random_state=7).reset_index(drop=True))
    assert json.dumps(a["payload"], sort_keys=True) == json.dumps(b["payload"], sort_keys=True)
    cols = ["parent_key", "dimension", "child_value", "metric", "estimate", "q_value", "material"]
    pd.testing.assert_frame_equal(a["frame"][cols], b["frame"][cols], check_exact=False, rtol=1e-12)


def test_not_ranked_by_value():
    out = nominate(synth(2))["frame"]
    keys = list(zip(out["parent_key"], out["dimension"], out["child_value"], out["metric"]))
    assert keys == sorted(keys, key=lambda k: json.dumps(list(k)))   # key order, not effect order


def test_clustered_stat_compatibility_with_clustered_mean():
    """The contrast estimate/SE/CI are exactly analysis.uncertainty.clustered_mean's difference of means."""
    f = synth(6)
    out = nominate(f, gates={"min_child_n": 1, "min_parent_n": 1, "min_nominate_n": 1})["frame"]
    for state, bucket in (("L|L", "near"), ("L|S", "far")):
        g = f.assign(in_child=(f["bucket"] == bucket))
        cm = run_op("analysis.uncertainty.clustered_mean", g, params={
            "value_columns": ["win"], "cluster_column": "day", "censored_column": "excluded",
            "differences": [{"name": "child_minus_rest", "a": {"state": state, "in_child": True},
                             "b": {"state": state, "in_child": False}}]})["payload"]["differences"][0]
        mine = out[(out["parent.state"] == state) & (out["child_value"] == bucket) & (out["metric"] == "win")].iloc[0]
        assert mine["estimate"] == pytest.approx(cm["estimate"], rel=1e-12)
        assert mine["se"] == pytest.approx(cm["se"], rel=1e-10)
        assert (mine["ci_low"], mine["ci_high"]) == pytest.approx((cm["ci_low"], cm["ci_high"]), rel=1e-10)
        assert int(mine["n_clusters"]) == cm["n_clusters"] and int(mine["n_child"]) == cm["n_rows_a"]


def test_precomputed_mode_gates_a_statistics_frame():
    stats = pd.DataFrame([
        {"cell": "a", "child_mean": 0.60, "parent_mean": 0.40, "estimate": 0.22, "se": 0.05, "df": 99, "ci_low": 0.12, "ci_high": 0.32, "n_child": 400, "n_parent": 1000},
        {"cell": "b", "child_mean": 0.42, "parent_mean": 0.40, "estimate": 0.03, "se": 0.05, "df": 99, "ci_low": -0.07, "ci_high": 0.13, "n_child": 400, "n_parent": 1000},
        {"cell": "c", "child_mean": 0.70, "parent_mean": 0.40, "estimate": 0.33, "se": 0.10, "df": 99, "ci_low": 0.13, "ci_high": 0.53, "n_child": 100, "n_parent": 1000},
    ])
    out = run_op("analysis.contrast.nominate", stats, params={"mode": "precomputed", "key_columns": ["cell"], "gates": GATES,
                                                              "materiality": MATERIALITY})
    f = out["frame"].set_index("parent.cell")
    assert bool(f.loc["a", "material"]) and not bool(f.loc["b", "material"])
    assert f.loc["c", "not_tested_reason"] == "CHILD_N_BELOW_MIN"


def test_excluded_child_values_and_censored_rows():
    f = synth(2)
    f.loc[f.index[:50], "excluded"] = True
    out = nominate(f, exclude_child_values=["mid"])["frame"]
    assert "mid" not in set(out["child_value"])
    n_parent = out[out["parent.state"] == "L|L"]["n_parent_rows"].iloc[0]
    assert n_parent == int(((f["state"] == "L|L") & ~f["excluded"]).sum())


def test_invalid_configuration_refused():
    f = synth(2)
    with pytest.raises(AnalysisOpError, match="GATES_INVALID"):
        nominate(f, gates={"min_child_n": 1})
    with pytest.raises(AnalysisOpError, match="max_bh_q"):
        nominate(f, materiality={"min_abs_difference": 0.05})
    with pytest.raises(AnalysisOpError, match="REPLICATION_RULES_INVALID"):
        nominate(f, replication={**REPLICATION, "rules": [{"class": "X", "requires": ["bogus"]}]})
    with pytest.raises(AnalysisOpError, match="CLUSTER_UNDECLARED"):
        nominate(f, cluster_column=None)


# ------------------------------------------------------------------------------------------ #
# scorecard
# ------------------------------------------------------------------------------------------ #
def _freeze(tmp_path, payload):
    path = tmp_path / "artifacts" / "claims_2023.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return "artifacts/claims_2023.json", hashlib.sha256(path.read_bytes()).hexdigest()


def score(tmp_path, rows, rel, sha):
    return run_op("analysis.replication.scorecard", rows, params={"claims_path": rel, "claims_sha256": sha},
                  context={"study_dir": str(tmp_path)})


@pytest.fixture()
def frozen(tmp_path):
    disc = nominate(synth(2))["payload"]
    assert len(disc["claims"]) == 1
    rel, sha = _freeze(tmp_path, disc)
    return disc, rel, sha


def test_scorecard_replicated(tmp_path, frozen):
    disc, rel, sha = frozen
    out = score(tmp_path, synth(20), rel, sha)
    (r,) = out["payload"]["rows"]
    assert r["classification"] == "REPLICATED"
    for k in ("claim_id", "discovery_value", "replication_value", "expected_direction", "support", "classification", "reason"):
        assert k in r
    assert r["expected_direction"] == 1 and r["support"] >= 150


def test_scorecard_contradicted_sign_reversal(tmp_path, frozen):
    _, rel, sha = frozen
    (r,) = score(tmp_path, synth(21, flip_sign=True), rel, sha)["payload"]["rows"]
    assert r["classification"] == "CONTRADICTED" and r["pred.opposite_sign"] and r["pred.ci_excludes_zero"]


def test_scorecard_not_replicated_and_directionally_consistent(tmp_path, frozen):
    _, rel, sha = frozen
    (r,) = score(tmp_path, synth(22, effect=0.0), rel, sha)["payload"]["rows"]
    assert r["classification"] in ("NOT_REPLICATED", "DIRECTIONALLY_CONSISTENT")
    # same sign, CI excludes 0, but |d_rep| < 0.5 |d_disc| -> only NOT_REPLICATED matches
    (r1,) = score(tmp_path, synth(24, effect=0.06, days=40, per_day=30), rel, sha)["payload"]["rows"]
    assert r1["pred.same_sign"] and r1["pred.ci_excludes_zero"] and r1["pred.ratio_lt_min"]
    assert r1["classification"] == "NOT_REPLICATED"
    # same sign, CI includes 0 and ratio < 0.5: the frozen text lets BOTH DIRECTIONALLY_CONSISTENT and
    # NOT_REPLICATED match; the DECLARED rule order decides (first match), never the op
    (r2,) = score(tmp_path, synth(23, effect=0.06, days=40, per_day=30), rel, sha)["payload"]["rows"]
    assert r2["pred.same_sign"] and r2["pred.ci_includes_zero"] and r2["pred.ratio_lt_min"]
    assert r2["classification"] == "DIRECTIONALLY_CONSISTENT" and r2["reason"].startswith("rules[2]")


def test_rule_order_is_configuration(tmp_path):
    rules = list(REPLICATION["rules"])
    swapped = [rules[0], rules[1], rules[3], rules[2], rules[4], rules[5]]
    disc = nominate(synth(2), replication={**REPLICATION, "rules": swapped})["payload"]
    rel, sha = _freeze(tmp_path, disc)
    (r,) = score(tmp_path, synth(23, effect=0.06, days=40, per_day=30), rel, sha)["payload"]["rows"]
    assert r["classification"] == "NOT_REPLICATED"


def test_scorecard_underpowered(tmp_path, frozen):
    _, rel, sha = frozen
    (r,) = score(tmp_path, synth(24, days=20), rel, sha)["payload"]["rows"]
    assert r["classification"] == "UNDERPOWERED" and r["support"] < 150


def test_scorecard_fallback_class_is_retained(tmp_path):
    disc = nominate(synth(2), replication={**REPLICATION, "rules": [{"class": "REPLICATED", "requires": ["same_sign", "ci_excludes_zero"]}]})["payload"]
    rel, sha = _freeze(tmp_path, disc)
    (r,) = score(tmp_path, synth(21, flip_sign=True), rel, sha)["payload"]["rows"]
    assert r["classification"] == "UNCLASSIFIED" and "no rule matched" in r["reason"]


def test_scorecard_refuses_a_changed_claim_file(tmp_path, frozen):
    disc, rel, sha = frozen
    tampered = json.loads((tmp_path / rel).read_text(encoding="utf-8"))
    tampered["replication"]["min_ratio"] = 0.01                      # "change a threshold after seeing 2024"
    (tmp_path / rel).write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(AnalysisOpError, match="HASH_MISMATCH"):
        score(tmp_path, synth(20), rel, sha)


def test_scorecard_cannot_add_or_drop_claims(tmp_path):
    disc = nominate(synth(2), gates={"min_child_n": 1, "min_parent_n": 1, "min_nominate_n": 1},
                    materiality={"max_bh_q": 1.0})["payload"]
    rel, sha = _freeze(tmp_path, disc)
    out = score(tmp_path, synth(30, states=("L|L",)), rel, sha)          # L|S never occurs in "2024"
    ids = [r["claim_id"] for r in out["payload"]["rows"]]
    assert ids == [c["claim_id"] for c in disc["claims"]]               # every claim, in file order, nothing added
    missing = [r for r in out["payload"]["rows"] if json.loads(r["parent_key"]) == {"state": "L|S"}]
    assert missing and all(r["classification"] == "UNDERPOWERED" and r["support"] == 0 for r in missing)
    assert sum(out["payload"]["counts"].values()) == len(disc["claims"])


def test_scorecard_uses_the_frozen_spec_not_parameters(tmp_path, frozen):
    _, rel, sha = frozen
    with pytest.raises(TypeError):
        run_op("analysis.replication.scorecard", synth(20), params={"claims_path": rel, "claims_sha256": sha, "min_ratio": 0.01},
               context={"study_dir": str(tmp_path)})


def test_scorecard_missing_column_is_an_error_not_a_drop(tmp_path, frozen):
    _, rel, sha = frozen
    with pytest.raises(AnalysisOpError, match="missing|MISSING|not"):
        score(tmp_path, synth(20).drop(columns=["bucket"]), rel, sha)


def test_scorecard_path_must_stay_in_the_study(tmp_path, frozen):
    _, _, sha = frozen
    for bad in ("../x.json", str(tmp_path / "artifacts" / "claims_2023.json")):
        with pytest.raises(AnalysisOpError, match="PATH_INVALID"):
            score(tmp_path, synth(20), bad, sha)


def test_discovery_values_are_immutable_in_the_scorecard(tmp_path, frozen):
    disc, rel, sha = frozen
    (r,) = score(tmp_path, synth(21, flip_sign=True), rel, sha)["payload"]["rows"]
    assert r["discovery_value"] == disc["claims"][0]["discovery"]["estimate"]
    assert r["discovery_ci_low"] == disc["claims"][0]["discovery"]["ci_low"]


def test_several_parent_specs_form_one_bh_family(tmp_path):
    """Every state vs the pooled population AND every bucket vs its state: ONE family, one BH."""
    f = synth(2)
    both = nominate(f, parent_by=[], dimensions=[], contrasts=[{"parent_by": [], "dimensions": ["state"]},
                                                              {"parent_by": ["state"], "dimensions": ["bucket"]}])
    only_l2 = nominate(f)
    fb, f2 = both["frame"], only_l2["frame"]
    assert both["payload"]["summary"]["family_size"] > only_l2["payload"]["summary"]["family_size"]
    assert set(fb["parent_by"]) == {"[]", '["state"]'}
    # the p-values of the shared contrasts are identical; their q-values reflect the larger family
    key = ["parent_key", "dimension", "child_value", "metric"]
    j = fb.merge(f2, on=key, suffixes=("_both", "_l2"))
    assert len(j) == len(f2)
    assert np.allclose(j["p_value_both"].astype(float), j["p_value_l2"].astype(float), equal_nan=True)
    tested = fb[fb["tested"]]
    expect = benjamini_hochberg([None if pd.isna(p) else float(p) for p in tested["p_value"]])
    assert np.allclose(tested["q_value"].astype(float), np.array(expect, dtype=float), equal_nan=True)
    # claims from either block are scored with their own parent specification
    rel, sha = _freeze(tmp_path, both["payload"])
    rows = score(tmp_path, synth(20), rel, sha)["payload"]["rows"]
    assert [r["claim_id"] for r in rows] == [c["claim_id"] for c in both["payload"]["claims"]]
    with pytest.raises(AnalysisOpError, match="AMBIGUOUS"):
        nominate(f, contrasts=[{"parent_by": [], "dimensions": ["state"]}])


def test_frame_common_matches_diagnostic_ops():
    """The session-day cluster (and the column/scalar helpers) mean the same thing in every op."""
    from research.analysis import diagnostic_ops as D, frame_common as F
    ts = pd.Series([1_700_000_000 * 10**9 + k * 3_600 * 10**9 for k in range(0, 24 * 9, 5)] + [None], dtype="Int64")
    assert F.globex_trading_day(ts).equals(D.globex_trading_day(ts))
    fr = pd.DataFrame({"t": ts, "c": list(range(len(ts)))})
    assert F.cluster_keys(fr, None, "t", "x").equals(D._cluster_keys(fr, None, "t", "x"))
    assert F.cluster_keys(fr, "c", None, "x").equals(D._cluster_keys(fr, "c", None, "x"))
    for v in (np.int64(3), np.float64("nan"), 2.5, "s", None):
        assert F.scalar(v) == D._scalar(v) or (F.scalar(v) is None and D._scalar(v) is None)
    for fn in (F.cluster_keys, D._cluster_keys):
        with pytest.raises(AnalysisOpError, match="CLUSTER_UNDECLARED"):
            fn(fr, None, None, "x")
    with pytest.raises(AnalysisOpError, match="ANALYSIS_COLUMN_MISSING"):
        F.require_columns(fr, ["zz"], "x")
