"""Phase 1, item 3-4: audit exact delayed-entry semantics for every
confirmed F2 signal in the primary window, and report pending-entry
cancellations (opposite flip before activation) as first-class, non-dropped,
non-zero-PnL records."""
import numpy as np
import pandas as pd
from common import OUT, load_atlas, repair_f2_window, PRIMARY_START, PRIMARY_END


def run():
    df_atlas = load_atlas()
    signals, terminal_viol = repair_f2_window(df_atlas, PRIMARY_START, PRIMARY_END)

    audit_cols = [
        "episode_id", "direction", "session", "month",
        "confirmation_ts", "decision_ts", "expected_fill_ts", "actual_fill_ts",
        "expected_fill_price", "actual_fill_price", "timestamp_match", "price_match",
        "fill_gap_seconds", "mismatch_class", "trade_status",
    ]
    delayed_entry_audit = signals[audit_cols].copy()
    delayed_entry_audit.to_parquet(OUT / "delayed_entry_audit.parquet", index=False)

    pending = signals[signals["trade_status"] == "pending_entry_canceled"].copy()
    pending_out = pending[[
        "episode_id", "direction", "session", "month",
        "confirmation_ts", "decision_ts", "expected_fill_ts", "ep_end_time", "opposing_flip_time",
    ]].copy()
    pending_out["status_chain"] = "signal confirmed -> entry scheduled -> opposite flip before activation -> pending entry canceled -> no trade"
    pending_out["pnl"] = np.nan  # explicitly NOT zero: no trade occurred, no PnL exists to report
    pending_out["gap_confirmation_to_opposite_flip_seconds"] = (pending["opposing_flip_time"] - pending["confirmation_ts"]) / 1e9
    pending_out.to_parquet(OUT / "pending_entry_cancellations.parquet", index=False)

    mismatch_summary = delayed_entry_audit["mismatch_class"].value_counts().rename_axis("mismatch_class").reset_index(name="count")
    mismatch_summary["fraction"] = mismatch_summary["count"] / len(delayed_entry_audit)
    gap_by_class = delayed_entry_audit.groupby("mismatch_class")["fill_gap_seconds"].agg(
        median_gap_s="median", p90_gap_s=lambda s: s.quantile(0.90), max_gap_s="max").reset_index()
    entry_mismatch_audit = mismatch_summary.merge(gap_by_class, on="mismatch_class", how="left")
    entry_mismatch_audit["n_pending_entry_canceled"] = int((delayed_entry_audit["trade_status"] == "pending_entry_canceled").sum())
    entry_mismatch_audit["n_decision_after_terminal_time_excluded_upstream"] = int(len(terminal_viol))
    entry_mismatch_audit.to_parquet(OUT / "entry_mismatch_audit.parquet", index=False)

    n_ts_mismatch = int((~delayed_entry_audit["timestamp_match"]).sum())
    n_px_mismatch = int((~delayed_entry_audit["price_match"]).sum())

    print(f"total confirmed signals: {len(signals)}")
    print(f"pending_entry_canceled: {len(pending)}")
    print(f"decision_after_terminal_time (invalid signals, excluded upstream): {len(terminal_viol)}")
    print(f"timestamp mismatches (no exact bar at expected_fill_ts): {n_ts_mismatch}")
    print(entry_mismatch_audit.to_string(index=False))
    return delayed_entry_audit, pending_out, entry_mismatch_audit, n_ts_mismatch


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()
