"""For trades that were WINNERS under BASELINE_regime (i.e., would
have been winning trades without any protection rule), how do they
exit under each protection variant?

This shows what the cat stop + MA layer does to the trades the
baseline already had right.
"""
import sys, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

R_2425 = Path("studies/v_a_exit_recon/results/stall_ma_protection_2024_2025")
R_2026 = Path("studies/v_a_exit_recon/results/stall_ma_protection_2026")


def analyze(span_label, root, variants):
    base = pd.read_parquet(root / "trades_BASELINE_regime.parquet")
    base_winners = base[base["net_pnl"] > 0]
    # Match on entry_ts (unique per trade, no year-collision)
    base_winner_ids = set(base_winners["entry_ts"])
    base_winner_pnl = (base_winners.drop_duplicates("entry_ts")
                          .set_index("entry_ts")["net_pnl"])
    n_base_winners = len(base_winners)
    print("=" * 95)
    print(f"{span_label}: {n_base_winners} trades were WINNERS "
          f"under BASELINE_regime "
          f"(total ${base_winners['net_pnl'].sum():,.0f})")
    print("=" * 95)
    print(f"{'Variant':<22} {'cat%':>6} {'MA%':>6} {'reg%':>6} | "
          f"{'kept':>5} {'flipped':>7} {'clipped':>7} | "
          f"{'$base':>10} {'$variant':>10} {'$ delta':>10}")
    print("-" * 95)

    for v in variants:
        p = root / f"trades_{v}.parquet"
        if not p.exists(): continue
        df = pd.read_parquet(p)
        # Filter to trades that were baseline winners
        sub = df[df["entry_ts"].isin(base_winner_ids)].copy()
        n = len(sub)
        if n == 0: continue
        rc = sub["exit_reason"].value_counts()
        cat = rc.get("catastrophic", 0)
        ma = rc.get("ma_protect", 0) + rc.get(
            "ma_invalid_market_exit", 0)
        reg = (rc.get("regime", 0)
                 + rc.get("regime_no_tape", 0))

        # Did the rule keep them as winners (kept), turn winner
        # into loser (flipped), or just clip (smaller positive)?
        sub["base_pnl"] = sub["entry_ts"].map(base_winner_pnl)
        n_kept = int((sub["net_pnl"] > 0).sum())
        n_flipped = int((sub["net_pnl"] <= 0).sum())
        # clipped: still winner but smaller than baseline
        clipped_mask = (sub["net_pnl"] > 0) & (
            sub["net_pnl"] < sub["base_pnl"])
        n_clipped = int(clipped_mask.sum())
        # delta on this subset
        base_total = float(sub["base_pnl"].sum())
        variant_total = float(sub["net_pnl"].sum())
        delta = variant_total - base_total

        print(f"{v:<22} {100*cat/n:>5.1f}% {100*ma/n:>5.1f}% "
              f"{100*reg/n:>5.1f}% | {n_kept:>5} {n_flipped:>7} "
              f"{n_clipped:>7} | ${base_total:>9,.0f} "
              f"${variant_total:>9,.0f} ${delta:>9,.0f}")
    print()
    print("Legend: kept = still profitable in variant; "
          "flipped = baseline winner → variant loser; "
          "clipped = still positive but smaller than baseline.")
    print()


variants_2425 = ["BASELINE_cat_only",
                    "S2_SMA9", "S2_SMA21",
                    "S3_SMA21", "S4_EMA21",
                    "S5_SMA21", "S5_EMA21"]
analyze("2024 + 2025 RTH", R_2425, variants_2425)

variants_2026 = ["BASELINE_cat_only", "S5_SMA21"]
analyze("2026 RTH", R_2026, variants_2026)
