"""Quick analysis: % of losers (and winners) by exit reason."""
import sys, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

R_2425 = Path("studies/v_a_exit_recon/results/stall_ma_protection_2024_2025")
R_2026 = Path("studies/v_a_exit_recon/results/stall_ma_protection_2026")


def stat_block(label, df):
    L = df[df["net_pnl"] < 0]
    W = df[df["net_pnl"] > 0]
    def row(sub, name):
        n = len(sub)
        if n == 0:
            return
        rc = sub["exit_reason"].value_counts()
        cat = rc.get("catastrophic", 0)
        ma_p = rc.get("ma_protect", 0)
        ma_i = rc.get("ma_invalid_market_exit", 0)
        ma_total = ma_p + ma_i
        reg = (rc.get("regime", 0)
                 + rc.get("regime_no_tape", 0))

        def avg(*keys):
            sub2 = sub[sub["exit_reason"].isin(keys)]["net_pnl"]
            return sub2.mean() if len(sub2) else float("nan")

        cat_avg = avg("catastrophic")
        ma_avg = avg("ma_protect", "ma_invalid_market_exit")
        reg_avg = avg("regime", "regime_no_tape")
        print(f"  {name:<8} n={n:>5} | "
              f"cat {cat:>4}={100*cat/n:>4.1f}% (avg ${cat_avg:>6.0f}) | "
              f"MA {ma_total:>4}={100*ma_total/n:>4.1f}% "
              f"(avg ${ma_avg:>6.0f}) | "
              f"reg {reg:>4}={100*reg/n:>4.1f}% "
              f"(avg ${reg_avg:>6.0f})")

    print(f"--- {label} ---")
    row(L, "LOSERS")
    row(W, "WINNERS")
    print()


print("=" * 88)
print("2024 + 2025 RTH (n=6,653) — % of losers/winners by exit reason")
print("=" * 88)
for v in ["BASELINE_regime", "BASELINE_cat_only",
            "S2_SMA9", "S2_SMA21",
            "S3_SMA21", "S4_EMA21",
            "S5_SMA21", "S5_EMA21"]:
    p = R_2425 / f"trades_{v}.parquet"
    if not p.exists(): continue
    df = pd.read_parquet(p)
    stat_block(v, df)

print()
print("=" * 88)
print("2026 RTH (n=1,006) — % of losers/winners by exit reason")
print("=" * 88)
for v in ["BASELINE_regime", "BASELINE_cat_only", "S5_SMA21"]:
    p = R_2026 / f"trades_{v}.parquet"
    if not p.exists(): continue
    df = pd.read_parquet(p)
    stat_block(v, df)
