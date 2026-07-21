"""runner_retention.parquet and tail_dependence.parquet.

Runner retention: among R0's biggest-winning trades (top 10%/5%/1% of R0's
own net_pnl distribution, within each evaluation block), what fraction does
each policy's skip filter actually retain (i.e. NOT skip)?

Tail dependence: for each policy's EV lift vs R0 (per block), how much of the
lift is attributable to the single/top-2 largest AVOIDED losses (episodes R0
would have taken, that the policy skipped, with the most negative R0
net_pnl)? Recomputes the lift with those 1-2 biggest avoided losses removed
from both sides of the comparison.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c
from compute_metrics import POOLED_BLOCKS, month_in_block

WORK_DIR = c.OUT.parent / "_work"
TIERS = {"top10pct": 0.10, "top5pct": 0.05, "top1pct": 0.01}


def build_pairs(status: pd.DataFrame, policy: str, block: tuple[str, str]) -> pd.DataFrame:
    """Per-episode paired frame: R0's net_pnl (NaN if R0 itself didn't fill)
    and this policy's net_pnl (0 if skipped, NaN if canceled/unfilled for a
    reason other than the policy's own skip), for episodes in `block`."""
    r0 = status[(status["policy"] == "r0") & (status["deploy_month"].apply(lambda m: month_in_block(m, block)))]
    pol = status[(status["policy"] == policy) & (status["deploy_month"].apply(lambda m: month_in_block(m, block)))]

    r0i = r0.set_index("confirmation_ts")
    poli = pol.set_index("confirmation_ts")

    df = pd.DataFrame({
        "r0_net_pnl": r0i["net_pnl"],
        "r0_filled": r0i["filled"],
        "pol_net_pnl": poli["net_pnl"],
        "pol_skipped": poli["skipped"],
        "pol_filled": poli["filled"],
    })
    # policy PnL contribution for lift purposes: its own net_pnl if filled, 0 if skipped
    # (a skip that would have been a cancellation/miss under R0 too contributes 0 either side)
    df["pol_pnl_contrib"] = np.where(df["pol_filled"], df["pol_net_pnl"], 0.0)
    df["r0_pnl_contrib"] = np.where(df["r0_filled"], df["r0_net_pnl"], 0.0)
    return df


def main():
    status = pd.read_parquet(WORK_DIR / "episode_status.parquet")
    policies = [p for p in status["policy"].unique() if p != "r0"]

    # ---- runner retention ----
    retention_rows = []
    for block_name, block in POOLED_BLOCKS.items():
        r0 = status[(status["policy"] == "r0") & (status["deploy_month"].apply(lambda m: month_in_block(m, block))) & (status["filled"])]
        if len(r0) == 0:
            continue
        for tier_name, frac in TIERS.items():
            n_tier = max(1, int(round(len(r0) * frac)))
            top = r0.nlargest(n_tier, "net_pnl")
            top_ts = set(top["confirmation_ts"])
            for policy in policies:
                pol = status[(status["policy"] == policy) & (status["confirmation_ts"].isin(top_ts))]
                retained = int((~pol["skipped"]).sum())
                skipped_rows = pol[pol["skipped"]]
                largest_skipped_winner = float(top.set_index("confirmation_ts").loc[skipped_rows["confirmation_ts"], "net_pnl"].max()) if len(skipped_rows) else 0.0
                retention_rows.append({
                    "block": block_name, "policy": policy, "tier": tier_name,
                    "n_runner_trades": n_tier, "n_retained": retained,
                    "retention_rate": retained / n_tier if n_tier else np.nan,
                    "largest_skipped_winner_in_tier": largest_skipped_winner,
                })
    runner_retention = pd.DataFrame(retention_rows)
    runner_retention.to_parquet(c.OUT / "runner_retention.parquet", index=False)

    # ---- tail dependence ----
    tail_rows = []
    for block_name, block in POOLED_BLOCKS.items():
        for policy in policies:
            df = build_pairs(status, policy, block)
            if len(df) == 0:
                continue
            full_lift = df["pol_pnl_contrib"].mean() - df["r0_pnl_contrib"].mean()

            # avoided losses: episodes the policy skipped where R0's own fill was a loss
            avoided = df[(df["pol_skipped"]) & (df["r0_filled"]) & (df["r0_net_pnl"] < 0)].sort_values("r0_net_pnl")
            largest_avoided_loss = float(avoided["r0_net_pnl"].iloc[0]) if len(avoided) else 0.0
            top2_ts = avoided.index[:2]

            df_ex1 = df.drop(index=avoided.index[:1]) if len(avoided) >= 1 else df
            df_ex2 = df.drop(index=avoided.index[:2]) if len(avoided) >= 2 else df
            lift_ex1 = df_ex1["pol_pnl_contrib"].mean() - df_ex1["r0_pnl_contrib"].mean() if len(df_ex1) else np.nan
            lift_ex2 = df_ex2["pol_pnl_contrib"].mean() - df_ex2["r0_pnl_contrib"].mean() if len(df_ex2) else np.nan

            largest_skipped_winner = 0.0
            skipped_wins = df[(df["pol_skipped"]) & (df["r0_filled"]) & (df["r0_net_pnl"] > 0)]
            if len(skipped_wins):
                largest_skipped_winner = float(skipped_wins["r0_net_pnl"].max())

            tail_rows.append({
                "block": block_name, "policy": policy,
                "full_ev_lift_per_episode": full_lift,
                "ev_lift_ex_top1_avoided_loss": lift_ex1,
                "ev_lift_ex_top2_avoided_losses": lift_ex2,
                "largest_avoided_loss": largest_avoided_loss,
                "largest_skipped_winner": largest_skipped_winner,
                "n_avoided_losses": len(avoided),
                "driven_by_top2_pct": float(100 * (1 - lift_ex2 / full_lift)) if full_lift not in (0, np.nan) and not np.isnan(lift_ex2) else np.nan,
            })
    tail_dependence = pd.DataFrame(tail_rows)
    tail_dependence.to_parquet(c.OUT / "tail_dependence.parquet", index=False)

    print("runner_retention:", runner_retention.shape)
    print("tail_dependence:", tail_dependence.shape)
    print("\nFinal-reserved tail dependence:")
    print(tail_dependence[tail_dependence["block"] == "2026_MarApr_final_reserved"].to_string(index=False))


if __name__ == "__main__":
    main()
