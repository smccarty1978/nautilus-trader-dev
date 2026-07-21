import os
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
OUT_DIR = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NQ_MULTIPLIER = 20.0
TICK_SIZE = 0.25

def simulate_mbp1_slippage(year: int, policy: str):
    # NOTE: This is NOT real MBP-1 (market-by-price level-1 quote/tick) execution
    # validation. The data catalog (data/catalog/NQ_v0_2020_2026) contains only
    # bar data — no quote_tick/trade_tick data has been ingested — so genuine
    # streamed top-of-book validation is not currently possible. This function
    # instead applies a flat 1-tick slippage assumption on entry and exit as a
    # rough sensitivity check. Per project convention (feedback_real_fills_from_
    # top_of_book), a flat spread tax is NOT a substitute for real top-of-book
    # fills and this result should not be reported as MBP-1-validated.
    print(f"Running flat-tick slippage SENSITIVITY CHECK (not real MBP-1) for NQ {year} {policy}...")
    
    # Load policy episodes
    episodes_path = OUT_DIR / "track_b_policy_episodes.parquet"
    if not episodes_path.exists():
        print(f"Error: Policy episodes not found at {episodes_path}")
        return
        
    df = pd.read_parquet(episodes_path)
    
    # We select the episodes where a policy warning exit was executed (warn_i != -1)
    warn_exits = df[df["warn_i"] != -1].copy()
    if len(warn_exits) == 0:
        print("No warning exits to simulate MBP-1 slippage for.")
        return
        
    print(f"Simulating MBP-1 slippage for {len(warn_exits):,} warning-triggered trades.")
    
    # Simulating slippage details:
    # 1. NQ typical spread is 1 tick (0.25 points) or 2 ticks (0.50 points) during high volatility.
    # 2. We apply 1 tick of slippage (0.25 points) on entry, and 1 tick of slippage (0.25 points) on exit.
    # 3. We calculate the resulting slippage cost per trade:
    #    slippage_cost = 1 tick * $20/point = $5.0 per contract side.
    # 4. We evaluate whether the warning exit B1 remains economically viable after adding this slippage.
    
    slip_ticks = 1.0
    slip_pts = slip_ticks * TICK_SIZE
    slip_dollars_per_side = slip_pts * NQ_MULTIPLIER
    
    # Calculate slipped PnL for B1
    # B1 PnL was already net of commission ($5), but we add the slippage cost of 1 tick on entry and 1 tick on exit ($10 total)
    warn_exits["pnl_B1_slipped"] = warn_exits["pnl_B1"] - (2.0 * slip_dollars_per_side)
    
    mean_pnl_base = warn_exits["pnl_base"].mean()
    mean_pnl_B1 = warn_exits["pnl_B1"].mean()
    mean_pnl_B1_slipped = warn_exits["pnl_B1_slipped"].mean()
    
    lift_raw = mean_pnl_B1 - mean_pnl_base
    lift_slipped = mean_pnl_B1_slipped - mean_pnl_base
    
    print("\n--- MBP-1 Slippage Simulation ---")
    print(f"  Bid/Ask Spread assumed: 1.0 tick ({TICK_SIZE} points)")
    print(f"  Slippage cost per trade (2 sides): ${2.0 * slip_dollars_per_side:.2f}")
    print(f"  Mean PnL Base (held to flip):     ${mean_pnl_base:.2f}")
    print(f"  Mean PnL B1 (raw warning exit):   ${mean_pnl_B1:.2f} (EV lift = ${lift_raw:.2f})")
    print(f"  Mean PnL B1 (slipped warning):    ${mean_pnl_B1_slipped:.2f} (EV lift = ${lift_slipped:.2f})")
    
    status = "ECONOMICALLY_UNRESOLVED" if lift_slipped < 0.0 else "IMPROVES_EXIT_WITH_SLIP"
    print(f"\nSlippage Sensitivity Status: **{status}**")

    # Save results as markdown
    report_md = f"""# Slippage Sensitivity Report (NOT real MBP-1 validation)

* **This is NOT streamed MBP-1 (market-by-price level-1) quote/tick validation.**
  The catalog (`data/catalog/NQ_v0_2020_2026`) contains only bar data — no
  quote_tick/trade_tick data has been ingested for NQ, so real top-of-book
  execution validation is not currently possible. This report applies a flat
  1-tick-per-side slippage assumption to the offline B1 PnL as a rough
  sensitivity check only, and should not be cited as MBP-1-validated.
* **Sensitivity Status**: **{status}**
* **Assumed Bid/Ask Spread**: 1.0 tick ({TICK_SIZE} points)
* **Assumed Slippage Cost per Side**: ${slip_dollars_per_side:.2f} ($5.0 per contract)
* **Total warning-triggered trades simulated**: {len(warn_exits):,}

| Metric | Raw Exit Value | Slipped Exit Value | Slippage Impact |
|---|---|---|---|
| **Average Trade PnL (Base)** | ${mean_pnl_base:.2f} | ${mean_pnl_base:.2f} | $0.00 |
| **Average Trade PnL (B1)** | ${mean_pnl_B1:.2f} | ${mean_pnl_B1_slipped:.2f} | -${2.0 * slip_dollars_per_side:.2f} |
| **EV Lift over Base** | ${lift_raw:.2f} | ${lift_slipped:.2f} | -${2.0 * slip_dollars_per_side:.2f} |
"""
    with open(OUT_DIR / "slippage_sensitivity_report.md", "w") as f:
        f.write(report_md)

    print(f"Slippage sensitivity report written to {OUT_DIR / 'slippage_sensitivity_report.md'}")

if __name__ == "__main__":
    simulate_mbp1_slippage(2025, "B1")
