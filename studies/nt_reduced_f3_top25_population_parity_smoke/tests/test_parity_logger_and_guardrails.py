"""Remaining required test items: candidate-key uniqueness, 2026 access
prohibition, deterministic hashing, snapshot immutability of logged rows."""
from __future__ import annotations

import re
import sys
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1] / "implementation"
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

from parity_logger import ParityLogger  # noqa: E402


def test_candidate_key_uniqueness_within_a_run():
    logger = ParityLogger()
    logger.log_candidate(
        regime_start_ns=100, regime_direction=1, checkpoint_index=0, observation_time_ns=105,
        established_regime_gate=True, regime_age_s=5.0, running_mfe_atr=1.0, running_mae_atr=0.0,
        current_pnl_atr=1.0, new_progress_windows=2, retained_mfe_ratio=1.0,
        decision_rth=True, fill_rth=True, fill_ts=105, fill_px=100.0, atr_at_entry=1.0,
        valid_fill=True, final_candidate_eligible=True,
        feature_values={"f1": 1.0}, null_mask={"f1": False}, score=0.5, r5_trigger=True,
        r2_5_trigger=False, suppression_reason=None)
    logger.log_candidate(
        regime_start_ns=100, regime_direction=1, checkpoint_index=1, observation_time_ns=110,
        established_regime_gate=True, regime_age_s=10.0, running_mfe_atr=1.5, running_mae_atr=0.0,
        current_pnl_atr=1.5, new_progress_windows=2, retained_mfe_ratio=1.0,
        decision_rth=True, fill_rth=True, fill_ts=110, fill_px=101.0, atr_at_entry=1.0,
        valid_fill=True, final_candidate_eligible=True,
        feature_values={"f1": 1.5}, null_mask={"f1": False}, score=0.6, r5_trigger=True,
        r2_5_trigger=False, suppression_reason=None)
    df = logger.to_dataframe()
    keys = list(zip(df["regime_start_ns"], df["checkpoint_index"]))
    assert len(keys) == len(set(keys)), "duplicate candidate keys within a single run"


def test_logged_row_immutable_after_log_candidate_returns():
    """A row appended to ParityLogger must not change if the caller mutates
    the dict it passed in afterward (feature_values/null_mask especially)."""
    logger = ParityLogger()
    feats = {"f1": 1.0}
    logger.log_candidate(
        regime_start_ns=1, regime_direction=1, checkpoint_index=0, observation_time_ns=5,
        established_regime_gate=True, regime_age_s=5.0, running_mfe_atr=1.0, running_mae_atr=0.0,
        current_pnl_atr=1.0, new_progress_windows=2, retained_mfe_ratio=1.0,
        decision_rth=True, fill_rth=True, fill_ts=5, fill_px=100.0, atr_at_entry=1.0,
        valid_fill=True, final_candidate_eligible=True,
        feature_values=feats, null_mask={"f1": False}, score=0.5, r5_trigger=True,
        r2_5_trigger=False, suppression_reason=None)
    feats["f1"] = 999.0  # mutate the caller's own dict after logging
    df = logger.to_dataframe()
    assert df.iloc[0]["feat__f1"] == 1.0, "logged row was not immutable to caller-side mutation"


def test_2026_path_access_prohibition():
    """No implementation script actually opens a 2026-year data file."""
    pattern = re.compile(r'(read_parquet|read_csv|open)\s*\([^)]*2026[^)]*\)', re.IGNORECASE)
    impl_files = list(IMPL.glob("*.py"))
    assert impl_files
    for f in impl_files:
        text = f.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        assert not matches, f"{f.name} appears to open a 2026 data file: {matches}"


def test_run_nt_load_end_hardcoded_to_2025():
    text = (IMPL / "run_nt.py").read_text(encoding="utf-8")
    assert '"2025-12-31' in text
    assert "2026" not in text


def test_on_candidate_uses_live_engine_atr_not_frozen_atr_val():
    """Regression guard, SUPERSEDES an earlier (wrong) version of this test.
    Component-level validation (replaying RegimeEngine from raw 1m bars,
    sampling .atr at each checkpoint's own observation_time) reproduced the
    offline reference's per-row atr_at_entry EXACTLY (0.0 diff) -- proving
    that column is actually a live, per-checkpoint quantity (documented in
    attach_features.py as "== atr_at_checkpoint", sourced from
    CODEX_5_X_build_repaired_atlas.py's `out["atr_at_checkpoint"] =
    out["atr"]`), NOT the frozen established-gate atr_at_entry that
    entry_surface.py hard-asserts constant per regime (that frozen value is
    a DIFFERENT quantity, used only internally by CandidateTracker's own
    MFE/MAE tracking). strategy.py's _on_candidate must therefore read
    self._engine.atr LIVE for the feature vector / stop sizing / logged
    atr_at_entry field, not the frozen c["atr_val"]. Exactly two reads of
    self._engine.atr are expected in the whole file: the flip-time freeze
    passed to on_regime_flip (CandidateTracker's own internal use), and this
    live per-checkpoint read in _on_candidate."""
    text = (IMPL / "strategy.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    reads = [m.start() for m in re.finditer(r"self\._engine\.atr\b", code_text)]
    assert len(reads) == 2, (
        f"expected exactly two self._engine.atr reads (flip-time freeze for "
        f"on_regime_flip, and the live per-checkpoint read in _on_candidate "
        f"assigned to `atr`), found {len(reads)}")
    assert "on_regime_flip(" in code_text[reads[0] - 80: reads[0] + 20]
    assert re.search(r"atr\s*=\s*self\._engine\.atr\b", code_text[reads[1] - 20: reads[1] + 20]), (
        "second self._engine.atr read must be assigned directly to `atr` in _on_candidate")


def test_on_regime_flip_uses_prev_close_gate_anchor_not_bar_open_or_close():
    """Regression guard for a real bug found during reconciliation:
    CandidateTracker.on_regime_flip's flip_close/anchor argument must be
    `gate_anchor` (self._prev_close, the causally-available raw 1s-bar
    close at the flip instant, matching build_weakness_atlas.py:56-69's
    `entry_open` definition), never `anchor` (the confirming 1-MINUTE bar's
    OWN open, 60s stale -- legitimate only for feature_engine.reset_regime)
    nor a fresh `bar.close`/`bar.open` read (a differently-aggregated bar,
    confirmed off by up to 9+ points from the true raw-1s-bar anchor on at
    least one real regime). Using the wrong anchor inflates/deflates the
    established-gate's MFE/MAE excursion and was the dominant remaining
    cause of the live candidate population diverging from the offline
    reference after the progress-window and frozen-ATR fixes."""
    text = (IMPL / "strategy.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    m = re.search(r"on_regime_flip\(([^)]*)\)", code_text)
    assert m, "on_regime_flip call not found"
    args = [a.strip() for a in m.group(1).split(",")]
    assert args[2] == "gate_anchor", (
        f"on_regime_flip's 3rd arg (flip_close/anchor) must be gate_anchor, got {args[2]!r}")
    assert re.search(r"gate_anchor\s*=\s*self\._prev_close\b", code_text), (
        "gate_anchor must be assigned from self._prev_close")


def test_add_data_call_order_is_1s_before_1m():
    """Coincident 1s/1m timestamp ordering is determined by data-registration
    call order, not an automatic NT bar-type priority (established by
    nt_live_scoring_infra_prereqs/tests/test_coincident_bar_ordering.py,
    reused here, not re-derived). This test guards run_nt.py's own call
    order against silent regression."""
    text = (IMPL / "run_nt.py").read_text(encoding="utf-8")
    idx_1s = text.index("engine.add_data(bars_1s)")
    idx_1m = text.index("engine.add_data(bars_1m)")
    assert idx_1s < idx_1m, "bars_1s must be added to the engine BEFORE bars_1m"


def test_on_1s_uses_ts_event_not_ts_init():
    """Regression guard for the OHLCVDeltaTracker first-divergence audit's
    root-cause fix. NT's `ts_init` for a 1-SECOND bar is `ts_event + 1s`
    (confirmed directly against the live catalog), whereas the offline
    reference pipeline (attach_features.py / ohlcv_delta.py / the whole
    candidate-grid timeline) is built entirely from raw 1s parquet's own
    index, which numerically equals `ts_event` -- matching CLAUDE.md
    invariant 3's "1s bars need no adjustment". Using `bar.ts_init` in
    _on_1s fed a value systematically 1s later than offline's convention
    into `_minute_bucket_key`, corrupting minute-bucket attribution and the
    entire 5s candidate grid. Reproduced bit-exactly via a targeted
    pure-Python replay: substituting ts_event+1s for ts_event reproduced the
    real NT run's own buggy price_change_points_60s/est_delta_sum_1800s/
    est_bear_vol_sum_300s values to full float precision on the first known-
    mismatching checkpoint, while ts_event alone reproduces the offline
    reference exactly (see diagnostics/run_targeted_replay.py
    --simulate-ts-init-1s). `_on_1m` is UNCHANGED and must keep `bar.ts_init`
    -- 1-MINUTE bars DO require the ts_init/close shift per the same
    invariant, independently verified elsewhere this session (regime/ATR
    component validation)."""
    text = (IMPL / "strategy.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code_text = "\n".join(code_lines)

    on_1s_start = code_text.index("def _on_1s(")
    on_1m_start = code_text.index("def _on_1m(")
    on_1s_body = code_text[on_1s_start:on_1m_start]
    on_1m_body = code_text[on_1m_start:on_1m_start + 400]

    assert re.search(r"ts\s*=\s*int\(bar\.ts_event\)", on_1s_body), (
        "_on_1s must read `ts = int(bar.ts_event)`, not bar.ts_init, for 1-second bars")
    assert "bar.ts_init" not in on_1s_body, "_on_1s must not read bar.ts_init anywhere"
    assert re.search(r"ts\s*=\s*int\(bar\.ts_init\)", on_1m_body), (
        "_on_1m must keep reading `ts = int(bar.ts_init)` -- 1-minute bars require the close-time shift")
