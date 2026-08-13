"""Regime-complete canonical collector.

Extends the accepted Phase B dual-model collector along three axes, all of them
widening. Nothing is narrowed, and no threshold, score, or selection predicate
appears in any emission condition.

1. Scores are emitted on the full-session 5s grid rather than the RTH grid.
   The frozen adapters are untouched, so ETH checkpoints yield whatever the
   frozen feature contract yields (see `session_contract_status`).
2. A regime record is opened at every flip and closed at the next one -- not
   only where a trade would have been selected.
3. A path row is emitted for every completed 1s bar inside an open regime.

The RTH score rows this collector produces must remain byte-identical to the
accepted artifact; `validate_pilot.py` asserts that directly. That is why the
scoring body is inherited rather than reimplemented.
"""
from __future__ import annotations

import math
from typing import Optional

from nautilus_trader.model.data import Bar

from studies.full_trade_path_builder.implementation.phase_a_strategy import (
    is_rth_decision,
    minute_bucket_from_close,
)
from studies.full_trade_path_builder.implementation.phase_b_strategy import (
    PhaseBCollector,
    PhaseBCollectorConfig,
)

from .identity import (
    CONTRACT_VERSION,
    collector_version,
    feature_snapshot_id,
    regime_engine_version,
    regime_id as make_regime_id,
    score_observation_id,
)

NS = 1_000_000_000

# Emitted on every score row so an ETH probability can never be silently
# compared against an RTH one. See DECISION-1.
IN_SESSION_CONTRACT = "IN_FROZEN_SESSION_CONTRACT"
OUT_OF_SESSION_CONTRACT = "OUT_OF_FROZEN_SESSION_CONTRACT"

REGIME_END_OPPOSING_FLIP = "opposing_flip"
REGIME_END_CENSORED = "sealed_boundary_censored"

# Compact path tuple layout. The frozen wide schema is materialized by the
# writer; carrying it per-row through Python would cost ~1 GB per month for
# values that are constant within a regime.
PATH_FIELDS = (
    "regime_sequence_number",
    "path_event_ns",
    "path_init_ns",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "atr_current",
    "regime_state",
    "established_state",
    "last_score_decision_ns",
    "last_bullish_probability",
    "last_bearish_probability",
)


class RegimeCompleteCollectorConfig(PhaseBCollectorConfig, frozen=True):
    pass


class RegimeCompleteCollector(PhaseBCollector):
    def __init__(self, config: RegimeCompleteCollectorConfig):
        super().__init__(config)
        self.instrument_id = config.instrument_id
        self.collector_version = collector_version()
        self.regime_engine_version = regime_engine_version()

        self.regimes: list[dict] = []
        self.paths: list[tuple] = []

        self._open_regime: Optional[dict] = None
        self._regime_sequence = 0
        self._warmup_flips_skipped = 0

        # Carried-forward score state for path rows. A carry is never written
        # into the score table; it is visible on path rows only, with its age.
        self._last_score_ns: Optional[int] = None
        self._last_bull_p: Optional[float] = None
        self._last_bear_p: Optional[float] = None

    # ------------------------------------------------------------------ 1s

    def _on_1s(self, bar: Bar) -> None:
        """Inherited scoring, widened to the full session, plus path capture.

        Mirrors `PhaseBCollector._on_1s` exactly except for the session gate on
        dispatch and the appended path row. The ordering of engine updates is
        preserved verbatim: any reordering here changes feature state.
        """
        te, ti = int(bar.ts_event), int(bar.ts_init)
        if te >= ti:
            raise RuntimeError("1s source must be completed before availability")
        o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
        estimate = self._bull_adapter.engine.update_1s(te, o, h, l, c, v)
        atr = float(self._regime.atr) if self._regime.atr is not None else math.nan
        self._bear_adapter.engine.update_1s(te, o, h, l, c, v, self._direction, atr)
        if self._domain is not None:
            self._domain.update(te, h, l)
        self._last_1s_event, self._last_1s_init, self._last_close = te, ti, c
        self.observation_end_ns = ti

        bucket = minute_bucket_from_close(ti)
        if self._minute_bucket is None:
            self._minute_bucket = bucket
        if bucket != self._minute_bucket:
            self._minute_buffer = []
            self._minute_bucket = bucket
        self._minute_buffer.append((te, h, l, v, float(estimate["bar_est_delta"])))

        if ti % (5 * NS) == 0:
            self._last_grid_ns = ti
            # Gaps in the dispatch grid are reconciled against the full window
            # grid by the runner rather than detected incrementally here. An
            # incremental detector only emits a gap once a *later* boundary
            # arrives, so it silently drops a gap that runs to the end of the
            # window -- which happens at every partition boundary.
            #
            # DECISION-1: no session gate. The frozen adapters decide whether a
            # score exists; the collector does not decide it for them.
            if self._regime.atr is not None:
                self._emit(ti)

        self._append_path_row(te, ti, o, h, l, c, v, atr)

    def _append_path_row(self, te, ti, o, h, l, c, v, atr) -> None:
        regime = self._open_regime
        if regime is None:
            return
        established_ns = regime["regime_established_decision_ns"]
        self.paths.append((
            regime["regime_sequence_number"],
            te,
            ti,
            o, h, l, c, v,
            None if math.isnan(atr) else atr,
            regime["regime_direction"],
            established_ns is not None and ti >= established_ns,
            self._last_score_ns,
            self._last_bull_p,
            self._last_bear_p,
        ))
        if regime["path_start_ns"] is None:
            regime["path_start_ns"] = ti
        regime["path_end_ns"] = ti
        regime["path_row_count"] += 1

    # ------------------------------------------------------------------ 1m

    def _on_1m(self, bar: Bar) -> None:
        """Inherited regime/ATR/RTH handling, plus regime-record lifecycle."""
        flips_before = len(self.flips)
        close_price = self._last_close
        super()._on_1m(bar)
        if len(self.flips) == flips_before:
            return

        flip = self.flips[-1]
        ti = int(bar.ts_init)
        anchor = flip["flip_close"]
        self._close_open_regime(
            end_decision_ns=ti,
            end_event_ns=int(bar.ts_event),
            end_price=close_price if close_price is not None else anchor,
            reason=REGIME_END_OPPOSING_FLIP,
        )
        # `_domain` is None when ATR has not initialized; those flips are inside
        # warmup, are counted, and never become regimes.
        if self._domain is None:
            self._warmup_flips_skipped += 1
            return
        self._open_new_regime(flip, ti, int(bar.ts_event), anchor)

    def _open_new_regime(self, flip, ti, te, anchor) -> None:
        self._regime_sequence += 1
        direction = int(flip["new_direction"])
        self._open_regime = {
            "instrument_id": self.instrument_id,
            "regime_id": make_regime_id(self.instrument_id, ti, direction),
            "regime_sequence_number": self._regime_sequence,
            "regime_direction": direction,
            "regime_start_decision_ns": ti,
            "regime_start_event_ns": te,
            "regime_start_price": float(anchor),
            "atr_at_regime_start": float(flip["atr_at_regime_start"]),
            "regime_established_decision_ns": None,
            "atr_at_established": None,
            "established_reached": False,
            "regime_end_decision_ns": None,
            "regime_end_event_ns": None,
            "regime_end_price": None,
            "regime_end_reason": None,
            "atr_at_regime_end": None,
            "session_at_start": _session(ti),
            "session_at_established": None,
            "session_at_end": None,
            "path_start_ns": None,
            "path_end_ns": None,
            "path_row_count": 0,
            "collector_version": self.collector_version,
            "regime_engine_version": self.regime_engine_version,
            "contract_version": CONTRACT_VERSION,
        }

    def _close_open_regime(
        self, end_decision_ns, end_event_ns, end_price, reason
    ) -> None:
        regime = self._open_regime
        if regime is None:
            return
        regime["regime_end_decision_ns"] = end_decision_ns
        regime["regime_end_event_ns"] = end_event_ns
        regime["regime_end_price"] = None if end_price is None else float(end_price)
        regime["regime_end_reason"] = reason
        regime["atr_at_regime_end"] = (
            float(self._regime.atr) if self._regime.atr is not None else None
        )
        regime["session_at_end"] = _session(end_decision_ns)
        self.regimes.append(regime)
        self._open_regime = None

    def finalize(self) -> None:
        """Close the trailing regime as censored. Never invent a terminal event."""
        self._close_open_regime(
            end_decision_ns=None,
            end_event_ns=None,
            end_price=None,
            reason=REGIME_END_CENSORED,
        )

    # --------------------------------------------------------------- emit

    def _emit(self, decision_ns: int) -> None:
        """Inherited row, augmented with linkage, identity, and session status."""
        super()._emit(decision_ns)
        self._augment_score_row(decision_ns)

    def _augment_score_row(self, decision_ns: int) -> None:
        """Add linkage, identity, and session status to the last emitted row.

        Separated from `_emit` so the collection contract can be exercised
        without loading the frozen model stack.
        """
        row = self.rows[-1]
        rth = is_rth_decision(decision_ns)

        row["session"] = "RTH" if rth else "ETH"
        row["session_contract_status"] = (
            IN_SESSION_CONTRACT if rth else OUT_OF_SESSION_CONTRACT
        )
        # The inherited in-domain predicate is `direction == +/-1 AND
        # established_regime_gate`. It never tested session because the Phase B
        # collector only ever ran inside RTH, so the session conjunct was
        # implicit. Widening to the full session makes that assumption false:
        # both frozen model contracts specify session [08:30,15:00) America/
        # Chicago, so an ETH checkpoint is out of domain by definition however
        # mature the regime is. RTH rows are unaffected.
        if not rth:
            row["bullish_in_domain"] = False
            row["bearish_in_domain"] = False
            row["bullish_out_of_domain_reason"] = OUT_OF_SESSION_CONTRACT
            row["bearish_out_of_domain_reason"] = OUT_OF_SESSION_CONTRACT
        else:
            row["bullish_out_of_domain_reason"] = None
            row["bearish_out_of_domain_reason"] = None
        row["score_observation_id"] = score_observation_id(
            self.instrument_id, decision_ns
        )
        row["feature_snapshot_id"] = feature_snapshot_id(
            self.instrument_id, decision_ns
        )
        row["feature_contract_version"] = CONTRACT_VERSION
        row["score_decision_ns"] = decision_ns
        row["score_event_ns"] = self._last_1s_event
        row["score_available_ns"] = decision_ns
        # Both models are dispatched from one provenance at one decision
        # timestamp, so these are equal today. They are materialized anyway so
        # a future cadence split cannot silently change what a row means.
        row["bullish_score_available_ns"] = decision_ns
        row["bearish_score_available_ns"] = decision_ns
        # One canonical row is one true scoring event, by construction: the
        # dispatch fires only on an exact 5s boundary and carry-forward lives
        # on path rows. Asserted by a negative test.
        row["bullish_score_is_new"] = True
        row["bearish_score_is_new"] = True
        row["collector_version"] = self.collector_version
        row["contract_version"] = CONTRACT_VERSION

        regime = self._open_regime
        if regime is None:
            row["regime_id"] = None
            row["score_sequence_in_regime"] = None
            row["seconds_from_regime_start"] = None
            row["seconds_from_established"] = None
        else:
            row["regime_id"] = regime["regime_id"]
            row["score_sequence_in_regime"] = regime.setdefault("_score_seq", 0)
            regime["_score_seq"] += 1
            row["seconds_from_regime_start"] = (
                decision_ns - regime["regime_start_decision_ns"]
            ) / NS
            # Record onset before measuring from it, so the checkpoint that
            # establishes the regime reads 0.0 rather than null.
            self._record_established(regime, decision_ns, row)
            established_ns = regime["regime_established_decision_ns"]
            row["seconds_from_established"] = (
                None if established_ns is None
                else (decision_ns - established_ns) / NS
            )

        self._last_score_ns = decision_ns
        self._last_bull_p = row["bullish_probability"]
        self._last_bear_p = row["bearish_probability"]

    def _record_established(self, regime: dict, decision_ns: int, row: dict) -> None:
        """First checkpoint at which the frozen established gate holds.

        Resolution is the 5s checkpoint grid, which is the same grid on which
        `bullish_in_domain` / `bearish_in_domain` are evaluated. Recording it at
        finer resolution would create a milestone the domain flags disagree with.
        """
        if regime["established_reached"] or not row.get("established_regime_gate"):
            return
        regime["regime_established_decision_ns"] = decision_ns
        regime["established_reached"] = True
        regime["atr_at_established"] = row["atr_at_checkpoint"]
        regime["session_at_established"] = _session(decision_ns)


def _session(ts_ns: Optional[int]) -> Optional[str]:
    if ts_ns is None:
        return None
    return "RTH" if is_rth_decision(ts_ns) else "ETH"
