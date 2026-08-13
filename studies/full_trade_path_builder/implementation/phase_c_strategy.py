"""NautilusTrader event-loop selector for canonical Phase C entries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy


def trade_id_for(
    instrument_id: str,
    model_id: str,
    regime_start_ns: int,
    checkpoint_decision_ns: int,
    trade_direction: int,
) -> str:
    payload = json.dumps(
        [
            instrument_id,
            model_id,
            int(regime_start_ns),
            int(checkpoint_decision_ns),
            int(trade_direction),
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PhaseCSelectorConfig(StrategyConfig, frozen=True):
    score_path: str
    prior_selected_json: str = "[]"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bullish_threshold: float = 0.5697449423968936
    bearish_threshold: float = 0.5641320087327389


class PhaseCSelector(Strategy):
    def __init__(self, config: PhaseCSelectorConfig):
        super().__init__(config)
        self._bar_type = BarType.from_str(config.bar_type_1s)
        table = pq.read_table(Path(config.score_path))
        rows = table.to_pylist()
        self._rows = {int(row["checkpoint_decision_ns"]): row for row in rows}
        if len(self._rows) != len(rows):
            raise RuntimeError("duplicate Phase B checkpoint keys")
        self.score_keys = set(self._rows)
        self.dispatched_keys: set[int] = set()
        self.selected_keys = set(json.loads(config.prior_selected_json))
        self.selections: list[dict] = []
        self.dispatched_score_rows = 0

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self._bar_type:
            return
        decision_ns = int(bar.ts_init)
        row = self._rows.get(decision_ns)
        if row is None:
            return
        if decision_ns in self.dispatched_keys:
            raise RuntimeError(f"duplicate Phase C dispatch: {decision_ns}")
        self.dispatched_keys.add(decision_ns)
        if int(bar.ts_event) >= decision_ns:
            raise RuntimeError("Phase C dispatch bar is not completed")
        self.dispatched_score_rows += 1
        self._consider(
            row=row,
            prefix="bullish",
            threshold=float(self.config.bullish_threshold),
            direction=-1,
            target_seconds_field="seconds_to_next_bearish_confirm_flip",
            within_300_field="bearish_confirm_within_300s",
            within_600_field="bearish_confirm_within_600s",
        )
        self._consider(
            row=row,
            prefix="bearish",
            threshold=float(self.config.bearish_threshold),
            direction=1,
            target_seconds_field="seconds_to_next_bullish_confirm_flip",
            within_300_field="bullish_confirm_within_300s",
            within_600_field="bullish_confirm_within_600s",
        )

    def _consider(
        self,
        row: dict,
        prefix: str,
        threshold: float,
        direction: int,
        target_seconds_field: str,
        within_300_field: str,
        within_600_field: str,
    ) -> None:
        if not row[f"{prefix}_in_domain"] or not row[f"{prefix}_score_available"]:
            return
        probability = row[f"{prefix}_probability"]
        if probability is None or float(probability) < threshold:
            return
        model_id = row[f"{prefix}_model_id"]
        regime_start_ns = int(row["regime_start_ns"])
        regime_key = json.dumps(
            [row["instrument_id"], model_id, regime_start_ns],
            separators=(",", ":"),
        )
        if regime_key in self.selected_keys:
            return
        self.selected_keys.add(regime_key)
        decision_ns = int(row["checkpoint_decision_ns"])
        trade_id = trade_id_for(
            row["instrument_id"], model_id, regime_start_ns, decision_ns, direction
        )
        seconds = row[target_seconds_field]
        confirm_flip_ns = (
            None if seconds is None else decision_ns + int(round(float(seconds) * 1e9))
        )
        self.selections.append(
            {
                "trade_id": trade_id,
                "trade_id_prefix": trade_id[:2],
                "instrument_id": row["instrument_id"],
                "entry_model_id": model_id,
                "trade_direction": direction,
                "trade_direction_name": "LONG" if direction == 1 else "SHORT",
                "entry_regime_direction": int(row["prevailing_regime"]),
                "regime_start_ns": regime_start_ns,
                "checkpoint_decision_ns": decision_ns,
                "entry_year": int(row["study_year"]),
                "entry_month": int(row["study_month"]),
                "session": row["session"],
                "checkpoint_reference_price": float(row["checkpoint_reference_price"]),
                "atr_at_entry": float(row["atr_at_score"]),
                "entry_raw_score": float(row[f"{prefix}_raw_score"]),
                "entry_probability": float(probability),
                "entry_percentile": None,
                "entry_decile": None,
                "entry_top_2_5_threshold": threshold,
                "threshold_membership_operator": ">=",
                "threshold_reference_overlap_waiver": True,
                "bullish_raw_score_at_entry": row["bullish_raw_score"],
                "bullish_probability_at_entry": row["bullish_probability"],
                "bullish_percentile_at_entry": None,
                "bullish_in_domain_at_entry": bool(row["bullish_in_domain"]),
                "bearish_raw_score_at_entry": row["bearish_raw_score"],
                "bearish_probability_at_entry": row["bearish_probability"],
                "bearish_percentile_at_entry": None,
                "bearish_in_domain_at_entry": bool(row["bearish_in_domain"]),
                "confirm_flip_ns": confirm_flip_ns,
                "confirm_flip_direction": direction if confirm_flip_ns is not None else None,
                "seconds_entry_to_confirm": seconds,
                "confirmed_within_300s": row[within_300_field],
                "confirmed_within_600s": row[within_600_field],
                "selection_regime_key": regime_key,
                "source_feature_vector_hash": row[f"{prefix}_feature_vector_hash"],
            }
        )
