#!/bin/bash
# Runs the full B0-B5 x {2025,2026} W4 backtest matrix using the frozen
# theta/N from results/warning_policy_frozen_config.json (theta=0.4, N=1).
set -u
cd "C:/Users/Scott McCarty/Projects/Nautilus Trader"
PY="C:/Users/Scott McCarty/AppData/Local/Programs/Python/Python313/python.exe"
LOG_DIR="studies/regime_sequence_signal_audit/results/backtest_run_logs"
mkdir -p "$LOG_DIR"

for policy in B0 B1 B2 B3 B4 B5; do
  for year in 2025 2026; do
    echo "=== Running $policy $year ==="
    "$PY" backtests/run_w4_backtest.py --year "$year" --policy "$policy" --theta 0.4 --N 1 \
      > "$LOG_DIR/${policy}_${year}.log" 2>&1
    status=$?
    echo "=== $policy $year exit code: $status ==="
  done
done

echo "ALL_RUNS_COMPLETE"
