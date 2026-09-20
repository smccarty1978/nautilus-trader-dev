import sys
sys.path.insert(0, ".")
import os
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
OUTPUT_DIR = REPO_ROOT / "studies/index_pullback_portability_and_trend_mirror/branch_b_trend_mirror"

CELLS = ['E0_R0', 'E0_R1', 'E0_R2', 'E1_R0', 'E1_R1', 'E1_R2']

# Load nq_trend_matrix.json
with open(OUTPUT_DIR / "nq_trend_matrix.json", "r") as f:
    nq_trend_matrix = json.load(f)

# 1. Trend mirror contract
contract = {
    "study_id": "nq_h050_trend_following_mirror",
    "hypothesis": "Trading in the direction of the incumbent regime (Bull pullback -> LONG, Bear rally -> SHORT) at the 0.50 ATR pullback checkpoint provides superior risk-adjusted economics and substantially lower drawdown than counter-regime reversal.",
    "entry_architectures": {
        "E0": "Immediate continuation: decision at H050 checkpoint, enter at next 1s bar open with 1 tick adverse slippage.",
        "E1": "Re-acceleration: first completed 5s bar with close in direction of incumbent regime (Bull: close > open; Bear: close < open), enter at next 1s bar open with 1 tick adverse slippage. If regime terminates before re-acceleration, trade is skipped."
    },
    "bracket_policies": {
        "R0": {"stop_loss_atr": 0.75, "take_profit_atr": 0.75, "nominal_reward_risk": 1.00},
        "R1": {"stop_loss_atr": 0.75, "take_profit_atr": 1.00, "nominal_reward_risk": 1.3333},
        "R2": {"stop_loss_atr": 1.00, "take_profit_atr": 1.25, "nominal_reward_risk": 1.25}
    },
    "execution_resolution": "1-second completed bars (CME NQ 1s catalog/raw bars)",
    "tie_break_rule": "Conservative tie-break: if both SL and PT are touched in the same 1s bar, SL takes priority (SL wins)",
    "exit_timeout_policy": "REGIME_TERMINATION_EXIT: if neither PT nor SL is touched before incumbent regime flip, exit at next 1s bar open upon confirmed transition with 1 tick adverse slippage",
    "friction_model": {
        "instrument": "CME NQ",
        "point_value": 20.0,
        "tick_size": 0.25,
        "commission_round_trip_dollars": 5.0,
        "slippage_round_trip_ticks": 2,
        "total_round_trip_friction_points": 0.75,
        "total_round_trip_friction_dollars": 15.0
    }
}
with open(OUTPUT_DIR / "trend_mirror_contract.json", "w") as f:
    json.dump(contract, f, indent=2)
print("Saved trend_mirror_contract.json")

# 2. Entry Parity (E0 vs E1)
entry_parity = {}
for b in ['R0', 'R1', 'R2']:
    e0_cell = f"E0_{b}"
    e1_cell = f"E1_{b}"
    df_e0 = pd.read_parquet(OUTPUT_DIR / f"ledger_{e0_cell}.parquet")
    df_e1 = pd.read_parquet(OUTPUT_DIR / f"ledger_{e1_cell}.parquet")
    
    # 2024 comparison
    df_e0_24 = df_e0[df_e0['year'] == '2024']
    df_e1_24 = df_e1[df_e1['year'] == '2024']
    
    entry_parity[b] = {
        "E0_2024": {
            "candidates": len(df_e0_24),
            "executed": int((~df_e0_24['skipped']).sum()),
            "trades_per_day": nq_trend_matrix['2024'][e0_cell]['trades_per_day'],
            "win_rate": nq_trend_matrix['2024'][e0_cell]['win_rate'],
            "mean_pnl_atr": nq_trend_matrix['2024'][e0_cell]['mean_pnl_atr'],
            "profit_factor": nq_trend_matrix['2024'][e0_cell]['profit_factor'],
            "max_dd_atr": nq_trend_matrix['2024'][e0_cell]['max_dd_atr']
        },
        "E1_2024": {
            "candidates": len(df_e1_24),
            "executed": int((~df_e1_24['skipped']).sum()),
            "skip_rate_pct": nq_trend_matrix['2024'][e1_cell]['skip_rate_pct'],
            "trades_per_day": nq_trend_matrix['2024'][e1_cell]['trades_per_day'],
            "win_rate": nq_trend_matrix['2024'][e1_cell]['win_rate'],
            "mean_pnl_atr": nq_trend_matrix['2024'][e1_cell]['mean_pnl_atr'],
            "profit_factor": nq_trend_matrix['2024'][e1_cell]['profit_factor'],
            "max_dd_atr": nq_trend_matrix['2024'][e1_cell]['max_dd_atr']
        },
        "delta_E1_minus_E0": {
            "win_rate_delta": round(nq_trend_matrix['2024'][e1_cell]['win_rate'] - nq_trend_matrix['2024'][e0_cell]['win_rate'], 4),
            "mean_pnl_atr_delta": round(nq_trend_matrix['2024'][e1_cell]['mean_pnl_atr'] - nq_trend_matrix['2024'][e0_cell]['mean_pnl_atr'], 4),
            "profit_factor_delta": round(nq_trend_matrix['2024'][e1_cell]['profit_factor'] - nq_trend_matrix['2024'][e0_cell]['profit_factor'], 4),
            "max_dd_atr_delta": round(nq_trend_matrix['2024'][e1_cell]['max_dd_atr'] - nq_trend_matrix['2024'][e0_cell]['max_dd_atr'], 4)
        }
    }

with open(OUTPUT_DIR / "trend_entry_parity.json", "w") as f:
    json.dump(entry_parity, f, indent=2)
print("Saved trend_entry_parity.json")

# 3. Counter-regime comparison
counter_path = REPO_ROOT / 'studies/nq_h050_economic_subpopulation_mining/results/candidate_subpopulation_matrix.json'
with open(counter_path, "r") as f:
    cand_matrix = json.load(f)

counter_h050 = None
for c in cand_matrix:
    if c['candidate'] == 'Broad_H050_Baseline':
        counter_h050 = c
        break

counter_comp = {
    'counter_regime_broad_h050_2024': counter_h050,
    'trend_following_cells_2024': {cell: nq_trend_matrix['2024'][cell] for cell in CELLS}
}
with open(OUTPUT_DIR / "counter_vs_trend_comparison.json", "w") as f:
    json.dump(counter_comp, f, indent=2)
print("Saved counter_vs_trend_comparison.json")

# 4. Decision Gate Evaluation (B20)
passing_cells = []
for cell in CELLS:
    m23 = nq_trend_matrix['2023'][cell]
    m24 = nq_trend_matrix['2024'][cell]
    
    pos_23 = m23['mean_pnl_atr'] > 0
    pos_24 = m24['mean_pnl_atr'] > 0
    
    wr_wl_1 = (m24['win_rate'] >= 0.53) and (m24['realized_win_loss_ratio'] >= 1.2)
    wr_wl_2 = (m24['win_rate'] >= 0.55) and (m24['realized_win_loss_ratio'] >= 1.0)
    high_ev = (m24['mean_pnl_atr'] >= 0.15)
    
    qualifies = (pos_23 and pos_24) and (wr_wl_1 or wr_wl_2 or high_ev)
    if qualifies:
        passing_cells.append(cell)

gate_result = {
    'gate_name': 'TREND_MIRROR_CROSS_INSTRUMENT_GATE',
    'verdict': 'PASS' if len(passing_cells) > 0 else 'FAIL',
    'passing_cells': passing_cells,
    'cell_evaluations': {
        cell: {
            'pos_2023': nq_trend_matrix['2023'][cell]['mean_pnl_atr'] > 0,
            'mean_atr_2023': nq_trend_matrix['2023'][cell]['mean_pnl_atr'],
            'pos_2024': nq_trend_matrix['2024'][cell]['mean_pnl_atr'] > 0,
            'mean_atr_2024': nq_trend_matrix['2024'][cell]['mean_pnl_atr'],
            'win_rate_2024': nq_trend_matrix['2024'][cell]['win_rate'],
            'realized_wl_2024': nq_trend_matrix['2024'][cell]['realized_win_loss_ratio'],
            'max_dd_atr_2024': nq_trend_matrix['2024'][cell]['max_dd_atr'],
            'passed': cell in passing_cells
        }
        for cell in CELLS
    }
}

with open(OUTPUT_DIR / "trend_cross_instrument_gate.json", "w") as f:
    json.dump(gate_result, f, indent=2)
print("Saved trend_cross_instrument_gate.json")
print("\nBranch B Decision Gate Verdict:", gate_result['verdict'])
print("Cell Evaluations:")
for cell, ev in gate_result['cell_evaluations'].items():
    print(f"  {cell}: 2023={ev['mean_atr_2023']:.4f}A, 2024={ev['mean_atr_2024']:.4f}A, WR_2024={ev['win_rate_2024']*100:.1f}%, W/L={ev['realized_wl_2024']:.2f}, DD={ev['max_dd_atr_2024']:.1f}A -> Qualifies: {ev['passed']}")
