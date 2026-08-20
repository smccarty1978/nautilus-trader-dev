from types import SimpleNamespace
import pytest
import pandas as pd

from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import CleanFlipCollector


class _Recorder:
    def __init__(self):
        self.calls = 0

    def update_1s(self, _bar):
        self.calls += 1

    def finalize_through(self, _timestamp):
        self.calls += 1

    def consume_incomplete_close_ts(self, _timeframe):
        return []

    def on_1s(self, *args):
        self.calls += 1


def init_mock_collector(collector):
    collector._was_rth_decision = False
    collector._last_seen_1s_event_ns = None
    collector._last_seen_1s_decision_ns = None
    collector._last_seen_1m_init_ns = None
    collector._last_eligible_close = None
    collector._current_regime_start_atr = None
    collector._current_regime_start_ns = None
    collector._current_regime_anchor = None
    collector._regime = SimpleNamespace(regime=0)
    collector.telemetry_total_checkpoints = 0
    collector.telemetry_rth_gate_pass = 0
    collector.telemetry_age_gate_pass = 0
    collector.telemetry_mfe_gate_pass = 0
    collector.telemetry_progress_gate_pass = 0
    collector.telemetry_retention_gate_pass = 0
    collector.telemetry_declared_population_eligible = 0
    collector.telemetry_candidates_emitted = 0
    collector.telemetry_declared_contract_exclusions = 0
    collector.telemetry_implementation_only_exclusions = 0


def test_dense_and_native_one_volume_bars_do_not_reject():
    # 1. Native volume = 1 does not reject and advances trackers
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    bar1 = SimpleNamespace(ts_event=1_704_067_200_000_000_000, ts_init=1_704_067_201_000_000_000,
                           open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar1)
    assert collector._features.calls == 1
    assert collector._geometry.calls == 1

    # 2. Canonical volume = 0 does not reject and advances trackers
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    bar0 = SimpleNamespace(ts_event=1_704_067_200_000_000_000, ts_init=1_704_067_201_000_000_000,
                           open=100.0, high=100.0, low=100.0, close=100.0, volume=0.0)
    collector._on_1s(bar0)
    assert collector._features.calls == 1
    assert collector._geometry.calls == 1


def test_timeline_integrity_violations_fail_execution():
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    
    # Setup initial state
    bar_init = SimpleNamespace(ts_event=1_725_548_400_000_000_000, ts_init=1_725_548_401_000_000_000,
                               open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar_init)
    
    # 1. Duplicate 1s timestamp
    bar_dup = SimpleNamespace(ts_event=1_725_548_400_000_000_000, ts_init=1_725_548_401_000_000_000,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    with pytest.raises(RuntimeError, match="Duplicate 1s timestamp"):
        collector._on_1s(bar_dup)
        
    # 2. Out-of-order 1s timestamp
    bar_ooo = SimpleNamespace(ts_event=1_725_548_399_000_000_000, ts_init=1_725_548_400_000_000_000,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    with pytest.raises(RuntimeError, match="Out-of-order 1s timestamp"):
        collector._on_1s(bar_ooo)
        
    # 3. Gap in 1s timestamps
    bar_gap = SimpleNamespace(ts_event=1_725_548_402_000_000_000, ts_init=1_725_548_403_000_000_000,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    with pytest.raises(RuntimeError, match="Unexpected gap in canonical dense timeline"):
        collector._on_1s(bar_gap)


def test_telemetry_reconciliation():
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    
    # Assert initial state
    assert collector.telemetry_total_checkpoints == 0
    assert collector.telemetry_declared_population_eligible == 0
    assert collector.telemetry_candidates_emitted == 0
    assert collector.telemetry_implementation_only_exclusions == 0
    
    # Assert reconciliation relationship
    assert collector.telemetry_declared_population_eligible == collector.telemetry_candidates_emitted + collector.telemetry_declared_contract_exclusions


def test_dense_timeline_semantics_under_closures():
    # 1. Ordinary consecutive seconds -> PASS
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    
    bar1 = SimpleNamespace(ts_event=1_725_548_400_000_000_000, ts_init=1_725_548_401_000_000_000,
                           open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) # 10:00:00 CT (15:00:00 UTC)
    bar2 = SimpleNamespace(ts_event=1_725_548_401_000_000_000, ts_init=1_725_548_402_000_000_000,
                           open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) # 10:00:01 CT (15:00:01 UTC)
    collector._on_1s(bar1)
    collector._on_1s(bar2) # Should pass without raising error
    
    # 2. Missing one open-session second -> HARD FAIL
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    collector._on_1s(bar1)
    bar_gap = SimpleNamespace(ts_event=1_725_548_402_000_000_000, ts_init=1_725_548_403_000_000_000,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) # 10:00:02 CT (15:00:02 UTC)
    with pytest.raises(RuntimeError, match="Unexpected gap in canonical dense timeline"):
        collector._on_1s(bar_gap)
        
    # 3. Daily maintenance closure -> PASS
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    
    t_pre_halt_event = int(pd.Timestamp("2024-09-05 20:59:59", tz="UTC").value)
    t_pre_halt_init = t_pre_halt_event + 1_000_000_000
    t_post_halt_event = int(pd.Timestamp("2024-09-05 22:00:00", tz="UTC").value)
    t_post_halt_init = t_post_halt_event + 1_000_000_000
    
    bar_pre = SimpleNamespace(ts_event=t_pre_halt_event, ts_init=t_pre_halt_init,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    bar_post = SimpleNamespace(ts_event=t_post_halt_event, ts_init=t_post_halt_init,
                               open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar_pre)
    collector._on_1s(bar_post) # Must PASS daily halt
    
    # 4. Weekend closure -> PASS
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    
    t_fri_event = int(pd.Timestamp("2024-09-06 20:59:59", tz="UTC").value)
    t_fri_init = t_fri_event + 1_000_000_000
    t_sun_event = int(pd.Timestamp("2024-09-08 22:00:00", tz="UTC").value)
    t_sun_init = t_sun_event + 1_000_000_000
    
    bar_fri = SimpleNamespace(ts_event=t_fri_event, ts_init=t_fri_init,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    bar_sun = SimpleNamespace(ts_event=t_sun_event, ts_init=t_sun_init,
                               open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar_fri)
    collector._on_1s(bar_sun) # Must PASS weekend
    
    # 5. Holiday closure -> PASS
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    
    t_thu_event = int(pd.Timestamp("2024-12-24 17:59:59", tz="UTC").value)
    t_thu_init = t_thu_event + 1_000_000_000
    t_reopen_event = int(pd.Timestamp("2024-12-25 23:00:00", tz="UTC").value)
    t_reopen_init = t_reopen_event + 1_000_000_000
    
    bar_thu = SimpleNamespace(ts_event=t_thu_event, ts_init=t_thu_init,
                              open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    bar_reopen = SimpleNamespace(ts_event=t_reopen_event, ts_init=t_reopen_init,
                                 open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar_thu)
    collector._on_1s(bar_reopen) # Must PASS holiday closure
    
    # 6. Historical pre-2021 15:15-15:30 CT halt -> PASS
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2020}
    
    t_pre_halt2020_event = int(pd.Timestamp("2020-01-06 21:14:59", tz="UTC").value)
    t_pre_halt2020_init = t_pre_halt2020_event + 1_000_000_000
    t_post_halt2020_event = int(pd.Timestamp("2020-01-06 21:30:00", tz="UTC").value)
    t_post_halt2020_init = t_post_halt2020_event + 1_000_000_000
    
    bar_pre2020 = SimpleNamespace(ts_event=t_pre_halt2020_event, ts_init=t_pre_halt2020_init,
                                  open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    bar_post2020 = SimpleNamespace(ts_event=t_post_halt2020_event, ts_init=t_post_halt2020_init,
                                   open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar_pre2020)
    collector._on_1s(bar_post2020) # Must PASS historical break
    
    # 7. Post-2021 same interval remains open; missing second there -> HARD FAIL
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    init_mock_collector(collector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    
    t_pre_halt2024_event = int(pd.Timestamp("2024-09-09 20:14:59", tz="UTC").value)
    t_pre_halt2024_init = t_pre_halt2024_event + 1_000_000_000
    t_post_halt2024_event = int(pd.Timestamp("2024-09-09 20:30:00", tz="UTC").value)
    t_post_halt2024_init = t_post_halt2024_event + 1_000_000_000
    
    bar_pre2024 = SimpleNamespace(ts_event=t_pre_halt2024_event, ts_init=t_pre_halt2024_init,
                                  open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    bar_post2024 = SimpleNamespace(ts_event=t_post_halt2024_event, ts_init=t_post_halt2024_init,
                                   open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar_pre2024)
    with pytest.raises(RuntimeError, match="Unexpected gap in canonical dense timeline"):
        collector._on_1s(bar_post2024) # Must FAIL post-2021 gap
