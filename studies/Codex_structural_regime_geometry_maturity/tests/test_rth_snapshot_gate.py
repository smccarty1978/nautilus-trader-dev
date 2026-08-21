from datetime import datetime, timezone

from studies.Codex_structural_regime_geometry_maturity.implementation.collector import is_rth_decision


def _ns(utc: str) -> int:
    return int(datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)


def test_snapshot_gate_uses_rth_decision_interval_including_dst_aware_open_and_excluding_close():
    assert not is_rth_decision(_ns("2024-01-03T14:29:55"))  # 08:29:55 CT
    assert is_rth_decision(_ns("2024-01-03T14:30:00"))      # 08:30:00 CT
    assert not is_rth_decision(_ns("2024-01-03T21:00:00"))  # 15:00:00 CT
    assert is_rth_decision(_ns("2024-07-03T13:30:00"))      # 08:30:00 CDT
