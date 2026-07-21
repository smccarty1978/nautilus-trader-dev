"""Execution model and cost scenarios for RL regime feasibility study.

NQ contract specs:
  Multiplier : $20/point
  Tick size  : 0.25 points = $5/tick

Entry semantics (OFFLINE label computation, mirroring bar_execution=True):
  - Market entry fills at next 1s bar OPEN after decision
      idx = searchsorted(ts_events, obs_time, side='left')
      entry_px = opens[idx]
  - Stop-market:
      if opens[i] breaches stop side  → fill at opens[i]
      elif bar low/high touches stop  → fill at stop_price
      Both adjusted outward by slippage_pts
  - Horizon exit at first bar where ts_event >= entry_ts + horizon_ns:
      fill at that bar's OPEN

Three cost scenarios; caller selects by name:
  base        $5 RT commission, 0 slippage ticks
  base_plus_1t $5 RT + 1 tick/side additional slippage
  base_plus_2t $5 RT + 2 ticks/side additional slippage
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

NQ_MULTIPLIER      = 20.0    # $/point
NQ_TICK_SIZE       = 0.25    # points per tick
NQ_TICK_VALUE      = 5.0     # $/tick
CAT_STOP_ATR       = 1.50    # catastrophic stop in ATR multiples
MAX_EPISODE_S      = 1800    # 30-minute max episode duration
NS_PER_S           = 1_000_000_000
RTH_OPEN_UTC_H     = 13      # 13:30 UTC = 8:30 CT RTH open
RTH_OPEN_UTC_M     = 30
RTH_CLOSE_UTC_H    = 20      # 20:00 UTC = 3:00 PM CT RTH close
RTH_CLOSE_UTC_M    = 0


@dataclass(frozen=True)
class CostScenario:
    name: str
    commission_rt_usd: float
    slippage_ticks_entry: float
    slippage_ticks_stop: float

    @property
    def slippage_entry_pts(self) -> float:
        return self.slippage_ticks_entry * NQ_TICK_SIZE

    @property
    def slippage_stop_pts(self) -> float:
        return self.slippage_ticks_stop * NQ_TICK_SIZE

    @property
    def total_rt_cost_usd(self) -> float:
        return (
            self.commission_rt_usd
            + (self.slippage_ticks_entry + self.slippage_ticks_stop) * NQ_TICK_VALUE
        )


COST_BASE     = CostScenario("base",         commission_rt_usd=5.0, slippage_ticks_entry=0.0, slippage_ticks_stop=0.0)
COST_PLUS_1T  = CostScenario("base_plus_1t", commission_rt_usd=5.0, slippage_ticks_entry=1.0, slippage_ticks_stop=1.0)
COST_PLUS_2T  = CostScenario("base_plus_2t", commission_rt_usd=5.0, slippage_ticks_entry=2.0, slippage_ticks_stop=2.0)

ALL_SCENARIOS = [COST_BASE, COST_PLUS_1T, COST_PLUS_2T]
SCENARIO_BY_NAME = {s.name: s for s in ALL_SCENARIOS}


def save_contract(output_dir: Path) -> None:
    """Write execution_contract.json to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = {
        "nq_multiplier":      NQ_MULTIPLIER,
        "nq_tick_size":       NQ_TICK_SIZE,
        "nq_tick_value":      NQ_TICK_VALUE,
        "cat_stop_atr":       CAT_STOP_ATR,
        "max_episode_s":      MAX_EPISODE_S,
        "fill_model":         "next_1s_bar_open",
        "stop_model":         "gap_or_touch",
        "cost_scenarios":     [asdict(s) for s in ALL_SCENARIOS],
        "note": (
            "Entry fills at next 1s bar open after decision_ts. "
            "Stop: gap-through fills at bar.open (direction-adjusted for slippage); "
            "touch fills at stop_price (direction-adjusted for slippage). "
            "Existing repo uses COMM=4.06 dollars; this study uses $5 RT per spec. "
            "Horizon exit at first 1s bar open at-or-after entry_ts + horizon_ns."
        ),
    }
    path = output_dir / "execution_contract.json"
    with open(path, "w") as f:
        json.dump(contract, f, indent=2)
    print(f"  wrote {path}")
