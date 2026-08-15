from types import SimpleNamespace

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


def test_one_contract_bar_cannot_advance_any_feature_family():
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    collector._features = _Recorder()
    collector._geometry = _Recorder()
    collector._authorized_years = {2024}
    collector._last_seen_1s_event_ns = None
    bar = SimpleNamespace(ts_event=1_704_067_200_000_000_000, ts_init=1_704_067_201_000_000_000,
                          high=101.0, low=99.0, close=100.0, volume=1.0)
    collector._on_1s(bar)
    assert collector._features.calls == 0
    assert collector._geometry.calls == 0
