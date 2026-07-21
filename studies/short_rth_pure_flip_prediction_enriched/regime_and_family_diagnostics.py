"""Regime-level diagnostics + feature-family contribution, for all 8
(feature_set, model) combos, on raw (uncalibrated) scores.

Regime-level framing (documented, since the SPEC leaves exact aggregation
open): every regime in this population eventually flips by construction
(entry_surface.build_surface only emits checkpoints while the regime is
still active), so a naive "did the regime flip" label is degenerate
(always 1) and cannot support a regime-level AUC on its own. Instead:

  - `warning zone` = a regime's own rows with bearish_regime_flip_within_300s
    == True (the tail of the regime, <=300s before its actual flip).
  - `regime_max_score` / `regime_max_score_label`: the row with the highest
    raw score in the regime, and whether THAT row's own label is True --
    "when the model is most confident about this regime, is it right?"
    This is genuinely non-degenerate and de-duplicates the heavy within-
    regime row correlation a naive row-level AUC would inflate.
  - `regime_level_auc` = AUC of (regime_max_score, regime_max_score_label)
    across regimes.
  - Thresholds (top 20/10/5% of raw score) are computed on 2025 ONLY per
    (feature_set, model) and applied FROZEN to both splits (never re-derived
    on 2026), matching this project's standing retention-band-cutoff
    convention.
  - `missed_flip_rate` (per threshold): fraction of regimes where NO
    warning-zone row ever crosses the threshold -- the model never raised
    an alarm even during the genuinely-imminent window.
  - `false_positive_rate` (per threshold): fraction of regimes whose FIRST
    crossing of the threshold happens on a row with label False (a
    premature alarm as the very first signal).
  - `median_lead_time_s`: among regimes that DO cross the threshold,
    median (confirm_flip_ns - first_cross_observation_time).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK, RESULTS = HERE / "_work", HERE / "results"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from features.registry import FEATURE_REGISTRY  # noqa: E402

FEATURE_SETS = ["F0_existing_only", "F1_volume_delta_only",
                "F2_price_levels_only", "F3_volume_delta_plus_price_levels"]
MODELS = ["logreg", "gbt"]
THRESHOLDS = {"top20": 0.80, "top10": 0.90, "top5": 0.95}
TARGET = "bearish_regime_flip_within_300s"
NEEDED_COLS = ["regime_start_ns", "observation_time", "confirm_flip_ns", TARGET]
# Frozen on 2025, applied unchanged to 2026 -- populated during the 2025
# pass of main()'s split loop (2025 iterates first), read during the 2026
# pass. Never re-derived on 2026.
thresholds_by_combo: dict[str, dict] = {}


def feature_family(feat: str, f0_feats: set[str]) -> str:
    if feat in f0_feats:
        return "existing"
    base = feat.split("__")[0] if "__" in feat else feat
    d = FEATURE_REGISTRY.get(feat) or FEATURE_REGISTRY.get(base)
    if d is not None:
        return "volume_delta" if d.family == "ohlcv_est_delta" else "price_level"
    raise RuntimeError(f"could not classify feature family for {feat!r}")


def regime_level_summary(df: pd.DataFrame, score_col: str, thresholds: dict) -> dict:
    df = df.sort_values(["regime_start_ns", "observation_time"], kind="stable")

    idx_max = df.groupby("regime_start_ns")[score_col].idxmax()
    peak = df.loc[idx_max, ["regime_start_ns", score_col, TARGET]].rename(
        columns={score_col: "regime_max_score", TARGET: "regime_max_score_label"})
    regime_auc = (roc_auc_score(peak["regime_max_score_label"].astype(int), peak["regime_max_score"])
                  if peak["regime_max_score_label"].nunique() > 1 else np.nan)

    n_regimes = peak["regime_start_ns"].nunique()
    top_decile_cut = peak["regime_max_score"].quantile(0.90)
    top_decile = peak[peak["regime_max_score"] >= top_decile_cut]
    top_decile_flip_rate = float(top_decile["regime_max_score_label"].mean()) if len(top_decile) else np.nan
    base_rate = float(peak["regime_max_score_label"].mean())

    out = {"regime_level_auc": regime_auc, "n_regimes": n_regimes,
           "regime_level_top_decile_flip_rate": top_decile_flip_rate,
           "regime_level_base_rate": base_rate}

    for name, cutoff in thresholds.items():
        crossed = df[df[score_col] >= cutoff]
        first_cross = (crossed.sort_values("observation_time", kind="stable")
                      .groupby("regime_start_ns", as_index=False).first())
        warning_zone = df[df[TARGET]]
        warn_crossed_regimes = set(
            warning_zone.loc[warning_zone[score_col] >= cutoff, "regime_start_ns"])
        all_regimes = set(df["regime_start_ns"])
        missed = all_regimes - warn_crossed_regimes
        missed_rate = len(missed) / len(all_regimes) if all_regimes else np.nan

        false_positive_n = int((~first_cross[TARGET]).sum()) if len(first_cross) else 0
        n_crossed_regimes = len(first_cross)
        fp_rate = false_positive_n / n_crossed_regimes if n_crossed_regimes else np.nan

        lead_time_s = (first_cross["confirm_flip_ns"] - first_cross["observation_time"]) / 1e9
        median_lead = float(lead_time_s.median()) if len(lead_time_s) else np.nan

        out[f"{name}_cutoff_score"] = float(cutoff)
        out[f"{name}_n_regimes_crossed"] = n_crossed_regimes
        out[f"{name}_pct_regimes_crossed"] = n_crossed_regimes / n_regimes if n_regimes else np.nan
        out[f"{name}_missed_flip_rate"] = missed_rate
        out[f"{name}_false_positive_rate"] = fp_rate
        out[f"{name}_median_lead_time_s"] = median_lead
    return out


def main() -> None:
    feature_sets = json.loads((WORK / "feature_sets.json").read_text(encoding="utf-8"))
    f0_feats = set(feature_sets["F0_existing_only"])

    regime_rows = []
    for split_name, path in (("2025", WORK / "scored_dev_2025.parquet"), ("2026", WORK / "scored_test_2026.parquet")):
        for fs_name in FEATURE_SETS:
            for model_name in MODELS:
                key = f"{fs_name}__{model_name}"
                score_col = f"score_{key}_raw"
                df = pd.read_parquet(path, columns=NEEDED_COLS + [score_col])
                if split_name == "2025":
                    thresholds = {name: float(df[score_col].quantile(q)) for name, q in THRESHOLDS.items()}
                    thresholds_by_combo[key] = thresholds
                else:
                    thresholds = thresholds_by_combo[key]
                summary = regime_level_summary(df, score_col, thresholds)
                regime_rows.append({"feature_set": fs_name, "model": model_name,
                                    "split": split_name, **summary})

    pd.DataFrame(regime_rows).to_csv(RESULTS / "regime_level_diagnostics.csv", index=False)

    imp = pd.read_csv(RESULTS / "feature_importance.csv")
    imp["abs_importance"] = imp["coefficient"].abs()
    imp["family"] = imp["feature"].apply(lambda f: feature_family(f, f0_feats))
    per_feature = imp.groupby(["feature_set", "model", "feature", "family"], as_index=False)["abs_importance"].sum()
    family_summary = (per_feature.groupby(["feature_set", "model", "family"], as_index=False)
                      .agg(n_features=("feature", "size"), total_abs_importance=("abs_importance", "sum")))
    totals = family_summary.groupby(["feature_set", "model"])["total_abs_importance"].transform("sum")
    family_summary["share"] = family_summary["total_abs_importance"] / totals
    family_summary.to_csv(RESULTS / "feature_family_contribution.csv", index=False)

    top50 = (per_feature.sort_values(["feature_set", "model", "abs_importance"], ascending=[True, True, False])
            .groupby(["feature_set", "model"]).head(50))
    top50.to_csv(WORK / "top50_features_per_combo.csv", index=False)

    print(pd.DataFrame(regime_rows)[["feature_set", "model", "split", "regime_level_auc",
                                     "top10_missed_flip_rate", "top10_false_positive_rate",
                                     "top10_median_lead_time_s"]].to_string(index=False))
    print(family_summary.to_string(index=False))


if __name__ == "__main__":
    main()
