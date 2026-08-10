from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from studies.full_trade_path_builder.implementation.phase_b_adapter import (
    ExactFastHGBProbability, FrozenBearishScorer, LeanBullishAdapter,
    LeanStrictLongFeatureEngine, vector_sha256,
)
from studies.nt_long_top25_march2025_runtime_parity.implementation.long_feature_engine import (
    LongFeatureEngine,
)
from studies.full_trade_path_builder.implementation.phase_b_strategy import PrevailingDomain
from studies.full_trade_path_builder.implementation.phase_a_runtime import FrozenBullishScorer
from studies.full_trade_path_builder.implementation.phase_a_runtime import load_frozen_adapter
from studies.full_trade_path_builder.implementation.phase_a_core import SourceProvenance
from studies.full_trade_path_builder.implementation.run_phase_b_collect import add_labels
from studies.full_trade_path_builder.implementation.finalize_phase_b_labels import finalize
from studies.nt_live_scoring_infra_prereqs.tests.test_coincident_bar_ordering import (
    T0, _run_and_get_coincident_arrivals,
)

ROOT = Path(__file__).resolve().parents[3]
NS = 1_000_000_000


def test_bearish_frozen_probability_fixture():
    artifact = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2"
    scorer = FrozenBearishScorer(artifact)
    fixture = pq.read_table(artifact / "validation_fixture.parquet", columns=scorer.features).slice(0, 100)
    got = scorer.model.predict_proba(fixture.to_pandas().to_numpy())[:, 1]
    expected = np.load(artifact / "validation_fixture_scores.npy")[:100]
    np.testing.assert_array_equal(got, expected)
    fast = ExactFastHGBProbability(scorer.model)
    fast_got = np.asarray([fast.probability(row) for row in fixture.to_pandas().to_numpy()])
    np.testing.assert_array_equal(fast_got, expected)


def test_bullish_fast_tree_traversal_is_bit_exact():
    artifact = ROOT / "studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2"
    scorer = FrozenBullishScorer(artifact)
    rng = np.random.default_rng(20250724)
    vectors = rng.normal(size=(100, len(scorer.features)))
    vectors[::7, ::5] = np.nan
    expected = scorer.model.predict_proba(vectors)[:, 1]
    fast = ExactFastHGBProbability(scorer.model)
    got = np.asarray([fast.probability(row) for row in vectors])
    np.testing.assert_array_equal(got, expected)


def test_vector_hash_is_little_endian_float64():
    import hashlib
    values = [1.0, -2.5, 0.0]
    assert vector_sha256(values) == hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def test_domain_direction_symmetry():
    bull = PrevailingDomain(1, 0, 100.0, 10.0)
    bear = PrevailingDomain(-1, 0, 100.0, 10.0)
    for sec, bh, bl, sh, sl in (
        (1, 111, 100, 100, 89),
        (122, 112, 105, 95, 88),
    ):
        bull.update(sec * NS, bh, bl)
        bear.update(sec * NS, sh, sl)
    b = bull.snapshot(125 * NS, 106.0)
    s = bear.snapshot(125 * NS, 94.0)
    assert b["running_mfe_atr"] == s["running_mfe_atr"]
    assert b["current_progress_atr"] == s["current_progress_atr"]
    assert b["established_regime_gate"] == s["established_regime_gate"]


def test_horizon_specific_censoring_400s_before_boundary():
    t = 1_000 * NS
    row = {"checkpoint_decision_ns": t}
    out = add_labels(row, [], [], t + 400 * NS)
    assert out["label_300_is_right_censored"] is False
    assert out["label_600_is_right_censored"] is True
    assert out["label_is_right_censored"] is True
    assert out["next_bullish_flip_le_300"] is False
    assert out["next_bullish_flip_le_600"] is None


def test_same_time_flip_excluded_and_horizon_inclusive():
    t = 1_000 * NS
    out = add_labels(
        {"checkpoint_decision_ns": t},
        [t, t + 300 * NS],
        [t + 600 * NS],
        t + 601 * NS,
    )
    assert out["seconds_to_next_bullish_confirm_flip"] == 300
    assert out["next_bullish_flip_le_300"] is True
    assert out["next_bearish_flip_le_600"] is True


def test_nt_equal_time_dispatch_is_1s_then_1m():
    arrivals = _run_and_get_coincident_arrivals(T0, reverse_add_order=False)
    assert [kind for _, kind in arrivals] == ["1s", "1m"]


def test_phase_b_runner_structurally_uses_causal_add_order():
    source = (
        ROOT / "studies/full_trade_path_builder/implementation/run_phase_b_collect.py"
    ).read_text(encoding="utf-8")
    body = source[source.index("def add_bars_causal_order"):source.index("def next_after")]
    assert body.index("engine.add_data(bars_1s)") < body.index("engine.add_data(bars_1m)")


def test_global_finalizer_rejects_incomplete_partition_set(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match="exact 60-month"):
        finalize(tmp_path)


def test_lean_bear_engine_exactly_matches_full_engine_for_top25():
    artifact = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2"
    features = FrozenBearishScorer(artifact).features
    full = LongFeatureEngine(features, lambda _: True)
    lean = LeanStrictLongFeatureEngine(features, lambda _: True)
    for index in range(2_000):
        price = 100 + index * 0.001
        args = (
            index * NS, price, price + 0.5, price - 0.5, price + 0.1,
            10.0, -1, 5.0,
        )
        full.update_1s(*args)
        lean.update_1s(*args)
    expected = full.ordered_vector(1_999 * NS, 2_000 * NS, 102.1, 5.0, -1, 5.0)
    actual = lean.ordered_vector(1_999 * NS, 2_000 * NS, 102.1, 5.0, -1, 5.0)
    assert actual == expected


def test_lean_bull_projection_exactly_matches_frozen_adapter():
    artifact = ROOT / "studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2"
    full = load_frozen_adapter(artifact)
    lean = LeanBullishAdapter(full)
    for index in range(2_000):
        price = 100 + index * 0.001
        args = (index * NS, price, price + 0.5, price - 0.5, price + 0.1, 10.0)
        full.engine.update_1s(*args)
        if (index + 1) % 60 == 0:
            full.engine.update_1m(
                (index + 1) * NS, price - 0.1, price + 0.5,
                price - 0.5, price + 0.1, True,
            )
    provenance = SourceProvenance(1_999 * NS, 2_000 * NS, None, None)
    expected = full.snapshot(2_000 * NS, 102.1, 5.0, provenance)
    actual = lean.snapshot(2_000 * NS, 102.1, 5.0, provenance)
    np.testing.assert_array_equal(actual[0], expected[0])
    assert actual[1:] == expected[1:]
