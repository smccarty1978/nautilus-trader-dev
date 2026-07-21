"""Smoke test both new strategies over a short window before committing
to a full multi-year run. Checks: no crash, provenance (checkpoint_ts
>= entry_ts always), trade/checkpoint counts are sane, diag counters
make sense (F2 should have far fewer entries than ALL_FLIPS given the
confirmation filter).
"""
from __future__ import annotations
import sys, json
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.nt_runner import run_period
from studies.all_flips_exit_management.strategy import (
    AllFlipsStrategy, AllFlipsConfig,
)
from studies.f2_confirmed_exit_management.strategy import (
    F2ConfirmedStrategy, F2ConfirmedConfig,
)

LOAD_START = pd.Timestamp("2024-01-03", tz="UTC")
LOAD_END = pd.Timestamp("2024-01-19 23:59:59", tz="UTC")


def check_provenance(df_trades: pd.DataFrame, df_cp: pd.DataFrame,
                         label: str) -> bool:
    ok = True
    if len(df_trades):
        bad_exit = df_trades[df_trades["exit_ts"] < df_trades["entry_ts"]]
        if len(bad_exit):
            print(f"  [{label}] FAIL: {len(bad_exit)} trades with "
                     f"exit_ts < entry_ts")
            ok = False
        bad_regime = df_trades[
            df_trades["entry_ts"] < df_trades["regime_start_ts"]]
        # entry_ts is a real ns timestamp (event time), regime_start_ts
        # is a bar close_ts -- entry must be >= regime_start (can be ==
        # for all_flips, since entry is same instant as flip close, but
        # entry fills 1s later at the earliest, so strictly >)
        if len(bad_regime):
            print(f"  [{label}] FAIL: {len(bad_regime)} trades with "
                     f"entry_ts < regime_start_ts")
            ok = False
    if len(df_cp):
        bad_cp = df_cp[df_cp["checkpoint_ts"] < df_cp["entry_ts"]]
        if len(bad_cp):
            print(f"  [{label}] FAIL: {len(bad_cp)} checkpoints with "
                     f"checkpoint_ts < entry_ts")
            ok = False
    if ok:
        print(f"  [{label}] provenance OK "
                 f"({len(df_trades)} trades, {len(df_cp)} checkpoints)")
    return ok


def main():
    out_root = Path("studies/_shared_exit_mgmt/_smoke_results")
    out_root.mkdir(parents=True, exist_ok=True)
    overall_ok = True

    print("=== ALL_FLIPS smoke ===", flush=True)
    out_a = out_root / "all_flips"
    res_a = run_period(AllFlipsStrategy, AllFlipsConfig, {},
                           LOAD_START, LOAD_END, out_a)
    print(f"  bars: {res_a['n_bars_1s']:,} 1s / {res_a['n_bars_1m']:,} 1m, "
             f"load={res_a['load_elapsed_s']:.0f}s run={res_a['run_elapsed_s']:.0f}s")
    print(f"  diag: {res_a['diag']}")
    trades_a = (pd.read_parquet(out_a / "trades.parquet")
                   if (out_a / "trades.parquet").exists() else pd.DataFrame())
    cp_a = (pd.read_parquet(out_a / "checkpoints.parquet")
               if (out_a / "checkpoints.parquet").exists() else pd.DataFrame())
    overall_ok &= check_provenance(trades_a, cp_a, "ALL_FLIPS")

    print("\n=== F2_CONFIRMED smoke ===", flush=True)
    out_f = out_root / "f2_confirmed"
    res_f = run_period(F2ConfirmedStrategy, F2ConfirmedConfig, {},
                           LOAD_START, LOAD_END, out_f)
    print(f"  bars: {res_f['n_bars_1s']:,} 1s / {res_f['n_bars_1m']:,} 1m, "
             f"load={res_f['load_elapsed_s']:.0f}s run={res_f['run_elapsed_s']:.0f}s")
    print(f"  diag: {res_f['diag']}")
    trades_f = (pd.read_parquet(out_f / "trades.parquet")
                   if (out_f / "trades.parquet").exists() else pd.DataFrame())
    cp_f = (pd.read_parquet(out_f / "checkpoints.parquet")
               if (out_f / "checkpoints.parquet").exists() else pd.DataFrame())
    overall_ok &= check_provenance(trades_f, cp_f, "F2_CONFIRMED")

    print("\n=== Cross-population sanity ===")
    n_flips_a = res_a["diag"].get("rth_flips", 0)
    n_flips_f = res_f["diag"].get("rth_flips", 0)
    n_trades_a = len(trades_a)
    n_trades_f = len(trades_f)
    print(f"  RTH flips seen -- ALL_FLIPS: {n_flips_a}, F2: {n_flips_f} "
             f"(should be equal: same regime engine, same data)")
    print(f"  Trades filled  -- ALL_FLIPS: {n_trades_a}, F2: {n_trades_f} "
             f"(F2 should be << ALL_FLIPS given confirmation filter)")
    if n_flips_a != n_flips_f:
        print("  WARNING: rth_flips differ between populations -- "
                 "unexpected since both share the same regime detection")
    if not (n_trades_f < n_trades_a):
        print("  WARNING: expected F2 trade count < ALL_FLIPS trade count")

    print(f"\n{'SMOKE PASSED' if overall_ok else 'SMOKE FAILED'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
