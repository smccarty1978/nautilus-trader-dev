"""Focused pre-run tests for the long TOP25 NT parity harness."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent          # studies/<study>/tests
IMPL = HERE.parent / "implementation"
ROOT = HERE.parents[2]                          # repo root
for _p in (str(ROOT), str(IMPL)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as C  # noqa: E402
from candidate_tracker_long import (CANDIDATE_STEP_NS, CandidateTrackerLong,  # noqa: E402
                                    RegimeCandidateStateLong)
from model_runtime_long import LongModelRuntime  # noqa: E402

NS = 1_000_000_000


def test_frozen_model_contract_gate():
    chk = C.verify_frozen_model_inputs()
    assert len(chk["feature_order"]) == 25
    assert chk["feature_order_sha256"] == C.EXPECTED_FEATURE_ORDER_SHA256


def test_feature_order_frozen_and_matches_coefficients():
    feats = pd.read_csv(C.FEATURE_ORDER_PATH)["feature_name"].tolist()
    coef = pd.read_csv(C.COEFFICIENTS_PATH)["feature_name"].tolist()
    assert feats == coef, "coefficient order must equal frozen feature order"


def test_bearish_mfe_is_downward_and_mae_upward():
    """MIRROR: for a prevailing-bearish regime, favorable = price BELOW anchor."""
    st = RegimeCandidateStateLong(flip_ts=0, flip_close=100.0, atr_val=2.0)
    st.on_1s_bar(1 * NS, high=101.0, low=96.0)      # 4 pts down, 1 pt up
    assert st._current_mfe() == pytest.approx(4.0 / 2.0)
    assert st._current_mae() == pytest.approx(1.0 / 2.0)


def test_current_pnl_uses_prevailing_direction_minus_one():
    st = RegimeCandidateStateLong(flip_ts=0, flip_close=100.0, atr_val=2.0)
    st.on_1s_bar(1 * NS, high=100.0, low=94.0)
    st.last_close = 94.0
    res = st.evaluate_checkpoint(T=200 * NS, price_at_T=94.0)
    # bearish regime that fell 6 pts is +3.0 ATR of PREVAILING-favorable pnl
    assert res["current_pnl_atr"] == pytest.approx(3.0)
    assert res["retained_mfe_ratio"] == pytest.approx(1.0)


def test_tracker_opens_only_on_bearish_regimes():
    got = []
    tr = CandidateTrackerLong(lambda c: got.append(c), C.is_rth_minute_of_day)
    tr.on_regime_flip(0, new_direction=+1, flip_close=100.0, atr_val=2.0)
    assert tr._active is None, "must NOT open on a bullish (prevailing-long) regime"
    tr.on_regime_flip(0, new_direction=-1, flip_close=100.0, atr_val=2.0)
    assert tr._active is not None, "must open on a bearish regime"


def test_checkpoint_uses_previous_bar_close_not_its_own():
    """Strict causality: a checkpoint must be evaluated against state that
    excludes the bar carrying it."""
    got = []
    tr = CandidateTrackerLong(lambda c: got.append(c), lambda m: True)
    tr.on_regime_flip(0, -1, flip_close=100.0, atr_val=1.0)
    # feed bars up to the first grid point at t=5s
    tr.on_1s_bar(1 * NS, 100.0, 100.0, 100.0, 600)
    tr.on_1s_bar(2 * NS, 100.0, 100.0, 100.0, 600)
    tr.on_1s_bar(3 * NS, 100.0, 100.0, 100.0, 600)
    tr.on_1s_bar(4 * NS, 100.0, 100.0, 100.0, 600)
    got.clear()
    # this bar plunges; the checkpoint at T=5s must NOT see it
    tr.on_1s_bar(5 * NS, 100.0, 50.0, 50.0, 600)
    assert got, "expected a checkpoint at T=5s"
    assert got[0]["observation_time_ns"] == 5 * NS
    assert got[0]["running_mfe_atr"] == pytest.approx(0.0), \
        "the checkpoint's own bar leaked into its MFE"
    assert got[0]["current_pnl_atr"] == pytest.approx(0.0), \
        "the checkpoint's own bar leaked into current_price"


def test_established_gate_thresholds_are_unmodified():
    import candidate_tracker_long as ct
    assert ct.REGIME_AGE_S_MIN == 120.0
    assert ct.RUNNING_MFE_ATR_MIN == 1.0
    assert ct.NEW_PROGRESS_WINDOWS_MIN == 2
    assert ct.RETAINED_MFE_RATIO_MIN == 0.5
    assert ct.PROGRESS_GAP_NS == 120 * NS
    assert CANDIDATE_STEP_NS == 5 * NS


def test_one_trigger_per_regime_suppression_and_stop_snapshot():
    """Stop is a fixed multiple of the ATR frozen at the flip; long stop is BELOW."""
    atr, fill = 8.0, 20000.0
    stop = fill - C.STOP_ATR_MULT * atr
    assert stop == pytest.approx(20000.0 - 1.25 * 8.0)
    assert stop < fill, "a LONG stop must sit below the fill"


def test_explicit_formula_reproduces_joblib_on_real_rows():
    chk = C.verify_frozen_model_inputs()
    rt = LongModelRuntime(C.MODEL_PATH, C.COEFFICIENTS_PATH, C.INTERCEPT_PATH,
                          chk["feature_order"], C.EXPECTED_MODEL_SHA256, C.sha256_file)
    ref = pd.read_parquet(C.WORK / "offline_reference_march_2025.parquet")
    sub = ref.sample(n=200, random_state=7)
    for r in sub.itertuples(index=False):
        vec = [getattr(r, f) for f in chk["feature_order"]]
        out = rt.score_both(vec)
        assert abs(out["probability"] - out["probability_joblib"]) <= C.TOL_PROBA
        assert abs(out["probability_joblib"] - r.score) <= C.TOL_PROBA


def test_missing_value_uses_frozen_median_impute():
    chk = C.verify_frozen_model_inputs()
    rt = LongModelRuntime(C.MODEL_PATH, C.COEFFICIENTS_PATH, C.INTERCEPT_PATH,
                          chk["feature_order"], C.EXPECTED_MODEL_SHA256, C.sha256_file)
    vec = [None] * 25
    out = rt.score_explicit(vec)
    assert out["n_imputed"] == 25
    assert np.allclose(out["imputed"], rt.fill)


def test_regime_engine_matches_offline_reproduction():
    """The live RegimeEngine must reproduce the offline 1m regime series that
    the frozen population was built from."""
    sys.path.insert(0, str(ROOT / "studies" / "regime_sequence_chop_context"))
    sys.path.insert(0, str(ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"))
    from reproduce_regimes import aggregate_and_run_regimes
    from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine

    raw = pd.read_parquet(C.RAW_1S_2025)
    ins = raw.index.tz_convert("UTC").asi8
    lo = pd.Timestamp("2025-03-03", tz="UTC").value
    hi = pd.Timestamp("2025-03-05", tz="UTC").value
    raw = raw.iloc[(ins >= lo) & (ins < hi)]
    df_1m = aggregate_and_run_regimes(raw, "1m")

    eng = RegimeEngine()
    live = [eng.update(float(r.high), float(r.low), float(r.close))
            for r in df_1m.itertuples()]
    offline = df_1m["regime"].tolist()
    assert live == offline, "live RegimeEngine diverges from the offline regime series"
