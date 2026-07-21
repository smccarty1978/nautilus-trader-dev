"""Isolate three 1-second execution contracts without running D10 policies.

The fixture deliberately selects a long entry bar whose low crosses a one-tick
stop below its open. Two tiny NT runs use the identical four-bar path. The
explicit-next-open contract is an OHLC research label, not an NT fill claim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy

from studies._shared_exit_mgmt.nt_runner import create_nq
from studies.pre_flip_d10_reversal_entry.common import AUDIT, year_catalog

BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
INSTRUMENT = InstrumentId.from_str("NQ.XCME")
TICK = 0.25
MULTIPLIER = 20.0


class FixtureConfig(StrategyConfig, frozen=True):
    trigger_price: float
    mode: str


class ContractFixture(Strategy):
    def __init__(self, config: FixtureConfig):
        super().__init__(config)
        self.cfg = config
        self.n = 0
        self.entry_id = None
        self.exit_id = None
        self.entry_fill_ts = None
        self.entry_fill_price = None
        self.stop_submit_ts = None
        self.stop_fill_ts = None
        self.stop_fill_price = None
        self.touch_detected_ts = None
        self.events: list[dict] = []

    def on_start(self):
        self.subscribe_bars(BarType.from_str(BAR_TYPE))

    def on_bar(self, bar):
        self.n += 1
        row = {
            "kind": "bar_callback", "ts_event": int(bar.ts_event),
            "ts_init": int(bar.ts_init), "open": float(bar.open),
            "high": float(bar.high), "low": float(bar.low), "close": float(bar.close),
        }
        self.events.append(row)
        if self.n == 1:
            order = self.order_factory.market(
                instrument_id=INSTRUMENT, order_side=OrderSide.BUY,
                quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK,
            )
            self.entry_id = order.client_order_id.value
            self.events.append({"kind": "entry_submit", "ts": int(bar.ts_init), "order": self.entry_id})
            self.submit_order(order)
            return

        if (self.cfg.mode == "close_detected" and self.entry_fill_ts is not None
                and self.exit_id is None and float(bar.low) <= self.cfg.trigger_price):
            self.touch_detected_ts = int(bar.ts_init)
            order = self.order_factory.market(
                instrument_id=INSTRUMENT, order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK,
                reduce_only=True,
            )
            self.exit_id = order.client_order_id.value
            self.stop_submit_ts = int(bar.ts_init)
            self.events.append({
                "kind": "close_detected_exit_submit", "ts": int(bar.ts_init),
                "trigger": self.cfg.trigger_price, "order": self.exit_id,
            })
            self.submit_order(order)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        self.events.append({
            "kind": "fill", "order": cid, "ts_event": int(event.ts_event),
            "price": float(event.last_px),
        })
        if cid == self.entry_id:
            self.entry_fill_ts = int(event.ts_event)
            self.entry_fill_price = float(event.last_px)
            if self.cfg.mode == "native_stop":
                order = self.order_factory.stop_market(
                    instrument_id=INSTRUMENT, order_side=OrderSide.SELL,
                    quantity=Quantity.from_int(1),
                    trigger_price=Price(self.cfg.trigger_price, 2),
                    time_in_force=TimeInForce.GTC, reduce_only=True,
                )
                self.exit_id = order.client_order_id.value
                # Order submission occurs in the entry-fill callback; NT does
                # not expose a separate nanosecond clock for the submission.
                self.stop_submit_ts = int(event.ts_event)
                self.events.append({
                    "kind": "native_stop_submit", "ts": int(event.ts_event),
                    "trigger": self.cfg.trigger_price, "order": self.exit_id,
                })
                self.submit_order(order)
        elif cid == self.exit_id:
            self.stop_fill_ts = int(event.ts_event)
            self.stop_fill_price = float(event.last_px)


def select_path():
    catalog = ParquetDataCatalog(str(year_catalog(2025)))
    start = pd.Timestamp("2025-03-03 23:00:00", tz="UTC")
    bars = catalog.bars(
        bar_types=[BAR_TYPE], start=start, end=start + pd.Timedelta(hours=2),
    )
    for i in range(len(bars) - 3):
        entry_bar = bars[i + 1]
        if float(entry_bar.low) <= float(entry_bar.open) - TICK:
            return bars[i:i + 4]
    raise RuntimeError("No deterministic entry bar with a one-tick downside crossing")


def run_nt(sample, trigger: float, mode: str) -> ContractFixture:
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"EXEC-{mode.upper()}"[:20],
        logging=LoggingConfig(log_level="WARNING"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)], bar_execution=True,
    )
    engine.add_instrument(create_nq())
    engine.add_data(sample)
    strategy = ContractFixture(FixtureConfig(trigger_price=trigger, mode=mode))
    engine.add_strategy(strategy)
    engine.run()
    engine.dispose()
    return strategy


def fmt_ts(value):
    if value is None or pd.isna(value):
        return None
    return str(pd.Timestamp(int(value), unit="ns", tz="UTC"))


def markdown_table(df: pd.DataFrame) -> str:
    def cell(value):
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return ""
        return str(value).replace("|", "\\|").replace("\n", " ")
    columns = list(df.columns)
    lines = ["| " + " | ".join(columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(cell(v) for v in row) + " |"
                 for row in df.itertuples(index=False, name=None))
    return "\n".join(lines)


def main():
    sample = select_path()
    decision_bar, entry_bar, next_bar = sample[0], sample[1], sample[2]
    expected_entry_open = float(entry_bar.open)
    trigger = expected_entry_open - TICK
    crossed = float(entry_bar.low) <= trigger

    native = run_nt(sample, trigger, "native_stop")
    conservative = run_nt(sample, trigger, "close_detected")

    intended_gross = (trigger - expected_entry_open) * MULTIPLIER
    native_gross = ((native.stop_fill_price - native.entry_fill_price) * MULTIPLIER
                    if native.stop_fill_price is not None else None)
    conservative_gross = ((conservative.stop_fill_price - conservative.entry_fill_price) * MULTIPLIER
                          if conservative.stop_fill_price is not None and conservative.entry_fill_price is not None else None)
    conservative_normalized = ((conservative.stop_fill_price - expected_entry_open) * MULTIPLIER
                               if conservative.stop_fill_price is not None else None)

    def delta(value):
        return value - intended_gross if value is not None else None

    common = {
        "decision_timestamp": int(decision_bar.ts_init),
        "expected_fill_bar_ts_event": int(entry_bar.ts_event),
        "expected_fill_bar_ts_init": int(entry_bar.ts_init),
        "expected_fill_open": expected_entry_open,
        "entry_bar_low": float(entry_bar.low),
        "entry_bar_high": float(entry_bar.high),
        "stop_trigger_price": trigger,
        "entry_bar_crosses_stop": crossed,
    }
    rows = [
        {
            "contract": "NT native bar matcher",
            **common,
            "actual_entry_fill_timestamp": native.entry_fill_ts,
            "actual_entry_fill_price": native.entry_fill_price,
            "assumed_entry_fill_timestamp": None,
            "assumed_entry_fill_price": None,
            "stop_submission_timestamp": native.stop_submit_ts,
            "stop_active_on_entry_bar": False,
            "stop_fill_timestamp": native.stop_fill_ts,
            "stop_fill_price": native.stop_fill_price,
            "gross_pnl_usd": native_gross,
            "pnl_difference_vs_intended_usd": delta(native_gross),
            "pnl_basis": "engine-observed entry and exit fills",
            "evidence_type": "NT BacktestEngine observed",
        },
        {
            "contract": "Explicit next-1s-open + immediate stop",
            **common,
            "actual_entry_fill_timestamp": None,
            "actual_entry_fill_price": None,
            "assumed_entry_fill_timestamp": int(entry_bar.ts_event),
            "assumed_entry_fill_price": expected_entry_open,
            "stop_submission_timestamp": int(entry_bar.ts_event),
            "stop_active_on_entry_bar": True,
            "stop_fill_timestamp": None,
            "stop_fill_price": None,
            "assumed_stop_touch_window_start": int(entry_bar.ts_event),
            "assumed_stop_touch_window_end": int(entry_bar.ts_init),
            "assumed_stop_fill_price": trigger,
            "gross_pnl_usd": intended_gross,
            "pnl_difference_vs_intended_usd": 0.0,
            "pnl_basis": "1s OHLC label: assumed open entry and adverse-touch stop price; time unknown within bar",
            "evidence_type": "1s OHLC research label; adverse touch assumed, not NT fill",
        },
        {
            "contract": "Close-detected stop + next market fill",
            **common,
            "actual_entry_fill_timestamp": conservative.entry_fill_ts,
            "actual_entry_fill_price": conservative.entry_fill_price,
            "assumed_entry_fill_timestamp": None,
            "assumed_entry_fill_price": None,
            "stop_submission_timestamp": conservative.stop_submit_ts,
            "stop_active_on_entry_bar": False,
            "stop_fill_timestamp": conservative.stop_fill_ts,
            "stop_fill_price": conservative.stop_fill_price,
            "gross_pnl_usd": conservative_gross,
            "pnl_difference_vs_intended_usd": delta(conservative_gross),
            "exit_only_normalized_pnl_from_expected_open_usd": conservative_normalized,
            "pnl_basis": "engine-observed entry and exit fills; normalized exit diagnostic separate",
            "evidence_type": "OHLC close detection + NT market-exit fill; delayed-information contract",
        },
    ]
    comparison = pd.DataFrame(rows)
    timestamp_cols = [
        "decision_timestamp", "expected_fill_bar_ts_event", "expected_fill_bar_ts_init",
        "actual_entry_fill_timestamp", "assumed_entry_fill_timestamp",
        "stop_submission_timestamp", "stop_fill_timestamp",
        "assumed_stop_touch_window_start", "assumed_stop_touch_window_end",
    ]
    for c in timestamp_cols:
        comparison[c] = pd.array([row.get(c) for row in rows], dtype="Int64")
    comparison.to_parquet(AUDIT / "execution_contract_comparison.parquet", index=False)

    trace = {
        "fixture_bars": [{
            "ts_event": int(b.ts_event), "ts_init": int(b.ts_init),
            "open": float(b.open), "high": float(b.high),
            "low": float(b.low), "close": float(b.close),
        } for b in sample],
        "native_events": native.events,
        "close_detected_events": conservative.events,
    }
    (AUDIT / "execution_contract_trace.json").write_text(
        json.dumps(trace, indent=2), encoding="utf-8",
    )

    table = comparison.copy()
    for c in timestamp_cols:
        table[c] = table[c].map(fmt_ts)
    report = f"""# Minimal execution-contract report

## Scope

This report isolates execution mechanics only. The D10 reversal policy study was
not run. All contracts use the same four adjusted Databento one-second bars from
`NQ_v0_2025_fixed` (`ts_init = ts_event + 1 second`). The intended long entry is
the next bar open with a one-tick fixed stop, deliberately crossed by the entry
bar low. The path was selected ex post solely to force this diagnostic edge
case; it is not a trade-selection rule or a performance sample.

## Comparison

{markdown_table(table)}

## Interpretation

1. **NT native bar matcher:** engine-observed evidence. The entry and stop fills
   are whatever NT actually produced. The stop submitted inside the entry-fill
   callback was not active against the entry bar's already-processing OHLC.
2. **Explicit next-1s-open:** an OHLC research label. It assumes the entry at the
   recorded open and an adverse-touch stop price when the bar crosses it. The
   touch/fill time is unknown inside `[ts_event, ts_init]`; no exact timestamp or
   actual fill is claimed, and intrabar ordering is unresolved.
3. **Close-detected:** stop touch becomes known only at entry-bar close. A market
   exit is then submitted and NT supplies the next fill. Primary PnL uses both
   engine-observed fills, consistently with Contract 1. A separately named
   normalized diagnostic isolates the exit from the entry-price mismatch.

## Limitation

No tick/quote path was used. Therefore this report does not claim fill-anchored
stop accuracy. Contract 2 is a labeled 1s-OHLC assumption; Contract 3 is a
delayed-information convention and is not guaranteed economically conservative
under gaps. The full D10 study remains blocked until
one contract is explicitly selected.
"""
    (AUDIT / "execution_contract_report.md").write_text(report, encoding="utf-8")
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
