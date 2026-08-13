"""NautilusTrader one-second factual path collector for Phase D."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow.parquet as pq
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

NS = 1_000_000_000


class PhaseDPathConfig(StrategyConfig, frozen=True):
    plan_path: str
    score_paths_json: str
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bullish_top_10: float = 0.43167249785595935
    bullish_top_5: float = 0.5067081427626979
    bullish_top_2_5: float = 0.5697449423968936
    bearish_top_5: float = 0.5084619230529974
    bearish_top_2_5: float = 0.5641320087327389


class PhaseDPathCollector(Strategy):
    def __init__(self, config: PhaseDPathConfig):
        super().__init__(config)
        self._bar_type = BarType.from_str(config.bar_type_1s)
        payload = json.loads(Path(config.plan_path).read_text(encoding="utf-8"))
        self._plans = sorted(
            payload["trades"], key=lambda row: row["checkpoint_decision_ns"]
        )
        self._flips = sorted(
            payload["regime_flips"], key=lambda row: row["confirm_flip_ns"]
        )
        score_rows = []
        score_columns = ["checkpoint_decision_ns"]
        for prefix in ("bullish", "bearish"):
            score_columns.extend(
                [
                    f"{prefix}_score_available",
                    f"{prefix}_raw_score",
                    f"{prefix}_probability",
                    f"{prefix}_percentile",
                    f"{prefix}_in_domain",
                ]
            )
        for raw_path in json.loads(config.score_paths_json):
            score_rows.extend(
                pq.read_table(Path(raw_path), columns=score_columns).to_pylist()
            )
        by_timestamp = {
            int(row["checkpoint_decision_ns"]): row for row in score_rows
        }
        self._scores = [by_timestamp[key] for key in sorted(by_timestamp)]
        self._score_index = 0
        self._flip_index = 0
        self._plan_index = 0
        self._regime_direction = 0
        self._latest_scores: dict[str, dict | None] = {
            "bullish": None,
            "bearish": None,
        }
        self._active: dict[str, dict] = {}
        self._pending: dict[str, dict] = {}
        self.path_rows: list[dict] = []
        self.summary_rows: list[dict] = []
        self.last_bar_close_ns: int | None = None
        self.last_bar_close: float | None = None

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self._bar_type:
            return
        te, ti = int(bar.ts_event), int(bar.ts_init)
        if te >= ti:
            raise RuntimeError("Phase D path source bar is not completed")
        o, h, l, c = map(float, (bar.open, bar.high, bar.low, bar.close))
        self.last_bar_close_ns, self.last_bar_close = ti, c
        self._advance_scores(ti)
        self._advance_regime_strictly_before(ti)
        self._complete_pending_after_exit(te, o)
        self._activate_due(te)

        to_pending = []
        to_censor = []
        for trade_id, state in list(self._active.items()):
            fallback_ns = state["selection"]["fallback_exit_flip_ns"]
            if fallback_ns is not None and ti > fallback_ns:
                to_censor.append((trade_id, "fallback_boundary_bar_missing"))
                continue
            if te < state["selection"]["checkpoint_decision_ns"]:
                continue
            if ti > state["selection"]["planned_path_end_ns"]:
                continue
            self._append_path_row(state, te, ti, o, h, l, c)
            if fallback_ns is not None and ti == fallback_ns:
                to_pending.append(trade_id)
        for trade_id in to_pending:
            state = self._active.pop(trade_id)
            state["path_is_complete"] = True
            self._pending[trade_id] = state
        for trade_id, reason in to_censor:
            state = self._active.pop(trade_id)
            self._finalize_censored(state, reason)

    def on_stop(self) -> None:
        for state in list(self._pending.values()):
            self._append_summary(state)
        self._pending.clear()
        for state in list(self._active.values()):
            self._finalize_censored(state, "sealed_or_data_boundary")
        self._active.clear()

    def _advance_scores(self, timestamp_ns: int) -> None:
        while (
            self._score_index < len(self._scores)
            and self._scores[self._score_index]["checkpoint_decision_ns"]
            <= timestamp_ns
        ):
            row = self._scores[self._score_index]
            for prefix in ("bullish", "bearish"):
                if row[f"{prefix}_score_available"]:
                    self._latest_scores[prefix] = {
                        "raw_score": row[f"{prefix}_raw_score"],
                        "probability": row[f"{prefix}_probability"],
                        "percentile": row[f"{prefix}_percentile"],
                        "in_domain": row[f"{prefix}_in_domain"],
                        "source_ns": int(row["checkpoint_decision_ns"]),
                    }
            self._score_index += 1

    def _advance_regime_strictly_before(self, timestamp_ns: int) -> None:
        while (
            self._flip_index < len(self._flips)
            and self._flips[self._flip_index]["confirm_flip_ns"] < timestamp_ns
        ):
            self._regime_direction = int(
                self._flips[self._flip_index]["new_direction"]
            )
            self._flip_index += 1

    def _activate_due(self, bar_open_ns: int) -> None:
        while (
            self._plan_index < len(self._plans)
            and self._plans[self._plan_index]["checkpoint_decision_ns"]
            <= bar_open_ns
        ):
            selection = self._plans[self._plan_index]
            trade_id = selection["trade_id"]
            if trade_id in self._active or trade_id in self._pending:
                raise RuntimeError(f"duplicate Phase D trade activation: {trade_id}")
            self._active[trade_id] = {
                "selection": selection,
                "path_sequence": 0,
                "running_mfe_atr": 0.0,
                "running_mae_atr": 0.0,
                "mfe_ns": int(selection["checkpoint_decision_ns"]),
                "mae_ns": int(selection["checkpoint_decision_ns"]),
                "first_eligible_bar_open_ns": None,
                "first_eligible_bar_open_price": None,
                "confirm_flip_close_price": None,
                "first_bar_after_confirm_open_ns": None,
                "first_bar_after_confirm_open_price": None,
                "fallback_exit_flip_close_price": None,
                "first_bar_after_fallback_exit_open_ns": None,
                "first_bar_after_fallback_exit_open_price": None,
                "last_path_index": None,
                "last_path_close_ns": None,
                "last_path_close": None,
                "path_is_complete": False,
                "opposite_score_at_confirm": None,
                "opposite_probability_at_confirm": None,
                "opposite_percentile_at_confirm": None,
                "max_opposite_score_after_confirm": None,
                "max_opposite_probability_after_confirm": None,
                "max_opposite_percentile_after_confirm": None,
                "max_opposite_score_ns": None,
                "opposite_first_top_10_ns": None,
                "opposite_first_top_5_ns": None,
                "opposite_first_top_2_5_ns": None,
                "opposite_last_source_ns": None,
                "censor_reason": None,
            }
            self._plan_index += 1

    def _score_fields(self, prefix: str, timestamp_ns: int) -> dict:
        score = self._latest_scores[prefix]
        if score is None:
            return {
                f"{prefix}_raw_score": None,
                f"{prefix}_probability": None,
                f"{prefix}_percentile": None,
                f"{prefix}_in_domain": None,
                f"{prefix}_score_source_ns": None,
                f"{prefix}_score_age_seconds": None,
                f"{prefix}_is_carried_forward": None,
            }
        source = score["source_ns"]
        return {
            f"{prefix}_raw_score": score["raw_score"],
            f"{prefix}_probability": score["probability"],
            f"{prefix}_percentile": score["percentile"],
            f"{prefix}_in_domain": score["in_domain"],
            f"{prefix}_score_source_ns": source,
            f"{prefix}_score_age_seconds": (timestamp_ns - source) / NS,
            f"{prefix}_is_carried_forward": source != timestamp_ns,
        }

    def _append_path_row(
        self,
        state: dict,
        te: int,
        ti: int,
        o: float,
        h: float,
        l: float,
        c: float,
    ) -> None:
        selection = state["selection"]
        direction = int(selection["trade_direction"])
        reference = float(selection["checkpoint_reference_price"])
        atr = float(selection["atr_at_entry"])
        if atr <= 0 or not math.isfinite(atr):
            raise RuntimeError(f"invalid entry ATR: {selection['trade_id']}")
        open_pnl = direction * (o - reference) / atr
        close_pnl = direction * (c - reference) / atr
        favorable = ((h - reference) if direction == 1 else (reference - l)) / atr
        adverse = ((l - reference) if direction == 1 else (reference - h)) / atr
        new_mfe = favorable > state["running_mfe_atr"] + 1e-15
        new_mae = adverse < state["running_mae_atr"] - 1e-15
        if new_mfe:
            state["running_mfe_atr"] = favorable
            state["mfe_ns"] = ti
        if new_mae:
            state["running_mae_atr"] = adverse
            state["mae_ns"] = ti
        touches = l <= reference <= h
        confirm_ns = selection["confirm_flip_ns"]
        fallback_ns = selection["fallback_exit_flip_ns"]
        is_confirm = confirm_ns is not None and ti == confirm_ns
        is_fallback = fallback_ns is not None and ti == fallback_ns
        if state["first_eligible_bar_open_ns"] is None:
            state["first_eligible_bar_open_ns"] = te
            state["first_eligible_bar_open_price"] = o
        if confirm_ns is not None and ti == confirm_ns:
            state["confirm_flip_close_price"] = c
        if (
            confirm_ns is not None
            and te >= confirm_ns
            and state["first_bar_after_confirm_open_ns"] is None
        ):
            state["first_bar_after_confirm_open_ns"] = te
            state["first_bar_after_confirm_open_price"] = o
        if is_fallback:
            state["fallback_exit_flip_close_price"] = c
        self._update_opposite_summary(state, ti)
        state["path_sequence"] += 1
        row = {
            "trade_id": selection["trade_id"],
            "trade_id_prefix": selection["trade_id_prefix"],
            "entry_year": selection["entry_year"],
            "entry_month": selection["entry_month"],
            "path_sequence": state["path_sequence"],
            "timestamp_open_ns": te,
            "timestamp_close_ns": ti,
            "seconds_from_decision": (
                ti - selection["checkpoint_decision_ns"]
            ) / NS,
            "seconds_from_confirm": (
                None if confirm_ns is None else (ti - confirm_ns) / NS
            ),
            "trade_direction": direction,
            "trade_direction_name": selection["trade_direction_name"],
            "prevailing_regime": self._regime_direction,
            "is_regime_confirmed": self._regime_direction != 0,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "open_pnl_atr": open_pnl,
            "close_pnl_atr": close_pnl,
            "favorable_intrabar_extreme_atr": favorable,
            "adverse_intrabar_extreme_atr": adverse,
            "running_mfe_atr": state["running_mfe_atr"],
            "running_mae_atr": state["running_mae_atr"],
            "running_close_pnl_atr": close_pnl,
            "close_drawdown_from_running_mfe_atr": (
                close_pnl - state["running_mfe_atr"]
            ),
            "worst_intrabar_drawdown_from_running_mfe_atr": (
                adverse - state["running_mfe_atr"]
            ),
            "is_first_path_bar": state["path_sequence"] == 1,
            "is_confirm_flip_boundary": is_confirm,
            "is_fallback_exit_boundary": is_fallback,
            "is_final_path_bar": is_fallback,
            "is_new_running_mfe": new_mfe,
            "is_new_running_mae": new_mae,
            "touches_entry_this_bar": touches,
            "intrabar_ordering": (
                "ordering_ambiguous_same_bar"
                if touches and new_mfe
                else "ordering_deterministic"
            ),
            **self._score_fields("bullish", ti),
            **self._score_fields("bearish", ti),
        }
        self.path_rows.append(row)
        state["last_path_index"] = len(self.path_rows) - 1
        state["last_path_close_ns"] = ti
        state["last_path_close"] = c

    def _update_opposite_summary(self, state: dict, timestamp_ns: int) -> None:
        selection = state["selection"]
        confirm_ns = selection["confirm_flip_ns"]
        if confirm_ns is None or timestamp_ns < confirm_ns:
            return
        prefix = "bullish" if selection["trade_direction"] == 1 else "bearish"
        score = self._latest_scores[prefix]
        if score is None:
            return
        if state["opposite_score_at_confirm"] is None:
            state["opposite_score_at_confirm"] = score["raw_score"]
            state["opposite_probability_at_confirm"] = score["probability"]
            state["opposite_percentile_at_confirm"] = score["percentile"]
        source = score["source_ns"]
        if source < confirm_ns or source == state["opposite_last_source_ns"]:
            return
        state["opposite_last_source_ns"] = source
        probability = float(score["probability"])
        current_max = state["max_opposite_probability_after_confirm"]
        if current_max is None or probability > current_max:
            state["max_opposite_score_after_confirm"] = score["raw_score"]
            state["max_opposite_probability_after_confirm"] = probability
            state["max_opposite_percentile_after_confirm"] = score["percentile"]
            state["max_opposite_score_ns"] = source
        if prefix == "bullish":
            top10, top5, top25 = (
                float(self.config.bullish_top_10),
                float(self.config.bullish_top_5),
                float(self.config.bullish_top_2_5),
            )
        else:
            top10, top5, top25 = (
                None,
                float(self.config.bearish_top_5),
                float(self.config.bearish_top_2_5),
            )
        for field, threshold in (
            ("opposite_first_top_10_ns", top10),
            ("opposite_first_top_5_ns", top5),
            ("opposite_first_top_2_5_ns", top25),
        ):
            if (
                threshold is not None
                and state[field] is None
                and probability >= threshold
            ):
                state[field] = source

    def _complete_pending_after_exit(self, bar_open_ns: int, open_price: float) -> None:
        for trade_id, state in list(self._pending.items()):
            fallback = state["selection"]["fallback_exit_flip_ns"]
            if fallback is not None and bar_open_ns >= fallback:
                state["first_bar_after_fallback_exit_open_ns"] = bar_open_ns
                state["first_bar_after_fallback_exit_open_price"] = open_price
                self._append_summary(state)
                del self._pending[trade_id]

    def _finalize_censored(self, state: dict, reason: str) -> None:
        state["censor_reason"] = reason
        index = state["last_path_index"]
        if index is not None:
            self.path_rows[index]["is_final_path_bar"] = True
        self._append_summary(state)

    def _append_summary(self, state: dict) -> None:
        selection = state["selection"]
        direction = int(selection["trade_direction"])
        atr = float(selection["atr_at_entry"])
        reference = float(selection["checkpoint_reference_price"])
        complete = bool(state["path_is_complete"])
        fallback_price = state["fallback_exit_flip_close_price"]
        return_points = (
            None
            if not complete or fallback_price is None
            else direction * (fallback_price - reference)
        )
        return_atr = None if return_points is None else return_points / atr
        mfe_atr = max(0.0, float(state["running_mfe_atr"]))
        mae_atr = max(0.0, -float(state["running_mae_atr"]))
        capture = (
            None
            if return_atr is None or mfe_atr <= 0
            else return_atr / mfe_atr
        )
        giveback = None if return_atr is None else mfe_atr - return_atr
        fallback_ns = selection["fallback_exit_flip_ns"]
        def lead(field: str):
            value = state[field]
            return (
                None
                if value is None or fallback_ns is None
                else (fallback_ns - value) / NS
            )
        summary = {
            **selection,
            "first_eligible_bar_open_ns": state["first_eligible_bar_open_ns"],
            "first_eligible_bar_open_price": state["first_eligible_bar_open_price"],
            "confirm_flip_close_price": state["confirm_flip_close_price"],
            "first_bar_after_confirm_open_ns": state[
                "first_bar_after_confirm_open_ns"
            ],
            "first_bar_after_confirm_open_price": state[
                "first_bar_after_confirm_open_price"
            ],
            "fallback_exit_flip_close_price": fallback_price,
            "first_bar_after_fallback_exit_open_ns": state[
                "first_bar_after_fallback_exit_open_ns"
            ],
            "first_bar_after_fallback_exit_open_price": state[
                "first_bar_after_fallback_exit_open_price"
            ],
            "seconds_entry_to_fallback_exit": (
                None
                if fallback_ns is None
                else (fallback_ns - selection["checkpoint_decision_ns"]) / NS
            ),
            "seconds_confirm_to_fallback_exit": (
                None
                if fallback_ns is None or selection["confirm_flip_ns"] is None
                else (fallback_ns - selection["confirm_flip_ns"]) / NS
            ),
            "path_is_complete": complete,
            "is_right_censored": not complete,
            "censor_ns": None if complete else state["last_path_close_ns"],
            "censor_reason": None if complete else state["censor_reason"],
            "terminal_mark_price": None if complete else state["last_path_close"],
            "terminal_mark_ns": None if complete else state["last_path_close_ns"],
            "fallback_exit_mark_return_points": return_points,
            "fallback_exit_mark_return_atr": return_atr,
            "full_trade_mfe_points": mfe_atr * atr,
            "full_trade_mfe_atr": mfe_atr,
            "full_trade_mfe_ns": state["mfe_ns"],
            "full_trade_mae_points": mae_atr * atr,
            "full_trade_mae_atr": mae_atr,
            "full_trade_mae_ns": state["mae_ns"],
            "mfe_capture_ratio": capture,
            "giveback_from_mfe_atr": giveback,
            "giveback_from_mfe_pct": (
                None if giveback is None or mfe_atr <= 0 else giveback / mfe_atr
            ),
            "path_first_timestamp_ns": state["first_eligible_bar_open_ns"],
            "path_final_timestamp_ns": state["last_path_close_ns"],
            "path_row_count": state["path_sequence"],
            "opposite_exit_model_id": (
                "BULLISH_STRICT_top25_gbt_v2"
                if direction == 1
                else "LONG_STRICT_top25_gbt_v2"
            ),
            "opposite_score_at_confirm": state["opposite_score_at_confirm"],
            "opposite_probability_at_confirm": state[
                "opposite_probability_at_confirm"
            ],
            "opposite_percentile_at_confirm": state[
                "opposite_percentile_at_confirm"
            ],
            "max_opposite_score_after_confirm": state[
                "max_opposite_score_after_confirm"
            ],
            "max_opposite_probability_after_confirm": state[
                "max_opposite_probability_after_confirm"
            ],
            "max_opposite_percentile_after_confirm": state[
                "max_opposite_percentile_after_confirm"
            ],
            "max_opposite_score_ns": state["max_opposite_score_ns"],
            "opposite_first_top_10_ns": state["opposite_first_top_10_ns"],
            "opposite_first_top_5_ns": state["opposite_first_top_5_ns"],
            "opposite_first_top_2_5_ns": state["opposite_first_top_2_5_ns"],
            "seconds_top_10_to_fallback_exit": lead("opposite_first_top_10_ns"),
            "seconds_top_5_to_fallback_exit": lead("opposite_first_top_5_ns"),
            "seconds_top_2_5_to_fallback_exit": lead(
                "opposite_first_top_2_5_ns"
            ),
            "opposite_top_10_unavailable_reason": (
                "BEARISH_TOP_10_NOT_FROZEN" if direction == -1 else None
            ),
            "threshold_reference_overlap_disclosure": (
                "The threshold reference population overlaps calendar year 2025 "
                "of the study population. Results are descriptive and must not be "
                "represented as threshold-out-of-sample for 2025."
            ),
        }
        self.summary_rows.append(summary)
