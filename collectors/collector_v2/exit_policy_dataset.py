"""Build exit-policy decision-row dataset from Collector V2
path_checkpoint snapshots.

Input (per year, per product):
  collectors/collector_v2/results/<dir>/
    snapshots.parquet  (kinds: regime_flip, bar1_check, path_checkpoint)
    trades.parquet

For each path_checkpoint snapshot tied to a trade via
`trade_event_id == trades.decision_event_id`:

  Features (causal — already audited at write time):
    - cur_pnl_atr / cur_mfe_atr / cur_mae_atr / cur_giveback_atr
    - elapsed_s, time_since_max_mfe_s
    - regime_30s / 1m / 3m / 5m + alignment to trade direction
    - bars_in_regime_3m / 5m
    - atr_1m / atr_3m / atr_5m
    - session (RTH/ETH)
    - close_<tf> distance features (already in snapshot)

  Labels (computed from FUTURE path within the same trade):
    1. future_mfe_remaining_atr
    2. future_mae_remaining_atr
    3. exit_now_better_than_hold (1 if exit at cur_close beats
        hold-to-actual-exit by >= 0.10 ATR)
    4. future_giveback_risk (1 if trade gives back >= 0.5 ATR
        before next +0.5 ATR favorable move)
    5. remaining_ev_atr (final actual PnL minus current PnL,
        in ATR; what's left)

Output:
  collectors/collector_v2/results/exit_policy/<source_dir_tag>_<year>.parquet
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("collectors/collector_v2/results/exit_policy")
OUT.mkdir(parents=True, exist_ok=True)


def build_dataset(source_dir: Path, tag: str) -> pd.DataFrame:
    """Build labeled decision-row dataset for one (product, year)."""
    snaps = pd.read_parquet(source_dir / "snapshots.parquet")
    trades = pd.read_parquet(source_dir / "trades.parquet")
    if not len(snaps) or not len(trades):
        return pd.DataFrame()

    cps = snaps[snaps["kind"] == "path_checkpoint"].copy()
    if not len(cps):
        return pd.DataFrame()
    print(f"  {tag}: {len(cps):,} path_checkpoints, "
           f"{len(trades):,} trades")

    # Join checkpoints to their trade via trade_event_id
    # (= trades.decision_event_id)
    t = trades.rename(columns={
        "decision_event_id": "trade_event_id",
        "fill_price": "trade_fill_price_actual",
        "exit_price": "trade_exit_price",
        "exit_ts": "trade_exit_ts",
        "net_pnl": "trade_net_pnl",
        "hold_s": "trade_hold_s",
    })
    cps = cps.merge(
        t[["trade_event_id", "trade_exit_price", "trade_exit_ts",
            "trade_net_pnl", "trade_hold_s"]],
        on="trade_event_id", how="left")
    if cps["trade_exit_price"].isna().any():
        n_miss = int(cps["trade_exit_price"].isna().sum())
        print(f"  warning: {n_miss} cps could not be matched to a "
               "trade — dropping them")
        cps = cps[~cps["trade_exit_price"].isna()].copy()

    # Build per-trade group for label calculation: for each (trade,
    # checkpoint), labels look at the future path WITHIN that trade.
    cps = cps.sort_values(
        ["trade_event_id", "decision_ts"]).reset_index(drop=True)

    # Group future-path stats per trade
    out_rows = []
    for tid, g in cps.groupby("trade_event_id"):
        g = g.reset_index(drop=True)
        atr = g["trade_atr_at_signal"].iloc[0]
        if pd.isna(atr) or atr <= 0:
            continue
        d = int(g["trade_direction"].iloc[0])
        fp = float(g["trade_fill_price"].iloc[0])
        exit_price = float(g["trade_exit_price"].iloc[0])
        # Final actual PnL in ATR units (before any cost)
        final_pnl_atr = (exit_price - fp) * d / atr
        # Per-checkpoint future calc
        cur_mfe = g["cur_mfe_atr"].values
        cur_mae = g["cur_mae_atr"].values
        cur_pnl = g["cur_pnl_atr"].values
        for i, row in g.iterrows():
            # Future MFE/MAE from THIS checkpoint forward
            # cur_mfe is the running PEAK MFE up to checkpoint i;
            # the future MFE peak across remaining checkpoints (i+1..end)
            # is max(cur_mfe[i+1..end]). The future ADDITIONAL
            # favorable excursion vs current is max(cur_mfe[i+1..end])
            # - cur_mfe[i] if any further checkpoints; else 0.
            tail_mfe = (cur_mfe[i + 1:].max() if i + 1 < len(cur_mfe)
                          else cur_mfe[i])
            tail_mae = (cur_mae[i + 1:].max() if i + 1 < len(cur_mae)
                          else cur_mae[i])
            future_mfe_rem = float(max(0.0, tail_mfe - cur_mfe[i]))
            future_mae_rem = float(max(0.0, tail_mae - cur_mae[i]))
            remaining_ev = float(final_pnl_atr - cur_pnl[i])

            # exit_now_better: exiting at current price beats
            # final exit by >= 0.10 ATR
            exit_now_better = int(
                (cur_pnl[i] - final_pnl_atr) >= 0.10)

            # future_giveback_risk:
            # 1 if from here trade gives back >= 0.5 ATR (i.e. cur PnL
            # drops 0.5 ATR from current PEAK MFE) BEFORE making
            # another favorable +0.5 ATR move.
            # Using checkpoint resolution (30s) as the future scan.
            give_threshold = 0.5
            new_fav_threshold = 0.5
            future_giveback_risk = 0
            for j in range(i + 1, len(g)):
                # New favorable extreme since checkpoint i?
                if cur_mfe[j] >= cur_mfe[i] + new_fav_threshold:
                    break
                # Adverse: cur_pnl drops more than give_threshold
                # below cur_mfe[i] (i.e. gave back >=0.5 ATR from
                # peak MFE)
                if (cur_mfe[i] - cur_pnl[j]) >= give_threshold:
                    future_giveback_risk = 1
                    break

            row_d = row.to_dict()
            row_d.update({
                "future_mfe_remaining_atr": future_mfe_rem,
                "future_mae_remaining_atr": future_mae_rem,
                "exit_now_better_than_hold": exit_now_better,
                "future_giveback_risk": future_giveback_risk,
                "remaining_ev_atr": remaining_ev,
                "final_pnl_atr": float(final_pnl_atr),
                "trade_net_pnl": float(g["trade_net_pnl"].iloc[0]),
                "tag": tag,
            })
            out_rows.append(row_d)
    df = pd.DataFrame(out_rows)
    print(f"  {tag}: {len(df):,} labeled decision rows")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source", required=True,
        help="Path under collectors/collector_v2/results/ "
             "containing snapshots.parquet + trades.parquet")
    ap.add_argument("--tag", required=True,
                     help="Label written into 'tag' column "
                          "(e.g. NQ_2024)")
    args = ap.parse_args()
    src = Path("collectors/collector_v2/results") / args.source
    if not src.exists():
        print(f"Source dir not found: {src}")
        sys.exit(1)
    df = build_dataset(src, args.tag)
    if not len(df):
        print("Empty dataset — nothing to write")
        sys.exit(0)
    out_path = OUT / f"{args.tag}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df):,} rows to {out_path}")


if __name__ == "__main__":
    main()
