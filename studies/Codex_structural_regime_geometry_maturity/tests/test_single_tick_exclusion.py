from types import SimpleNamespace

from studies.Codex_structural_regime_geometry_maturity.implementation.collector import StructuralOnlyCollector


class _Geometry:
    def __init__(self):
        self.snapshot_price = None

    def on_1s(self, *args):
        raise AssertionError("excluded single-contract bar must not update extrema")

    def snapshot(self, _decision_ns, price, *_args):
        self.snapshot_price = price
        return {"structural_available": False}


class _Aggregator:
    def on_1s_bar(self, *args):
        raise AssertionError("excluded single-contract bar must not update 5m state")

    def finalize_through(self, _available_ns):
        pass


class _Registry:
    def audit_provenance(self, _decision_ns):
        pass

    def get(self, _timeframe):
        return None


def test_single_contract_checkpoint_uses_last_eligible_close_for_snapshot_price():
    collector = StructuralOnlyCollector.__new__(StructuralOnlyCollector)
    collector._geometry = _Geometry()
    collector._aggregator = _Aggregator()
    collector._registry = _Registry()
    collector._regime = SimpleNamespace(atr=10.0)
    collector._last_close = 100.0
    collector.geometry_rows = []
    # The excluded bar has a different close, so leaking it would be observable.
    bar = SimpleNamespace(ts_event=4_000_000_000, ts_init=5_000_000_000,
                          open=105.0, high=105.0, low=105.0, close=105.0, volume=1.0)
    collector._on_1s(bar)
    assert collector._geometry.snapshot_price == 100.0
