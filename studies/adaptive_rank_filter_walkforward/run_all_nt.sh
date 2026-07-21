#!/bin/bash
set -u
cd "C:/Users/Scott McCarty/Projects/Nautilus Trader"
PY="C:/Users/Scott McCarty/AppData/Local/Programs/Python/Python313/python.exe"
LOG_DIR="studies/adaptive_rank_filter_walkforward/nt_run_logs"
mkdir -p "$LOG_DIR"

POLICIES="r0 static_r2 static_r4 a1_3m a2_3m a4_3m a1_6m a2_6m a4_6m a1_12m a2_12m a4_12m"

for period in 2025 2026; do
  for policy in $POLICIES; do
    echo "=== Running $policy $period ==="
    "$PY" -c "
import sys
sys.path.insert(0, 'studies/adaptive_rank_filter_walkforward')
import awf_common as c
import run_nt_adaptive as r
f2 = c.load_f2_atlas()
r.run_backtest(f2, '$policy', '$period')
" > "$LOG_DIR/${policy}_${period}.log" 2>&1
    status=$?
    echo "=== $policy $period exit code: $status ==="
  done
done

echo "ALL_NT_RUNS_COMPLETE"
