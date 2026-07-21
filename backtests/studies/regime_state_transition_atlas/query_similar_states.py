"""NQ Regime State Transition Atlas - Similar States Query Engine.

Provides exact bucket matching and K-Nearest Neighbors (KNN) lookup of
historical similar states from the In-Sample (IS: 2021-2024) database.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUT = Path("studies/regime_state_transition_atlas/results")

NUMERIC_COLS = [
    "current_pnl_atr", "mfe_so_far_atr", "mae_so_far_atr", "pullback_from_peak_atr",
    "consecutive_no_continuation_bars", "continuation_count_so_far",
    "5s_flip_count_since_1m_start", "ema9_slope_atr", "ema9_slope_change",
    "distance_to_ema9_atr", "volume_percentile_20"
]

CATEGORICAL_COLS = [
    "bar_index_in_regime", "last_3_bar_pattern", "regime_5s_aligned"
]

OUTCOME_COLS = [
    "next_bar_makes_continuation",
    "next_3_bars_recover_prior_peak",
    "pt050_before_sl050",
    "pt100_before_sl100",
    "forward_pnl_to_regime_exit_atr",
    "future_mfe_from_here_atr",
    "future_mae_from_here_atr"
]


class StateMemoryQueryEngine:
    def __init__(self, df_all: pd.DataFrame = None):
        if df_all is None:
            state_rows = OUT / "state_rows.parquet"
            fwd_labels = OUT / "forward_labels.parquet"
            if not state_rows.exists() or not fwd_labels.exists():
                raise FileNotFoundError("Atlas Parquet files not found under results/.")
            df_states = pd.read_parquet(state_rows)
            df_labels = pd.read_parquet(fwd_labels)
            self.df_all = pd.merge(df_states, df_labels, on=["regime_id", "bar_ts"])
        else:
            self.df_all = df_all.copy()
            
        # Clean numeric cols
        self.df_all[NUMERIC_COLS] = self.df_all[NUMERIC_COLS].fillna(0.0)
        
        # Split into IS database
        self.df_is = self.df_all[self.df_all["year"] < 2025].copy()
        
        # Fit StandardScaler on IS numeric features
        self.means = self.df_is[NUMERIC_COLS].mean()
        self.stds = self.df_is[NUMERIC_COLS].std().replace(0.0, 1.0)  # avoid div by zero
        
        # Add standardized columns to IS database
        for col in NUMERIC_COLS:
            self.df_is[f"scaled_{col}"] = (self.df_is[col] - self.means[col]) / self.stds[col]

    def scale_row(self, row: pd.Series) -> pd.Series:
        scaled = row.copy()
        for col in NUMERIC_COLS:
            scaled[f"scaled_{col}"] = (row[col] - self.means[col]) / self.stds[col]
        return scaled

    def query_exact_bucket(self, query_row: pd.Series) -> pd.DataFrame:
        """Returns all IS rows matching exact categorical features, excluding the query's regime."""
        idx = query_row["bar_index_in_regime"]
        pat = query_row["last_3_bar_pattern"]
        align = query_row["regime_5s_aligned"]
        
        mask = (
            (self.df_is["bar_index_in_regime"] == idx) &
            (self.df_is["last_3_bar_pattern"] == pat) &
            (self.df_is["regime_5s_aligned"] == align) &
            (self.df_is["regime_id"] != query_row["regime_id"]) &
            # As-of-time (audit v5): neighbors must strictly precede the query,
            # so an in-sample query never borrows a future state's outcome.
            (self.df_is["bar_ts"] < query_row["bar_ts"])
        )
        return self.df_is[mask]

    def query_knn(self, query_row: pd.Series, k: int = 500) -> pd.DataFrame:
        """Returns the k-nearest neighbors in IS matching the exact bar_index_in_regime, excluding same regime."""
        idx = query_row["bar_index_in_regime"]
        
        # Filter candidates by same bar index, exclude same regime, and enforce
        # as-of-time (audit v5): only strictly-earlier states are eligible.
        candidates = self.df_is[
            (self.df_is["bar_index_in_regime"] == idx) &
            (self.df_is["regime_id"] != query_row["regime_id"]) &
            (self.df_is["bar_ts"] < query_row["bar_ts"])
        ].copy()
        
        if len(candidates) == 0:
            return candidates
            
        # Standardize the query row
        q_scaled = self.scale_row(query_row)
        
        # Calculate Euclidean distance
        dist_cols = [f"scaled_{col}" for col in NUMERIC_COLS]
        q_vec = q_scaled[dist_cols].values.astype(np.float32)
        cand_matrix = candidates[dist_cols].values.astype(np.float32)
        
        dists = np.sqrt(np.sum((cand_matrix - q_vec) ** 2, axis=1))
        candidates["distance"] = dists
        
        return candidates.nsmallest(k, "distance")

    def estimate_outcomes(self, neighbors: pd.DataFrame) -> dict:
        """Computes probability and expected value outcome statistics for a set of neighbors."""
        n = len(neighbors)
        if n == 0:
            return {
                "neighbor_count": 0,
                "P_next_continuation": np.nan,
                "P_recover_peak_next_3": np.nan,
                "P_pt050_before_sl050": np.nan,
                "P_pt100_before_sl100": np.nan,
                "mean_forward_pnl": np.nan,
                "median_forward_pnl": np.nan,
                "mean_future_mfe": np.nan,
                "mean_future_mae": np.nan
            }
            
        return {
            "neighbor_count": n,
            "P_next_continuation": float(neighbors["next_bar_makes_continuation"].mean()),
            "P_recover_peak_next_3": float(neighbors["next_3_bars_recover_prior_peak"].mean()),
            "P_pt050_before_sl050": float(neighbors["pt050_before_sl050"].mean()),
            "P_pt100_before_sl100": float(neighbors["pt100_before_sl100"].mean()),
            "mean_forward_pnl": float(neighbors["forward_pnl_to_regime_exit_dollars"].mean()),
            "median_forward_pnl": float(neighbors["forward_pnl_to_regime_exit_dollars"].median()),
            "mean_future_mfe": float(neighbors["future_mfe_from_here_atr"].mean()),
            "mean_future_mae": float(neighbors["future_mae_from_here_atr"].mean())
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regime-id", type=int, required=True)
    ap.add_argument("--bar-ts", type=int, required=True)
    ap.add_argument("--k", type=int, default=500)
    args = ap.parse_args()
    
    print("Loading query engine...")
    engine = StateMemoryQueryEngine()
    
    # Locate query row
    match = engine.df_all[
        (engine.df_all["regime_id"] == args.regime_id) &
        (engine.df_all["bar_ts"] == args.bar_ts)
    ]
    if match.empty:
        print(f"Row for regime_id={args.regime_id}, bar_ts={args.bar_ts} not found.")
        return
        
    query_row = match.iloc[0]
    print("\n--- QUERY STATE ---")
    for col in CATEGORICAL_COLS + NUMERIC_COLS:
        print(f"  {col}: {query_row[col]}")
        
    print("\n--- EXACT BUCKET RESULTS ---")
    exact_res = engine.query_exact_bucket(query_row)
    stats_exact = engine.estimate_outcomes(exact_res)
    for k_, v_ in stats_exact.items():
        if isinstance(v_, float) and k_.startswith("P_"):
            print(f"  {k_}: {v_*100:.1f}%")
        else:
            print(f"  {k_}: {v_}")
            
    print(f"\n--- KNN RESULTS (k={args.k}) ---")
    knn_res = engine.query_knn(query_row, k=args.k)
    stats_knn = engine.estimate_outcomes(knn_res)
    for k_, v_ in stats_knn.items():
        if isinstance(v_, float) and k_.startswith("P_"):
            print(f"  {k_}: {v_*100:.1f}%")
        else:
            print(f"  {k_}: {v_}")


if __name__ == "__main__":
    main()
