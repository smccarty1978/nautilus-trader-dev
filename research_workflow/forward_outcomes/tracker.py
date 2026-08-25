"""Streaming forward-path observation.

The tracker answers exactly one question -- "what happened after that proposed entry?"
-- and is deliberately incapable of answering any other. It never decides whether an
entry exists, never re-prices one, and never reads a bar that precedes the entry it is
measuring.

Cost model. Full future paths are never retained. Each live entry owns one small
``ForwardObservation`` with running extrema and a horizon cursor; work per bar is
O(active observations), and an observation is dropped from the active set the moment
its tracking budget elapses. Entries that have not started yet wait in an
``entry_ts``-ordered queue, and finished ones are reachable only through a lazily
validated expiry heap. Nothing scans the historical entry set.

Bar-resolution caveat. Excursion timestamps resolve to the close of the bar that set
the extremum, because a bar does not record *when* inside itself its high and low
occurred. For the same reason, when a bar touches a favourable and an adverse
diagnostic level in the same interval the ordering is unknowable, and the record says
so (``first_touch_ambiguous_*``) rather than guessing.
"""

from __future__ import annotations

import heapq
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from research_workflow.forward_outcomes.contracts import (
    NS,
    BarInclusion,
    ConfirmationSpec,
    Direction,
    ForwardOutcomeError,
    ForwardOutcomeSpec,
    OutcomeStatus,
    ProposedEntry,
    horizon_label,
    level_label,
    worst_status,
)

_UNIT_SUFFIX = {"points": "", "atr": "_atr", "ticks": "_ticks"}


class ForwardObservation:
    """Mutable per-entry future-path state. One instance per live proposed entry."""

    __slots__ = (
        "entry", "spec", "session_close_ts", "direction_sign", "atr",
        "_horizons", "_horizon_cursor", "_horizon_results",
        "mfe", "mae", "time_to_mfe_ns", "time_to_mae_ns",
        "first_bar_ts", "last_bar_ts", "last_close", "bars_observed",
        "_prev_included_ts", "max_gap_ns", "gap_breach",
        "confirmed", "confirmation_ts", "confirmation_price",
        "pre_mfe", "pre_mae", "pre_time_to_mfe_ns", "pre_time_to_mae_ns",
        "post_mfe", "post_mae", "post_time_to_mfe_ns", "post_time_to_mae_ns",
        "_post_horizons", "_post_cursor", "_post_results", "post_bars_observed",
        "_level_fav_ts", "_level_adv_ts", "_level_ambiguous",
        "close_deadline_ns", "closed", "resolved_at_ts", "final_status",
        "censor_reason", "session_truncated",
    )

    def __init__(
        self,
        entry: ProposedEntry,
        spec: ForwardOutcomeSpec,
        session_close_ts: Optional[int],
    ) -> None:
        self.entry = entry
        self.spec = spec
        self.session_close_ts = session_close_ts
        self.direction_sign = entry.direction.sign
        self.atr = float(entry.entry_atr) if entry.entry_atr else None

        self._horizons: Tuple[Tuple[int, int], ...] = tuple(
            (h, entry.entry_ts + int(h) * NS) for h in spec.horizons_seconds
        )
        self._horizon_cursor = 0
        self._horizon_results: Dict[int, Dict[str, Any]] = {}

        self.mfe: Optional[float] = None
        self.mae: Optional[float] = None
        self.time_to_mfe_ns: Optional[int] = None
        self.time_to_mae_ns: Optional[int] = None

        self.first_bar_ts: Optional[int] = None
        self.last_bar_ts: Optional[int] = None
        self.last_close: Optional[float] = None
        self.bars_observed = 0
        self._prev_included_ts: Optional[int] = None
        self.max_gap_ns = 0
        self.gap_breach = False

        self.confirmed: Optional[bool] = None if spec.confirmation else False
        self.confirmation_ts: Optional[int] = None
        self.confirmation_price: Optional[float] = None
        self.pre_mfe: Optional[float] = None
        self.pre_mae: Optional[float] = None
        self.pre_time_to_mfe_ns: Optional[int] = None
        self.pre_time_to_mae_ns: Optional[int] = None
        self.post_mfe: Optional[float] = None
        self.post_mae: Optional[float] = None
        self.post_time_to_mfe_ns: Optional[int] = None
        self.post_time_to_mae_ns: Optional[int] = None
        self._post_horizons: Tuple[Tuple[int, int], ...] = ()
        self._post_cursor = 0
        self._post_results: Dict[int, Dict[str, Any]] = {}
        self.post_bars_observed = 0

        self._level_fav_ts: Dict[float, Optional[int]] = {l: None for l in spec.diagnostic_levels_atr}
        self._level_adv_ts: Dict[float, Optional[int]] = {l: None for l in spec.diagnostic_levels_atr}
        self._level_ambiguous: Dict[float, bool] = {l: False for l in spec.diagnostic_levels_atr}

        self.close_deadline_ns = entry.entry_ts + spec.max_tracking_ns
        self.closed = False
        self.resolved_at_ts: Optional[int] = None
        self.final_status: Optional[OutcomeStatus] = None
        self.censor_reason: Optional[str] = None
        self.session_truncated = False

    # -- inclusion --------------------------------------------------------------
    def _includes(self, ts_open: int, ts_close: int) -> bool:
        """Whether this bar's price action belongs to the entry's forward path."""
        if self.spec.bar_inclusion is BarInclusion.FULLY_FORWARD:
            if ts_open < self.entry.entry_ts:
                return False
        elif ts_close <= self.entry.entry_ts:
            return False
        if self.session_truncated:
            return False
        if (
            self.spec.session_end_censoring
            and self.session_close_ts is not None
            and ts_close > self.session_close_ts
        ):
            # Past its own session close the path is a different session's price
            # action. Stop accumulating rather than blending the two.
            self.session_truncated = True
            return False
        return True

    # -- streaming --------------------------------------------------------------
    def on_bar(self, ts_open: int, ts_close: int, high: float, low: float, close: float) -> None:
        # Horizons that fall strictly before this bar's close are answered with the
        # state accumulated up to the last observable instant at or before them. The
        # horizon is never shortened; the status records what was observable.
        self._emit_due_horizons(ts_close, inclusive=False)
        self._emit_due_post_horizons(ts_close, inclusive=False)

        if self._includes(ts_open, ts_close):
            self._accumulate(ts_close, high, low, close)

        # A horizon landing exactly on this bar's close includes this bar.
        self._emit_due_horizons(ts_close, inclusive=True)
        self._emit_due_post_horizons(ts_close, inclusive=True)

        if self.spec.confirmation is not None and self.confirmed is None:
            wait_deadline = self.entry.entry_ts + self.spec.confirmation.max_wait_seconds * NS
            if ts_close > wait_deadline:
                self.confirmed = False

    def _accumulate(self, ts_close: int, high: float, low: float, close: float) -> None:
        entry_price = self.entry.entry_price
        sign = self.direction_sign
        # Direction-aware excursions. For a LONG the favourable side is the high and the
        # adverse side is the low; for a SHORT the roles swap. Values are not floored at
        # zero: a path that never traded through its entry has a negative extremum, and
        # hiding that behind a zero would misreport the path.
        favorable = (high - entry_price) if sign > 0 else (entry_price - low)
        adverse = (entry_price - low) if sign > 0 else (high - entry_price)

        if self.mfe is None or favorable > self.mfe:
            self.mfe = favorable
            self.time_to_mfe_ns = ts_close - self.entry.entry_ts
        if self.mae is None or adverse > self.mae:
            self.mae = adverse
            self.time_to_mae_ns = ts_close - self.entry.entry_ts

        if self.first_bar_ts is None:
            self.first_bar_ts = ts_close
            gap = ts_close - self.entry.entry_ts
        else:
            gap = ts_close - self._prev_included_ts
        if gap > self.max_gap_ns:
            self.max_gap_ns = gap
        if self.spec.max_gap_seconds is not None and gap > self.spec.max_gap_seconds * NS:
            self.gap_breach = True

        self._prev_included_ts = ts_close
        self.last_bar_ts = ts_close
        self.last_close = close
        self.bars_observed += 1

        self._update_levels(ts_close, favorable, adverse)
        if self.confirmation_ts is not None and ts_close > self.confirmation_ts:
            self._accumulate_post(ts_close, high, low)

    def _accumulate_post(self, ts_close: int, high: float, low: float) -> None:
        """Post-confirmation excursions are measured from the confirmation price.

        Measuring them from the entry price instead would fold the pre-confirmation
        drift into the post-confirmation number, which is exactly the conflation the
        confirmation split exists to prevent.
        """
        base = self.confirmation_price
        if base is None:
            return
        sign = self.direction_sign
        favorable = (high - base) if sign > 0 else (base - low)
        adverse = (base - low) if sign > 0 else (high - base)
        if self.post_mfe is None or favorable > self.post_mfe:
            self.post_mfe = favorable
            self.post_time_to_mfe_ns = ts_close - self.confirmation_ts
        if self.post_mae is None or adverse > self.post_mae:
            self.post_mae = adverse
            self.post_time_to_mae_ns = ts_close - self.confirmation_ts
        self.post_bars_observed += 1

    def _update_levels(self, ts_close: int, favorable: float, adverse: float) -> None:
        if not self._level_fav_ts or self.atr is None:
            return
        for level in self.spec.diagnostic_levels_atr:
            distance = level * self.atr
            hit_fav = favorable >= distance and self._level_fav_ts[level] is None
            hit_adv = adverse >= distance and self._level_adv_ts[level] is None
            if hit_fav and hit_adv:
                # Both sides touched inside one bar. Bars carry no intra-bar ordering,
                # so the answer is recorded as ambiguous and resolved pessimistically.
                self._level_ambiguous[level] = True
            if hit_fav:
                self._level_fav_ts[level] = ts_close
            if hit_adv:
                self._level_adv_ts[level] = ts_close

    # -- horizons ---------------------------------------------------------------
    def _horizon_status(self, deadline_ns: int) -> OutcomeStatus:
        if (
            self.spec.session_end_censoring
            and self.session_close_ts is not None
            and deadline_ns > self.session_close_ts
        ):
            return OutcomeStatus.CENSORED_SESSION
        if self.bars_observed == 0:
            return OutcomeStatus.MISSING_DATA
        if self.gap_breach:
            return OutcomeStatus.MISSING_DATA
        return OutcomeStatus.RESOLVED

    def _emit_due_horizons(self, now_ts: int, *, inclusive: bool) -> None:
        while self._horizon_cursor < len(self._horizons):
            seconds, deadline = self._horizons[self._horizon_cursor]
            due = deadline <= now_ts if inclusive else deadline < now_ts
            if not due:
                return
            self._snapshot_horizon(seconds, deadline, self._horizon_status(deadline))
            self._horizon_cursor += 1

    def _snapshot_horizon(self, seconds: int, deadline: int, status: OutcomeStatus) -> None:
        resolved = status is OutcomeStatus.RESOLVED
        self._horizon_results[seconds] = {
            "status": status,
            "mfe": self.mfe if resolved else None,
            "mae": self.mae if resolved else None,
            "time_to_mfe_ns": self.time_to_mfe_ns if resolved else None,
            "time_to_mae_ns": self.time_to_mae_ns if resolved else None,
            "price": self.last_close if resolved else None,
        }

    def _emit_due_post_horizons(self, now_ts: int, *, inclusive: bool) -> None:
        while self._post_cursor < len(self._post_horizons):
            seconds, deadline = self._post_horizons[self._post_cursor]
            due = deadline <= now_ts if inclusive else deadline < now_ts
            if not due:
                return
            status = self._horizon_status(deadline)
            if status is OutcomeStatus.RESOLVED and self.post_bars_observed == 0:
                status = OutcomeStatus.MISSING_DATA
            self._post_results[seconds] = {
                "status": status,
                "price": self.last_close if status is OutcomeStatus.RESOLVED else None,
            }
            self._post_cursor += 1

    # -- confirmation -----------------------------------------------------------
    def record_confirmation(self, ts: int, price: float) -> None:
        spec = self.spec.confirmation
        if spec is None:
            raise ForwardOutcomeError("this spec declares no confirmation event")
        if self.confirmation_ts is not None:
            raise ForwardOutcomeError(
                f"entry {self.entry.entry_id} already confirmed at {self.confirmation_ts}"
            )
        # A confirmation at the exact wait deadline is still observable on that
        # completed bar. The streaming adapter may visit the deadline before the
        # coincident confirmation event is supplied, so only a strictly later
        # event is too late.
        if self.confirmed is False and self.last_bar_ts is not None and self.last_bar_ts > self.entry.entry_ts + spec.max_wait_seconds * NS:
            raise ForwardOutcomeError(
                f"entry {self.entry.entry_id} exceeded its confirmation wait window"
            )
        ts = int(ts)
        if ts < self.entry.entry_ts:
            raise ForwardOutcomeError("confirmation precedes the entry it confirms")
        if ts > self.entry.entry_ts + spec.max_wait_seconds * NS:
            raise ForwardOutcomeError("confirmation falls outside the declared wait window")
        self.confirmed = True
        self.confirmation_ts = ts
        self.confirmation_price = float(price)
        # Freeze the pre-confirmation path exactly here; everything after this instant
        # is measured against the confirmation price instead.
        self.pre_mfe = self.mfe
        self.pre_mae = self.mae
        self.pre_time_to_mfe_ns = self.time_to_mfe_ns
        self.pre_time_to_mae_ns = self.time_to_mae_ns
        self._post_horizons = tuple((h, ts + int(h) * NS) for h in spec.post_horizons_seconds)
        self._post_cursor = 0
        post_deadline = ts + spec.post_max_tracking_seconds * NS
        if post_deadline > self.close_deadline_ns:
            self.close_deadline_ns = post_deadline

    # -- closing ----------------------------------------------------------------
    def close(self, now_ts: int, *, reason: Optional[str] = None) -> None:
        if self.closed:
            return
        base = OutcomeStatus.RESOLVED
        if reason == "data_end":
            base = OutcomeStatus.CENSORED_DATA_END
        elif reason == "horizon_budget":
            base = OutcomeStatus.CENSORED_HORIZON
        if self.session_truncated:
            base = worst_status([base, OutcomeStatus.CENSORED_SESSION])
        if self.gap_breach or self.bars_observed == 0:
            base = worst_status([base, OutcomeStatus.MISSING_DATA])

        # Horizons still pending at close never became observable.
        pending_status = base if base is not OutcomeStatus.RESOLVED else OutcomeStatus.CENSORED_DATA_END
        while self._horizon_cursor < len(self._horizons):
            seconds, deadline = self._horizons[self._horizon_cursor]
            status = self._horizon_status(deadline)
            if status is OutcomeStatus.RESOLVED:
                status = pending_status
            self._snapshot_horizon(seconds, deadline, status)
            self._horizon_cursor += 1
        while self._post_cursor < len(self._post_horizons):
            seconds, _deadline = self._post_horizons[self._post_cursor]
            self._post_results[seconds] = {"status": pending_status, "price": None}
            self._post_cursor += 1

        if self.spec.confirmation is not None and self.confirmed is None:
            # The wait window never fully elapsed within observed data, so "did not
            # confirm" is not a finding this run is entitled to make. The spec forbids
            # a wait longer than the tracking budget, so reaching here means the data
            # ran out first.
            base = worst_status([base, pending_status if reason else OutcomeStatus.CENSORED_HORIZON])

        statuses = [base] + [r["status"] for r in self._horizon_results.values()]
        statuses += [r["status"] for r in self._post_results.values()]
        self.final_status = worst_status(statuses)
        self.censor_reason = reason if self.final_status is not OutcomeStatus.RESOLVED else None
        self.resolved_at_ts = int(now_ts)
        self.closed = True

    # -- record -----------------------------------------------------------------
    def _units(self, row: Dict[str, Any], prefix: str, value: Optional[float]) -> None:
        for unit in self.spec.excursion_units:
            key = f"{prefix}{_UNIT_SUFFIX[unit]}"
            if value is None:
                row[key] = None
            elif unit == "points":
                row[key] = float(value)
            elif unit == "atr":
                row[key] = (float(value) / self.atr) if self.atr else None
            else:
                row[key] = float(value) / float(self.spec.tick_size)

    def _quality(self, row: Dict[str, Any], suffix: str, mfe, mae, ret) -> None:
        """Diagnostics only. These describe the observed path; they decide nothing.

        Note on ``epsilon``: the declared formula is ``MFE / max(MAE, epsilon)``, so a
        path with no adverse excursion divides by ``epsilon``. Studies should set
        ``epsilon`` to a meaningful floor (a tick, or a fraction of ATR) rather than
        leave it at the numerical default, or these ratios saturate.
        """
        eps = self.spec.epsilon
        denom = max(mae, eps) if mae is not None else None
        row[f"mfe_mae_ratio{suffix}"] = (mfe / denom) if (mfe is not None and denom) else None
        row[f"return_over_mae{suffix}"] = (ret / denom) if (ret is not None and denom) else None
        row[f"mfe_minus_mae{suffix}"] = (mfe - mae) if (mfe is not None and mae is not None) else None
        if mfe is not None and ret is not None and mfe > 0:
            row[f"retained_mfe_fraction{suffix}"] = ret / mfe
            row[f"giveback_from_mfe{suffix}"] = mfe - ret
        else:
            row[f"retained_mfe_fraction{suffix}"] = None
            row[f"giveback_from_mfe{suffix}"] = None

    def to_record(self) -> Dict[str, Any]:
        if not self.closed:
            raise ForwardOutcomeError("observation must be closed before it produces a record")
        entry = self.entry
        spec = self.spec
        sign = self.direction_sign
        row: Dict[str, Any] = {
            "entry_id": entry.entry_id,
            "candidate_key": entry.candidate_key,
            "study_id": entry.study_id,
            "source_period": entry.source_period,
            "regime_id": entry.regime_id,
            "decision_ts": entry.decision_ts,
            "entry_ts": entry.entry_ts,
            "direction": entry.direction.value,
            "entry_price": entry.entry_price,
            "entry_atr": entry.entry_atr,
            "model_id": entry.model_id,
            "model_hash": entry.model_hash,
            "score": entry.score,
            "score_decile": entry.score_decile,
            "threshold_id": entry.threshold_id,
            "maturity_bucket": entry.maturity_bucket,
            "maturity_seconds": entry.maturity_seconds,
            "selector_id": entry.selector_id,
        }

        if spec.confirmation is not None:
            row["confirmed"] = self.confirmed
            row["confirmation_ts"] = self.confirmation_ts
            row["seconds_to_confirmation"] = (
                (self.confirmation_ts - entry.entry_ts) / NS if self.confirmation_ts else None
            )
            row["confirmation_price"] = self.confirmation_price

        for seconds in spec.horizons_seconds:
            lab = horizon_label(seconds)
            res = self._horizon_results.get(seconds, {"status": OutcomeStatus.MISSING_DATA})
            mfe, mae = res.get("mfe"), res.get("mae")
            price = res.get("price")
            ret = (sign * (price - entry.entry_price)) if price is not None else None
            self._units(row, f"mfe_{lab}", mfe)
            self._units(row, f"mae_{lab}", mae)
            self._units(row, f"return_{lab}", ret)
            row[f"time_to_mfe_{lab}"] = (
                res["time_to_mfe_ns"] / NS if res.get("time_to_mfe_ns") is not None else None
            )
            row[f"time_to_mae_{lab}"] = (
                res["time_to_mae_ns"] / NS if res.get("time_to_mae_ns") is not None else None
            )
            row[f"price_{lab}"] = price
            row[f"status_{lab}"] = res["status"].value
            if spec.path_quality:
                self._quality(row, f"_{lab}", mfe, mae, ret)

        final_price = self.last_close
        final_ret = (sign * (final_price - entry.entry_price)) if final_price is not None else None
        self._units(row, "max_mfe", self.mfe)
        self._units(row, "max_mae", self.mae)
        self._units(row, "final_return", final_ret)
        row["time_to_max_mfe"] = self.time_to_mfe_ns / NS if self.time_to_mfe_ns is not None else None
        row["time_to_max_mae"] = self.time_to_mae_ns / NS if self.time_to_mae_ns is not None else None
        row["final_price"] = final_price
        if spec.path_quality:
            eps = spec.epsilon
            denom = max(self.mae, eps) if self.mae is not None else None
            row["max_mfe_mae_ratio"] = (self.mfe / denom) if (self.mfe is not None and denom) else None
            row["final_return_over_mae"] = (final_ret / denom) if (final_ret is not None and denom) else None
            row["max_mfe_minus_max_mae"] = (
                self.mfe - self.mae if (self.mfe is not None and self.mae is not None) else None
            )
            if self.mfe is not None and final_ret is not None and self.mfe > 0:
                row["retained_mfe_fraction_final"] = final_ret / self.mfe
                row["giveback_from_max_mfe"] = self.mfe - final_ret
            else:
                row["retained_mfe_fraction_final"] = None
                row["giveback_from_max_mfe"] = None

        for level in spec.diagnostic_levels_atr:
            lab = level_label(level)
            fav_ts = self._level_fav_ts.get(level)
            adv_ts = self._level_adv_ts.get(level)
            row[f"time_to_favorable_{lab}"] = (fav_ts - entry.entry_ts) / NS if fav_ts else None
            row[f"time_to_adverse_{lab}"] = (adv_ts - entry.entry_ts) / NS if adv_ts else None
            ambiguous = self._level_ambiguous.get(level, False)
            if fav_ts is None:
                before = False if adv_ts is not None else None
            elif adv_ts is None:
                before = True
            else:
                before = False if ambiguous else fav_ts < adv_ts
            row[f"favorable_before_adverse_{lab}"] = before
            row[f"first_touch_ambiguous_{lab}"] = bool(ambiguous)

        if spec.confirmation is not None:
            self._units(row, "pre_confirmation_mfe", self.pre_mfe)
            self._units(row, "pre_confirmation_mae", self.pre_mae)
            self._units(row, "post_confirmation_mfe", self.post_mfe)
            self._units(row, "post_confirmation_mae", self.post_mae)
            row["pre_confirmation_time_to_mfe"] = (
                self.pre_time_to_mfe_ns / NS if self.pre_time_to_mfe_ns is not None else None
            )
            row["pre_confirmation_time_to_mae"] = (
                self.pre_time_to_mae_ns / NS if self.pre_time_to_mae_ns is not None else None
            )
            row["post_confirmation_time_to_mfe"] = (
                self.post_time_to_mfe_ns / NS if self.post_time_to_mfe_ns is not None else None
            )
            row["post_confirmation_time_to_mae"] = (
                self.post_time_to_mae_ns / NS if self.post_time_to_mae_ns is not None else None
            )
            if self.confirmation_ts is None:
                row["post_confirmation_status"] = OutcomeStatus.MISSING_DATA.value
            else:
                row["post_confirmation_status"] = (
                    self.final_status.value if self.final_status else OutcomeStatus.RESOLVED.value
                )
            for seconds in spec.confirmation.post_horizons_seconds:
                lab = horizon_label(seconds)
                res = self._post_results.get(seconds, {"status": OutcomeStatus.MISSING_DATA, "price": None})
                price = res.get("price")
                base = self.confirmation_price
                pret = (sign * (price - base)) if (price is not None and base is not None) else None
                self._units(row, f"post_confirmation_return_{lab}", pret)
                row[f"post_confirmation_status_{lab}"] = res["status"].value

        row["outcome_status"] = self.final_status.value if self.final_status else None
        row["censor_reason"] = self.censor_reason
        row["resolved_at_ts"] = self.resolved_at_ts
        row["tracked_seconds"] = (
            (self.last_bar_ts - entry.entry_ts) / NS if self.last_bar_ts is not None else 0.0
        )
        row["bars_observed"] = self.bars_observed
        row["first_bar_ts"] = self.first_bar_ts
        row["last_bar_ts"] = self.last_bar_ts
        row["max_gap_seconds_observed"] = self.max_gap_ns / NS
        row["spec_sha256"] = spec.spec_sha256
        row["entry_sha256"] = entry.entry_sha256
        row["authorization_sha256"] = entry.authorization_sha256
        row["source_freeze_sha256"] = entry.source_freeze_sha256
        return row


class ForwardOutcomeTracker:
    """Bar-driven observer for a set of immutable proposed entries.

    ``primary_interval`` makes the tracker partition-safe. A partitioned run reads
    enough lookahead to resolve its own entries but emits only those anchored inside
    its primary interval, so a boundary entry is produced exactly once across the whole
    partition set and its outcomes are identical to the monolithic run's.
    """

    def __init__(
        self,
        spec: ForwardOutcomeSpec,
        *,
        entries: Optional[Iterable[ProposedEntry]] = None,
        primary_interval: Optional[Tuple[int, int]] = None,
    ) -> None:
        self.spec = spec
        self.primary_interval = (
            (int(primary_interval[0]), int(primary_interval[1])) if primary_interval else None
        )
        self._pending: List[Tuple[int, int, ProposedEntry]] = []
        self._active: Dict[str, ForwardObservation] = {}
        self._expiry: List[Tuple[int, int, str]] = []
        self._records: List[Dict[str, Any]] = []
        self._seen_ids: set[str] = set()
        self._seq = 0
        self._last_bar_ts: Optional[int] = None
        self.skipped_non_primary = 0
        self.finalized = False
        for entry in entries or ():
            self.add_entry(entry)

    # -- registration -----------------------------------------------------------
    def add_entry(self, entry: ProposedEntry) -> bool:
        if self.finalized:
            raise ForwardOutcomeError("cannot add entries to a finalized tracker")
        if entry.reference_price is not self.spec.reference_price:
            raise ForwardOutcomeError(
                f"entry {entry.entry_id} uses reference price {entry.reference_price.value} "
                f"but the spec froze {self.spec.reference_price.value}"
            )
        if self.spec.uses_atr and entry.entry_atr is None:
            raise ForwardOutcomeError(
                f"entry {entry.entry_id} has no frozen entry_atr but the spec declares "
                f"ATR-normalized excursions"
            )
        if self.primary_interval is not None:
            start, end = self.primary_interval
            if not (start <= entry.entry_ts <= end):
                self.skipped_non_primary += 1
                return False
        if entry.entry_id in self._seen_ids:
            raise ForwardOutcomeError(f"duplicate entry_id: {entry.entry_id}")
        self._seen_ids.add(entry.entry_id)
        self._seq += 1
        heapq.heappush(self._pending, (entry.entry_ts, self._seq, entry))
        return True

    def add_entries(self, entries: Iterable[ProposedEntry]) -> int:
        return sum(1 for e in entries if self.add_entry(e))

    # -- streaming --------------------------------------------------------------
    def on_bar(self, ts_open: int, ts_close: int, high: float, low: float, close: float) -> None:
        ts_open, ts_close = int(ts_open), int(ts_close)
        if ts_close <= ts_open:
            raise ForwardOutcomeError(
                f"bar close {ts_close} must follow bar open {ts_open}; a close-stamped "
                f"bar carries ts_init = ts_event + duration"
            )
        if self._last_bar_ts is not None and ts_close < self._last_bar_ts:
            raise ForwardOutcomeError("bars must be fed in non-decreasing close order")
        self._last_bar_ts = ts_close

        self._activate_due(ts_close)
        for obs in self._active.values():
            obs.on_bar(ts_open, ts_close, high, low, close)
        self._retire_due(ts_close)

    def on_nt_bar(self, bar: Any) -> None:
        """Adapter for a NautilusTrader ``Bar``: ts_event is OPEN, ts_init is CLOSE."""
        self.on_bar(int(bar.ts_event), int(bar.ts_init), float(bar.high), float(bar.low), float(bar.close))

    def _activate_due(self, ts_close: int) -> None:
        while self._pending and self._pending[0][0] <= ts_close:
            _, _, entry = heapq.heappop(self._pending)
            session_close = entry.session_close_ts
            if (
                session_close is None
                and self.spec.session_end_censoring
                and self.spec.session != "ALL"
            ):
                from utils.session_boundaries import session_close_ns

                session_close = session_close_ns(entry.entry_ts, self.spec.session)
            obs = ForwardObservation(entry, self.spec, session_close)
            self._active[entry.entry_id] = obs
            self._seq += 1
            heapq.heappush(self._expiry, (obs.close_deadline_ns, self._seq, entry.entry_id))

    def _retire_due(self, ts_close: int) -> None:
        while self._expiry and self._expiry[0][0] <= ts_close:
            deadline, _, entry_id = heapq.heappop(self._expiry)
            obs = self._active.get(entry_id)
            if obs is None:
                continue
            if obs.close_deadline_ns > deadline:
                # Confirmation extended the tracking budget; re-queue lazily rather than
                # rebuilding the heap.
                self._seq += 1
                heapq.heappush(self._expiry, (obs.close_deadline_ns, self._seq, entry_id))
                continue
            obs.close(ts_close)
            self._records.append(obs.to_record())
            del self._active[entry_id]

    # -- confirmation -----------------------------------------------------------
    def record_confirmation(self, entry_id: str, ts: int, price: float) -> None:
        obs = self._active.get(entry_id)
        if obs is None:
            raise ForwardOutcomeError(
                f"no active observation for entry {entry_id}; a confirmation can only be "
                f"recorded while its entry is still being tracked"
            )
        obs.record_confirmation(ts, price)
        self._seq += 1
        heapq.heappush(self._expiry, (obs.close_deadline_ns, self._seq, entry_id))

    # -- termination ------------------------------------------------------------
    def finalize(self, *, reason: str = "data_end") -> List[Dict[str, Any]]:
        """Dispose every observation, including ones that never started.

        An entry that produced no record would be a member of the population silently
        removed for being unresolved, which is selection on the future. Every registered
        primary entry leaves here with exactly one row.
        """
        if reason not in {"data_end", "horizon_budget"}:
            raise ForwardOutcomeError(f"unknown finalize reason: {reason!r}")
        if self.finalized:
            return list(self._records)
        now = self._last_bar_ts if self._last_bar_ts is not None else 0
        for obs in list(self._active.values()):
            obs.close(now, reason=reason)
            self._records.append(obs.to_record())
        self._active.clear()
        while self._pending:
            _, _, entry = heapq.heappop(self._pending)
            session_close = entry.session_close_ts
            obs = ForwardObservation(entry, self.spec, session_close)
            obs.close(now, reason=reason)
            self._records.append(obs.to_record())
        self._expiry.clear()
        self.finalized = True
        self._records.sort(key=lambda r: (r["entry_ts"], r["entry_id"]))
        return list(self._records)

    @property
    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def is_active(self, entry_id: str) -> bool:
        return entry_id in self._active


def compute_forward_outcomes(
    entries: Sequence[ProposedEntry],
    bars: Iterable[Sequence[Any]],
    spec: ForwardOutcomeSpec,
    *,
    confirmations: Optional[Dict[str, Tuple[int, float]]] = None,
    primary_interval: Optional[Tuple[int, int]] = None,
    finalize_reason: str = "data_end",
) -> List[Dict[str, Any]]:
    """Batch driver over an iterable of ``(ts_open, ts_close, high, low, close)`` bars.

    Identical machinery to the streaming path -- the same tracker, fed offline -- so an
    offline result and an in-replay result cannot diverge by construction.
    """
    tracker = ForwardOutcomeTracker(spec, entries=entries, primary_interval=primary_interval)
    pending_conf = dict(confirmations or {})
    for bar in bars:
        ts_open, ts_close, high, low, close = bar
        # A confirmation whose timestamp falls between two sampled bars must be
        # applied before the later bar; otherwise the later bar can incorrectly
        # mark the wait window as expired. A coincident confirmation is applied
        # after that bar, preserving the NT short-bar-before-parent-bar order.
        if pending_conf:
            due_before = [eid for eid, (cts, _) in pending_conf.items() if int(cts) < int(ts_close)]
            for eid in due_before:
                cts, cprice = pending_conf.pop(eid)
                if tracker.is_active(eid):
                    tracker.record_confirmation(eid, cts, cprice)
        tracker.on_bar(ts_open, ts_close, high, low, close)
        if pending_conf:
            due = [eid for eid, (cts, _) in pending_conf.items() if int(cts) == int(ts_close)]
            for eid in due:
                cts, cprice = pending_conf.pop(eid)
                if tracker.is_active(eid):
                    tracker.record_confirmation(eid, cts, cprice)
    return tracker.finalize(reason=finalize_reason)
