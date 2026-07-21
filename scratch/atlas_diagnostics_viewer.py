import pandas as pd
import numpy as np
import os
from pathlib import Path

PROJECT_ROOT = Path(r"c:\Users\Scott McCarty\Projects\Nautilus Trader")
OUT_DIR = PROJECT_ROOT / "studies/regime_state_transition_atlas/results/diagnostics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def generate_markdown_report(title, filename, df_selected, df_all):
    lines = [f"# {title}\n"]
    
    for i, row in df_selected.iterrows():
        regime_id = row['regime_id']
        regime_bars = df_all[df_all['regime_id'] == regime_id].sort_values('bar_index_in_regime')
        
        lines.append(f"## Regime {regime_id}")
        lines.append(f"**Peak Score:** {row['peak_score']:.3f} | **PnL at Peak:** ${row['pnl_at_peak']:.2f}")
        
        lines.append("| Bar | Score | Pred MFE | Pred MAE | Actual Rem MFE | Actual Rem MAE | Fwd PnL | Next 1s Open |")
        lines.append("|---|---|---|---|---|---|---|---|")
        
        for _, bar in regime_bars.iterrows():
            score = bar.get('score_opportunity', 0)
            pred_mfe = bar.get('pred_rem_mfe', 0)
            pred_mae = bar.get('pred_rem_mae', 0)
            act_mfe = bar.get('future_mfe_from_here_atr', 0)
            act_mae = bar.get('future_mae_from_here_atr', 0)
            fwd_pnl = bar.get('actual_forward_pnl', 0)
            open_px = bar.get('next_1s_open', 0)
            
            lines.append(f"| {bar['bar_index_in_regime']} | {score:.3f} | {pred_mfe:.2f} ATR | {pred_mae:.2f} ATR | {act_mfe:.2f} ATR | {act_mae:.2f} ATR | ${fwd_pnl:.2f} | {open_px:.2f} |")
        
        lines.append("\n")
    
    with open(OUT_DIR / filename, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"Wrote {filename}")

def main():
    print("Loading scored_state_rows.parquet...")
    df = pd.read_parquet(PROJECT_ROOT / "studies/regime_state_transition_atlas/results/scored_state_rows.parquet")
    
    # We want OOS only for diagnostics
    df = df[df['is_oos'] == 1].copy()
    
    if 'score_opportunity' not in df.columns:
        print("Missing score_opportunity, using pred_rem_mfe - pred_rem_mae")
        df['score_opportunity'] = df['pred_rem_mfe'] - df['pred_rem_mae']
    
    print("Aggregating per regime...")
    
    # Find the peak score and the corresponding PnL for each regime
    regime_stats = []
    
    for regime_id, group in df.groupby('regime_id'):
        peak_idx = group['score_opportunity'].idxmax()
        peak_row = group.loc[peak_idx]
        
        regime_stats.append({
            'regime_id': regime_id,
            'peak_score': peak_row['score_opportunity'],
            'pnl_at_peak': peak_row['actual_forward_pnl']
        })
        
    df_regimes = pd.DataFrame(regime_stats)
    
    print("Selecting categories...")
    # Best 50: High score, High PnL
    best_50 = df_regimes[(df_regimes['peak_score'] > 0.5) & (df_regimes['pnl_at_peak'] > 100)].nlargest(50, 'peak_score')
    
    # Worst 50: Lowest score, Lowest PnL (Wait, low score means we wouldn't enter. Maybe 'Worst' is just lowest scores overall)
    worst_50 = df_regimes[(df_regimes['peak_score'] < -0.5) & (df_regimes['pnl_at_peak'] < -50)].nsmallest(50, 'peak_score')
    
    # False Positives: High Score, Losing Trade
    false_positives = df_regimes[(df_regimes['peak_score'] > 0.5) & (df_regimes['pnl_at_peak'] < -50)].nlargest(50, 'peak_score')
    
    # False Negatives: Low Score, Winning Trade
    false_negatives = df_regimes[(df_regimes['peak_score'] < 0) & (df_regimes['pnl_at_peak'] > 150)].nsmallest(50, 'peak_score')
    
    print("Generating reports...")
    generate_markdown_report("Top 50 Best Regimes", "best_50.md", best_50, df)
    generate_markdown_report("Top 50 Worst Regimes", "worst_50.md", worst_50, df)
    generate_markdown_report("Top 50 False Positives", "false_positives.md", false_positives, df)
    generate_markdown_report("Top 50 False Negatives", "false_negatives.md", false_negatives, df)
    
    print("Done.")

if __name__ == "__main__":
    main()
