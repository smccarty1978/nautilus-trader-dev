import pandas as pd
import numpy as np

pos = pd.read_parquet(
    "studies/bracket_entry_v2/validation_2026/results/nt_run/positions.parquet")
trades = pd.read_parquet(
    "studies/bracket_entry_v2/validation_2026/results/nt_run/strategy_trades.parquet")

filled = trades[trades["entry_fill_price"].notna()].copy()
filled = filled.sort_values("decision_ts_ns").reset_index(drop=True)
pos = pos.copy()
pos["entry_ts_ns"] = pos["ts_opened"].astype("int64")
pos = pos.sort_values("entry_ts_ns").reset_index(drop=True)
n = min(len(pos), len(filled))
pos = pos.iloc[:n].copy()
pos["checkpoint_s"] = filled["checkpoint_s"].iloc[:n].values
pos["direction"] = filled["direction"].iloc[:n].values
pos["atr_at_signal"] = filled["atr_at_signal"].iloc[:n].values

pos["pnl_raw"] = ((pos["avg_px_close"] - pos["avg_px_open"])
                    * pos["direction"] * 20.0)

d = pos["direction"].values
atr = pos["atr_at_signal"].values
entry = pos["avg_px_open"].astype(float).values
exit_ = pos["avg_px_close"].astype(float).values
move_atr = (exit_ - entry) * d / np.maximum(atr, 0.01)
is_pt = move_atr >= 0.95
entry_slip = np.where(d == 1, 0.25, -0.25)
exit_slip = np.where(is_pt, 0.0,
                       np.where(d == 1, -0.25, 0.25))
pnl_1t = ((exit_ + exit_slip) - (entry + entry_slip)) * d * 20.0 - 5.0
pos["pnl_1tick"] = pnl_1t

in_scope = pos[pos["checkpoint_s"] <= 600]
out_scope = pos[pos["checkpoint_s"] > 600]


def dollars(v):
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def pf(s):
    s = s.dropna()
    w = s[s > 0].sum()
    l = abs(s[s < 0].sum())
    return w / l if l > 0 else float("inf")


print(f"FULL population: n={len(pos):,}  "
      f"raw_total={dollars(pos['pnl_raw'].sum())}  "
      f"1tick_total={dollars(pos['pnl_1tick'].sum())}  "
      f"1tick_PF={pf(pos['pnl_1tick']):.2f}  "
      f"win={100*(pos['pnl_1tick']>0).mean():.1f}%")
print()
print(f"IN-SCOPE T<=600: n={len(in_scope):,}  "
      f"raw_total={dollars(in_scope['pnl_raw'].sum())}  "
      f"1tick_total={dollars(in_scope['pnl_1tick'].sum())}  "
      f"1tick_PF={pf(in_scope['pnl_1tick']):.2f}  "
      f"win={100*(in_scope['pnl_1tick']>0).mean():.1f}%")
print(f"  mean/trade 1tick: {dollars(in_scope['pnl_1tick'].mean())}")
print()
print(f"OUT-OF-SCOPE T>600: n={len(out_scope):,}  "
      f"raw_total={dollars(out_scope['pnl_raw'].sum())}  "
      f"1tick_total={dollars(out_scope['pnl_1tick'].sum())}  "
      f"1tick_PF={pf(out_scope['pnl_1tick']):.2f}  "
      f"win={100*(out_scope['pnl_1tick']>0).mean():.1f}%")
print(f"  mean/trade 1tick: {dollars(out_scope['pnl_1tick'].mean())}")
print()
delta_1tick = pos["pnl_1tick"].sum() - in_scope["pnl_1tick"].sum()
print(f"Impact of removing T>600 trades: {dollars(delta_1tick)} "
      f"(1-tick slippage)")
