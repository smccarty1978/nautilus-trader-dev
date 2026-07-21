"""Phase 4: conditional recovery-MAE stop tables.

Population-agnostic aggregation over (decile, persistence_bucket,
score_path) -- restricted to D5-D10 ("weak territory") per the study
spec. MUST be computed on train+validation splits ONLY (never
dev_test/reserved_eval) -- stop distances estimated on data the policy
will later be evaluated against would be a train/serve leak.
"""
from __future__ import annotations
import pandas as pd

WEAK_DECILES = list(range(5, 11))
PERSISTENCE_BUCKETS = ["first_touch", "10s", "20s", "30s"]
SCORE_PATHS = ["rising", "flat", "improving"]


def build_conditional_tables(scored_atlas: pd.DataFrame) -> pd.DataFrame:
    """scored_atlas must already have: decile, persistence_bucket,
    score_path, recovery_mae_from_checkpoint_atr,
    recovery_mae_from_mfe_atr, time_to_recovery_s, time_to_failure_s,
    eventual_recovery_to_prior_mfe, eventual_new_mfe,
    terminal_weakness_label, split (restrict to train/validation
    BEFORE calling this)."""
    df = scored_atlas[
        (scored_atlas["decile"].isin(WEAK_DECILES))
        & (scored_atlas["persistence_bucket"] != "")
    ]
    rows = []
    for (decile, pbucket, spath), g in df.groupby(
        ["decile", "persistence_bucket", "score_path"], observed=True
    ):
        recovering = g[g["eventual_recovery_to_prior_mfe"]]
        terminal = g[~g["eventual_recovery_to_prior_mfe"]]
        row = {
            "decile": decile, "persistence_bucket": pbucket,
            "score_path": spath, "n": len(g),
            "n_recovering": len(recovering), "n_terminal": len(terminal),
            "prob_recover_to_prior_MFE": float(
                g["eventual_recovery_to_prior_mfe"].mean()),
            "prob_make_new_MFE": float(g["eventual_new_mfe"].mean()),
            "prob_terminal": float(
                (g["terminal_weakness_label"] == "TERMINAL_WEAKNESS").mean()),
        }
        for p in (0.50, 0.75, 0.90, 0.95):
            row[f"recovery_MAE_from_checkpoint_p{int(p*100)}"] = (
                float(recovering["recovery_mae_from_checkpoint_atr"].quantile(p))
                if len(recovering) else float("nan"))
            row[f"recovery_MAE_from_MFE_p{int(p*100)}"] = (
                float(recovering["recovery_mae_from_mfe_atr"].quantile(p))
                if len(recovering) else float("nan"))
        row["median_time_to_recovery"] = (
            float(recovering["time_to_recovery_s"].median())
            if len(recovering) else float("nan"))
        row["median_time_to_failure"] = (
            float(terminal["time_to_failure_s"].median())
            if len(terminal) else float("nan"))
        rows.append(row)
    return pd.DataFrame(rows)


def path_diagnostics(scored_atlas: pd.DataFrame) -> pd.DataFrame:
    """Supplementary diagnostic: sample counts and event rates by
    (decile, persistence_bucket, score_path) -- lets the reader assess
    reliability of each cell in the main table (n too small = don't
    trust that cell's stop distance)."""
    df = scored_atlas[scored_atlas["decile"].isin(WEAK_DECILES)]
    return (df.groupby(["decile", "persistence_bucket", "score_path"],
                            observed=True)
              .agg(n=("trade_id", "size"),
                      n_unique_trades=("trade_id", "nunique"),
                      mean_pred_prob=("pred_weakness_prob", "mean"),
                      event_rate=("is_terminal_weakness", "mean"))
              .reset_index())
