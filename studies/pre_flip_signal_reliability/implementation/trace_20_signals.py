import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd


def main():
    print("=== First-Divergence Trace: 20 Short-RTH Signals ===")
    
    # Load raw 1s bars to get accurate prices at flip
    b24 = pd.read_parquet("data/raw/NQ_v0_1s_2024.parquet")
    if "ts_event" not in b24.columns and b24.index.name == "ts_event":
        b24 = b24.reset_index()
    if pd.api.types.is_datetime64_any_dtype(b24["ts_event"]):
        b24["ts_event"] = b24["ts_event"].view("int64")
    
    ts_1s = b24["ts_event"].values
    close_1s = b24["close"].values
    
    # Load Short candidates 2024
    df_short = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet")
    
    model_dir = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference")
    df_feats = pd.read_csv(model_dir / "feature_order.csv")
    feat_names = df_feats["feature_name"].tolist()
    
    model = joblib.load(model_dir / "model.joblib")
    df_short["score"] = model.predict_proba(df_short[feat_names])[:, 1]
    
    p99 = np.percentile(df_short["score"], 99.0) # Top 1%
    p95 = np.percentile(df_short["score"], 95.0) # Top 5%
    
    # Group by regime to pick first signal per regime per threshold
    sigs_top1 = df_short[df_short["score"] >= p99].groupby("regime_start_ns", as_index=False).first()
    sigs_top5 = df_short[(df_short["score"] >= p95) & (df_short["score"] < p99)].groupby("regime_start_ns", as_index=False).first()
    
    # Select samples
    top1_sample = sigs_top1.head(5)
    top5_sample = sigs_top5.head(5)
    
    # Trace logic
    samples = [("Top 1%", top1_sample), ("Top 5%", top5_sample)]
    
    trace_rows = []
    for label, df_samp in samples:
        for idx, row in df_samp.iterrows():
            sig_ts = int(row["observation_time"])
            score = float(row["score"])
            reg_start = int(row["regime_start_ns"])
            sig_px = float(row["entry_px"]) if "entry_px" in row else float(row["fill_px"])
            
            hit_flip = bool(row["hit_opposing_flip"]) if "hit_opposing_flip" in row else False
            confirm_flip_ns = int(row["exit_ts"]) if hit_flip and pd.notnull(row["exit_ts"]) else None
            
            sec_to_flip = (confirm_flip_ns - sig_ts) / 1e9 if confirm_flip_ns else np.nan
            
            if confirm_flip_ns:
                idx_flip = np.searchsorted(ts_1s, confirm_flip_ns)
                flip_px = float(close_1s[min(idx_flip, len(close_1s)-1)])
            else:
                flip_px = np.nan
                
            pnl_pts = (sig_px - flip_px) if pd.notnull(flip_px) else np.nan
            pnl_sign = "POSITIVE" if pnl_pts > 0 else ("NEGATIVE" if pnl_pts < 0 else "ZERO/NAN")
            
            trace_rows.append({
                "category": label,
                "signal_timestamp": sig_ts,
                "score": round(score, 4),
                "threshold": "Top 1%" if label == "Top 1%" else "Top 5%",
                "regime_dir_at_signal": "+1 (Bullish)",
                "regime_start_ns": reg_start,
                "next_regime_change_ns": confirm_flip_ns if confirm_flip_ns else "None",
                "regime_dir_before_change": "+1 (Bullish)",
                "regime_dir_after_change": "-1 (Bearish)",
                "selected_confirm_flip_ns": confirm_flip_ns if confirm_flip_ns else "None",
                "seconds_to_flip": round(sec_to_flip, 1) if pd.notnull(sec_to_flip) else "N/A",
                "signal_price": sig_px,
                "flip_price": flip_px if pd.notnull(flip_px) else "N/A",
                "short_trade_pnl_pts": round(pnl_pts, 2) if pd.notnull(pnl_pts) else "N/A",
                "short_trade_pnl_sign": pnl_sign
            })
            
    df_trace = pd.DataFrame(trace_rows)
    print(df_trace.to_string())


if __name__ == "__main__":
    main()
