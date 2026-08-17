"""Instrument timestamp evidence and session boundary (Findings G1, G2).

G1 -- ``config/timestamp_contract.json`` for an **ES** study recorded
``catalog_path: data/catalog/NQ_v0_2020_2026`` and measurements for ``NQ.XCME-*`` bar
types. The cause was mundane and total: ``compile_timestamp_contract`` accepted an
``instrument_symbol`` argument and never used it, defaulting the catalog to NQ for every
instrument.

G2 -- ``strategies/flip_prediction_collector.py`` carried three different inline RTH
boundaries simultaneously (08:30-15:15 for the OHLCV accumulator, 08:30-15:00 for the
candidate gate, 08:30-15:00 for the ``is_rth`` feature) while the population contract said
only ``session: "RTH"``. ``utils/session_boundaries.py`` and ``AGENTS.md`` both already
defined the canonical window as **08:30-15:15 CT**; the collector simply never consulted
either.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd
import pytest

from research.engines.timestamp_engine import (
    CatalogTimestampSemanticError,
    compile_timestamp_contract,
    resolve_catalog_for_symbol,
)
from utils.session_boundaries import (
    RTH_END,
    RTH_START,
    UnknownSessionError,
    is_in_session,
    resolve_session_window,
    session_close_ns,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def ct(day: str, hhmmss: str) -> int:
    return int(pd.Timestamp(f"{day} {hhmmss}", tz="America/Chicago").tz_convert("UTC").value)


DAY = "2024-09-03"          # a Tuesday


# ---------------------------------------------------------------------------
# G1 -- instrument-resolved timestamp evidence
# ---------------------------------------------------------------------------

def test_catalog_is_resolved_from_the_instrument():
    """G1.1 -- the symbol actually selects the catalog."""
    assert resolve_catalog_for_symbol("ES") == "data/catalog/ES_v0_2020_2026"
    assert resolve_catalog_for_symbol("NQ") == "data/catalog/NQ_v0_2020_2026"
    assert resolve_catalog_for_symbol("es") == "data/catalog/ES_v0_2020_2026"


def test_unknown_instrument_fails_closed_instead_of_defaulting_to_nq():
    """G1.2 -- the historical failure mode was a silent default, so there is none."""
    with pytest.raises(CatalogTimestampSemanticError, match="UNSUPPORTED_INSTRUMENT"):
        resolve_catalog_for_symbol("ZZ")


def test_es_contract_carries_es_evidence_only():
    """G1.3 -- an ES study's contract must not contain NQ measurements."""
    contract = compile_timestamp_contract("ES")
    assert contract["instrument_symbol"] == "ES"
    assert "ES_v0_2020_2026" in contract["measured_catalog_rel_path"]

    measurements = contract["nautilus_catalog"]["empirical_measurement"]["measurements"]
    assert measurements, "no measurements were taken"
    assert all(k.startswith("ES.") for k in measurements), list(measurements)
    assert not any("NQ" in k for k in measurements)


@pytest.mark.parametrize("bar_type,expected_ns", [
    ("ES.XCME-1-SECOND-LAST-EXTERNAL", 1_000_000_000),
    ("ES.XCME-1-MINUTE-LAST-EXTERNAL", 60_000_000_000),
    ("ES.XCME-5-MINUTE-LAST-EXTERNAL", 300_000_000_000),
])
def test_es_ts_init_minus_ts_event_equals_bar_duration(bar_type, expected_ns):
    """G1.4 -- the empirical invariant, measured on ES for each required stream."""
    contract = compile_timestamp_contract("ES")
    m = contract["nautilus_catalog"]["empirical_measurement"]["measurements"]
    assert bar_type in m, f"{bar_type} not measured; found {list(m)}"
    assert m[bar_type]["observed_deltas_ns"] == [expected_ns]
    assert m[bar_type]["expected_delta_ns"] == expected_ns
    assert m[bar_type]["pass"] is True


def test_measurement_is_required_not_assumed():
    """A contract may not assert an invariant it never measured."""
    with pytest.raises(CatalogTimestampSemanticError, match="TIMESTAMP_EVIDENCE_UNMEASURED"):
        compile_timestamp_contract("ES", catalog_path="data/catalog/does_not_exist")


# ---------------------------------------------------------------------------
# G2 -- one authoritative session boundary
# ---------------------------------------------------------------------------

def test_canonical_rth_window_is_0830_to_1515_ct():
    """G2.1 -- the boundary is explicit, and it is the project-canonical one."""
    start, end = resolve_session_window("RTH")
    assert (start, end) == (RTH_START, RTH_END)
    assert start.strftime("%H:%M:%S") == "08:30:00"
    assert end.strftime("%H:%M:%S") == "15:15:00"


@pytest.mark.parametrize("hhmmss,expected", [
    ("08:29:59", False),   # before the open
    ("08:30:00", False),   # a bar closing AT the open covers the pre-open minute
    ("08:30:01", True),    # first in-session second
    ("12:00:00", True),
    ("14:59:59", True),    # inside -- the old gate wrongly excluded everything past 15:00
    ("15:00:00", True),
    ("15:14:59", True),
    ("15:15:00", True),    # final in-session bar
    ("15:15:01", False),   # past the close
    ("16:00:00", False),
])
def test_session_membership_at_the_boundaries(hhmmss, expected):
    assert is_in_session(ct(DAY, hhmmss), "RTH") is expected


def test_the_1500_to_1515_window_is_in_session():
    """G2.2 -- the exact 15-minute band the collector's candidate gate used to discard."""
    for hhmmss in ("15:00:01", "15:05:00", "15:10:00", "15:14:59", "15:15:00"):
        assert is_in_session(ct(DAY, hhmmss), "RTH"), hhmmss


def test_weekend_is_not_in_session():
    assert is_in_session(ct("2024-09-07", "12:00:00"), "RTH") is False   # Saturday


def test_session_close_is_computed_per_calendar_day():
    for day in ("2024-09-03", "2024-01-15", "2024-06-20"):
        close = session_close_ns(ct(day, "10:00:00"), "RTH")
        as_ct = pd.Timestamp(close, tz="UTC").tz_convert("America/Chicago")
        assert as_ct.strftime("%Y-%m-%d %H:%M:%S") == f"{day} 15:15:00"


def test_unknown_session_fails_closed():
    """An unresolvable session must never widen silently to 'no restriction'."""
    with pytest.raises(UnknownSessionError):
        resolve_session_window("LUNCH")
    with pytest.raises(UnknownSessionError):
        is_in_session(ct(DAY, "12:00:00"), "LUNCH")


def test_all_session_admits_everything():
    assert is_in_session(ct(DAY, "03:00:00"), "ALL") is True


def test_eth_is_the_complement_of_rth():
    assert is_in_session(ct(DAY, "03:00:00"), "ETH") is True
    assert is_in_session(ct(DAY, "12:00:00"), "ETH") is False


# ---------------------------------------------------------------------------
# The collector no longer re-derives the boundary inline
# ---------------------------------------------------------------------------

def test_collector_contains_no_inline_session_boundary():
    """G2.3 -- the three divergent hard-coded windows are gone.

    A source-level assertion is the right shape here: the defect was not a wrong value
    that a behavioural test would catch, it was three independent definitions that each
    behaved correctly in isolation.
    """
    src = (REPO_ROOT / "strategies" / "flip_prediction_collector.py").read_text(encoding="utf-8")

    # Scan executable lines only: the comments explaining what was removed necessarily
    # quote the removed expressions, and matching those would make this test unfailable
    # in the wrong direction.
    code_lines = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("``"):
            continue
        code_lines.append(line.split("#", 1)[0])
    code = "\n".join(code_lines)

    assert "510 <= minute_of_day" not in code, "the 08:30-15:00 candidate gate is still present"
    for banned in ("minute <= 15)", "ts_pd.hour < 15"):
        assert banned not in code, f"inline session arithmetic still present: {banned!r}"
    assert "is_in_session" in code, "the collector must consult the canonical boundary module"


def test_collector_config_declares_session_and_censoring():
    """The runtime reads the session from the contract instead of assuming one."""
    from strategies.flip_prediction_collector import FlipPredictionCollectorConfig

    cfg = FlipPredictionCollectorConfig()
    assert hasattr(cfg, "session")
    assert hasattr(cfg, "session_end_censoring")
    # The defaults must match the canonical contract, not a looser fallback.
    assert cfg.session == "RTH"
    assert cfg.session_end_censoring is True


def test_collect_mode_passes_the_contract_session_to_the_strategy():
    """The wiring exists, so a study declaring a session actually gets that session."""
    from backtests.nt_runtime.modes import collect

    # The strategy config is built in `_execute_collect`, which `run_collect_mode` wraps
    # for terminal-status handling (H2); read the module so the assertion survives that
    # split rather than binding to one function's body.
    src = inspect.getsource(collect)
    assert 'cfg_kwargs["session"]' in src
    assert 'cfg_kwargs["session_end_censoring"]' in src
    assert "spec.population.session" in src, "session must come from the contract"
