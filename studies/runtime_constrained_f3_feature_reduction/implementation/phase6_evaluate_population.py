"""Phase 6 -- evaluate every candidate model on the COMPLETE 2025 population
(198,255 rows -- never the Phase 3 ranking sample). Predictive metrics,
quantile-matched AND count-matched population overlap grouped by
`regime_start_ns`, monthly stability, first-qualifying-checkpoint agreement.

T1/T2/T3 trigger-stage reapplication: per SPEC.md's own "where supported"
qualifier and the pre-execution audit's confirmation that this repo's actual
trigger stages are named trig_A/B/C30/C60/D15s/D30s/D60s (not T1/T2/T3),
full reapplication of that trigger grid is out of this bounded study's scope
-- disclosed explicitly in STUDY_REPORT.md rather than fabricated here.

KNOWN LIMITATION (completion-gate audit finding, disclosed not silently
carried): `find_count_matched_threshold()` below and the plain top-N%
quantile threshold are near-mathematically-forced to be identical in this
implementation, because both bands are defined as "top N% of the SAME
198,255-row population" via np.quantile -- baseline's row COUNT in its own
top-N% band is, by construction, always ~N% of the total regardless of
which model produced it, so matching a candidate to that count is
essentially the same operation as taking the candidate's own top-N%
quantile. This means the two required comparisons ("quantile-matched" and
"operating-point"/"count-matched") did not end up testing materially
different things here -- see STUDY_REPORT.md section 6 for the full
disclosure. A genuinely different operating-point comparison would need to
start from a real deployment threshold, which is out of this study's scope.
"""
from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import ARTIFACTS, RESULTS, SRC_STUDY, TARGET, metrics_row

BASELINE_ID = "F3_695_baseline"
CANDIDATE_IDS = [
    "F3_ablation_C_f0only_gbt_v1", "F3_ablation_D_ohlcv_gbt_v1", "F3_ablation_E_pricelvl_gbt_v1",
    "F3_ablation_F_f0_ohlcv_gbt_v1", "F3_ablation_G_f0_pricelvl_gbt_v1",
    "F3_top25_gbt_v1", "F3_top40_gbt_v1", "F3_top60_gbt_v1", "F3_top80_gbt_v1",
    "F3_top100_gbt_v1", "F3_top150_gbt_v1", "F3_top250_gbt_v1", "F3_live546_gbt_v2",
]
BANDS = {"top5pct": 0.95, "top2_5pct": 0.975}


def load_model_and_score(model_id: str, dev_df: pd.DataFrame) -> np.ndarray:
    model = joblib.load(ARTIFACTS / model_id / "model.joblib")
    feats = json.loads((ARTIFACTS / model_id / "feature_list.json").read_text())["ordered_features"]
    return model.predict_proba(dev_df[feats])[:, 1]


def regime_selection_set(df: pd.DataFrame, score_col: str, threshold: float) -> set:
    return set(df.loc[df[score_col] >= threshold, "regime_start_ns"].unique().tolist())


def find_count_matched_threshold(scores: np.ndarray, target_count: int) -> float:
    sorted_scores = np.sort(scores)[::-1]
    target_count = min(target_count, len(sorted_scores))
    if target_count <= 0:
        return float("inf")
    return float(sorted_scores[target_count - 1])


def main() -> None:
    t0 = time.time()
    dev_df = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet")
    dev_df["month"] = pd.to_datetime(dev_df["observation_time"], unit="ns", utc=True).dt.month
    y = dev_df[TARGET].astype(int).to_numpy()

    dev_df["score_baseline"] = load_model_and_score(BASELINE_ID, dev_df)
    baseline_scores = dev_df["score_baseline"].to_numpy()
    baseline_thresholds = {label: float(np.quantile(baseline_scores, q)) for label, q in BANDS.items()}
    baseline_regime_sets = {label: regime_selection_set(dev_df, "score_baseline", thr)
                            for label, thr in baseline_thresholds.items()}
    baseline_row_sets = {label: set(np.where(baseline_scores >= thr)[0].tolist())
                         for label, thr in baseline_thresholds.items()}

    rows_out = []
    population_rows = []
    for model_id in CANDIDATE_IDS:
        model_dir = ARTIFACTS / model_id
        if not (model_dir / "model.joblib").exists():
            print(f"SKIP {model_id}: artifact not found (not yet trained)")
            continue
        col = f"score_{model_id}"
        dev_df[col] = load_model_and_score(model_id, dev_df)
        cand_scores = dev_df[col].to_numpy()

        pred_metrics = metrics_row(y, cand_scores)
        score_corr = float(np.corrcoef(baseline_scores, cand_scores)[0, 1])
        rank_corr = float(spearmanr(baseline_scores, cand_scores).correlation)

        monthly_auc = {}
        for month, m_df in dev_df.groupby("month"):
            ym = m_df[TARGET].astype(int).to_numpy()
            if len(np.unique(ym)) < 2:
                continue
            monthly_auc[int(month)] = metrics_row(ym, m_df[col].to_numpy())["auc"]

        rows_out.append({
            "model_id": model_id, "auc": pred_metrics["auc"], "average_precision": pred_metrics["average_precision"],
            "logloss": pred_metrics["logloss"], "brier": pred_metrics["brier"],
            "auc_delta_vs_baseline": None,  # filled in after baseline_auc is known, below
            "score_pearson_corr_vs_baseline": score_corr, "score_rank_spearman_corr_vs_baseline": rank_corr,
            "monthly_auc_min": min(monthly_auc.values()), "monthly_auc_max": max(monthly_auc.values()),
            "monthly_auc": json.dumps(monthly_auc),
        })

        cand_thresholds_q = {label: float(np.quantile(cand_scores, q)) for label, q in BANDS.items()}
        for label in BANDS:
            # Quantile-matched
            cand_regimes_q = regime_selection_set(dev_df, col, cand_thresholds_q[label])
            both_q = baseline_regime_sets[label] & cand_regimes_q
            baseline_only_q = baseline_regime_sets[label] - cand_regimes_q
            cand_only_q = cand_regimes_q - baseline_regime_sets[label]
            regime_overlap_q = len(both_q) / max(1, len(baseline_regime_sets[label]))

            # Count-matched (operating point): candidate threshold reproducing baseline's ROW count
            baseline_n_rows = len(baseline_row_sets[label])
            cand_threshold_count_matched = find_count_matched_threshold(cand_scores, baseline_n_rows)
            cand_regimes_cm = regime_selection_set(dev_df, col, cand_threshold_count_matched)
            both_cm = baseline_regime_sets[label] & cand_regimes_cm
            regime_overlap_cm = len(both_cm) / max(1, len(baseline_regime_sets[label]))

            population_rows.append({
                "model_id": model_id, "band": label,
                "baseline_n_regimes": len(baseline_regime_sets[label]),
                "quantile_matched_cand_n_regimes": len(cand_regimes_q),
                "quantile_matched_regime_overlap": regime_overlap_q,
                "quantile_matched_both": len(both_q), "quantile_matched_baseline_only": len(baseline_only_q),
                "quantile_matched_cand_only": len(cand_only_q),
                "count_matched_threshold": cand_threshold_count_matched,
                "count_matched_regime_overlap": regime_overlap_cm,
                "count_matched_n_regimes": len(cand_regimes_cm),
            })
        print(f"[{model_id}] auc={pred_metrics['auc']:.4f} "
              f"top5pct_regime_overlap(quantile)={population_rows[-2]['quantile_matched_regime_overlap']:.3f}")

    baseline_auc = metrics_row(y, baseline_scores)["auc"]
    for r in rows_out:
        r["auc_delta_vs_baseline"] = r["auc"] - baseline_auc

    pd.DataFrame(rows_out).to_csv(RESULTS / "candidate_model_metrics.csv", index=False)
    pd.DataFrame(population_rows).to_csv(RESULTS / "candidate_population_overlap.csv", index=False)

    print(f"baseline auc={baseline_auc:.4f}, n_candidates_evaluated={len(rows_out)}")
    print(f"Phase 6 done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
