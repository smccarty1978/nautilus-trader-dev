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


def test_on_candidate_uses_frozen_atr_not_live_engine_atr():
    """Regression guard for a real bug found during reconciliation:
    strategy.py's _on_candidate must source atr from the candidate dict's
    frozen atr_val (CandidateTracker's own flip-time value), not by
    re-reading self._engine.atr (which keeps updating live across
    checkpoints within the same regime). The only permitted read of
    self._engine.atr in the whole file is the flip-time freeze itself, in
    _on_1m's on_regime_flip(...) call."""
    text = (IMPL / "strategy.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code_text = "\n".join(code_lines)
    reads = [m.start() for m in re.finditer(r"self\._engine\.atr\b", code_text)]
    assert len(reads) == 1, (
        f"expected exactly one self._engine.atr read (the flip-time freeze "
        f"passed to on_regime_flip), found {len(reads)}")
    assert "on_regime_flip(" in code_text[reads[0] - 80: reads[0] + 20]


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
