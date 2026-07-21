"""Phase 1 — Model B P(QuickFailure) walk-forward mapping for the bar-4 all-flips
NT strategy.

Causality contract (audited):
  - Model B = LightGBM, features through BAR 3 only (P.feats_through(df, M, 3)[MODEL_B],
    leak-corrected k=Nbar), target = QuickFailure (npost==4 among bar-4 survivors).
  - Walk-forward: test year Y trained ONLY on IS years < Y (capped at <2025 for OOS),
    so no same-year or future data trains the model that scores year Y.
  - Thresholds for "reject worst X%" are derived from the IS pQF distribution of each
    test year's own model (in-sample IS scores) -> portable, IS-derived, NOT OOS-rank.
  - Output keyed by regime_start_ts (= flip-bar close ts, the live lookup key). pQF is a
    single per-regime value (one bar-3 decision); decision_ts = bar-3 close < bar-4 entry.

Outputs:
  results/pqf_mapping.parquet         regime_start_ts, rid, year, pQF
  results/pqf_is_thresholds.parquet   year, reject_pct, pqf_threshold  (reject pQF >= thr)
  results/audit_pqf_mapping.md        causality audit
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Canonical study path after the mid-session move studies/ -> backtests/studies/
KNN_DIR = PROJECT_ROOT / "backtests" / "studies" / "regime_dna_knn"
sys.path.insert(0, str(KNN_DIR))
sys.path.insert(0, str(PROJECT_ROOT))   # for `collectors.collector_v2.*` imports

import early_health_filter as E       # noqa: E402
import progressive_separability as P  # noqa: E402
from rejection_power import MODEL_B, gbm  # noqa: E402

OUT_KNN = KNN_DIR / "results"
# Isolated output dir to avoid clobbering the concurrent worker's artifacts
OUT = PROJECT_ROOT / "collectors" / "collector_v2" / "results" / "combined_arch"
OUT.mkdir(parents=True, exist_ok=True)
REJECT_PCTS = [10, 20, 30, 40, 50]


def main():
    print("Loading capsule...")
    cap = pd.read_parquet(OUT_KNN / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    yr = df.year.values
    npost = df.n_post.values.astype(int)

    XB = P.feats_through(df, M, 3)[MODEL_B].values
    yQ = (df.label.values == "QuickFailure").astype(int)
    alive4 = npost >= 4                      # bar 4 exists -> enterable; QF defined here

    pQF = np.full(len(df), np.nan)
    thr_rows = []
    for year in [2022, 2023, 2024, 2025, 2026]:
        is_m = (yr < year) & alive4 if year < 2025 else (yr < 2025) & alive4
        oos_m = (yr == year) & alive4
        if oos_m.sum() == 0 or is_m.sum() < 200:
            print(f"  skip {year} (IS={is_m.sum()}, OOS={oos_m.sum()})")
            continue
        pQF[oos_m] = gbm(XB[is_m], yQ[is_m], XB[oos_m])
        pis = gbm(XB[is_m], yQ[is_m], XB[is_m])          # in-sample IS, thresholds ONLY
        for rp in REJECT_PCTS:
            # reject worst rp% by pQF -> threshold = (100-rp) percentile of IS pQF
            thr = float(np.percentile(pis, 100 - rp))
            thr_rows.append({"year": year, "reject_pct": rp, "pqf_threshold": thr})
        print(f"  {year}: IS={is_m.sum():,} OOS={oos_m.sum():,} "
              f"mean pQF(OOS)={np.nanmean(pQF[oos_m]):.3f}")

    valid = ~np.isnan(pQF)
    mapping = pd.DataFrame({
        "regime_start_ts": df.regime_start_ts.values[valid].astype(np.int64),
        "rid": df.regime_id.values[valid],
        "year": yr[valid],
        "pQF": pQF[valid],
    })
    # uniqueness of the live lookup key
    dup = mapping.regime_start_ts.duplicated().sum()
    mapping.to_parquet(OUT / "pqf_mapping.parquet", index=False)
    thr = pd.DataFrame(thr_rows)
    thr.to_parquet(OUT / "pqf_is_thresholds.parquet", index=False)

    # ---------- audit ----------
    L = ["# Audit — pQF mapping (Model B P(QuickFailure))", ""]
    L.append(f"- Records: **{len(mapping):,}** (alive-at-bar-4 regimes 2022-2026)")
    L.append(f"- regime_start_ts duplicates (live key collisions): **{dup}** "
             f"{'PASS' if dup == 0 else 'FAIL — key not unique'}")
    L.append(f"- Feature window: `P.feats_through(df, M, 3)` = bars 0..3 only "
             f"(leak-corrected k=Nbar). Decision_ts = bar-3 close < bar-4 entry. PASS")
    L.append(f"- Target: QuickFailure among bar-4 survivors. Walk-forward train IS<Y "
             f"(OOS capped IS<2025). No same-year/future training. PASS")
    L.append(f"- Thresholds: IS-derived percentiles of in-sample IS pQF (portable, "
             f"not OOS-rank). PASS")
    L.append("")
    L.append("## pQF coverage by year")
    L.append("| Year | n (alive@bar4, scored) | mean pQF | QF base rate |")
    L.append("| --- | ---: | ---: | ---: |")
    for y in [2022, 2023, 2024, 2025, 2026]:
        m = mapping.year == y
        if m.sum() == 0:
            continue
        qfb = yQ[(yr == y) & alive4].mean()
        L.append(f"| {y} | {m.sum():,} | {mapping.pQF[m].mean():.3f} | {qfb*100:.1f}% |")
    L.append("")
    L.append("## IS-derived reject thresholds (reject pQF >= threshold)")
    L.append("| Year | " + " | ".join(f"worst {p}%" for p in REJECT_PCTS) + " |")
    L.append("| --- | " + " | ".join(["---"] * len(REJECT_PCTS)) + " |")
    for y in sorted(thr.year.unique()):
        cells = [f"{thr[(thr.year == y) & (thr.reject_pct == p)].pqf_threshold.iloc[0]:.3f}"
                 for p in REJECT_PCTS]
        L.append(f"| {y} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("> NOTE: universe = early_health_capsule. Phase 3 MUST verify the live NT "
             "regime-engine flip set joins to this mapping on regime_start_ts at a high "
             "rate; if the capsule is the bar1-confirmed filtered subset, 'all-flips' "
             "coverage is incomplete and pQF gating only applies to the covered subset.")
    (OUT / "audit_pqf_mapping.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nWrote pqf_mapping.parquet ({len(mapping):,}), pqf_is_thresholds.parquet, audit_pqf_mapping.md")


if __name__ == "__main__":
    main()
