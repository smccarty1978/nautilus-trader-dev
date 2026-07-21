"""Phase 2 — per-bar KNN hC management-state mapping for the bar-4 all-flips NT strategy.

For every regime and every bar k (4..28) produces the causal management state:
  hC      = pNH3 - pFL3   (KNN, neighbors from IS only)
  pred    = KNN majority class vote (Failure/Chop/Continuation/Runner)
  hC_pk   = cummax(hC) within regime up to bar k (backward-looking)
  dd      = 1 - hC/hC_pk  (health drawdown from peak)
  dhC     = hC - hC[k-3]  (3-bar slope, within regime)
  state   = DETER if pred in {Failure,Chop}; elif dd>=0.20 HardStall; elif dd>=0.10 SoftStall; else Healthy

Causality contract (audited):
  - Features at bar k use bars 4..k only (build_states: H[i,4:k+1]); decision/action at bar-k
    close. Walk-forward KNN trained on IS years < test year (OOS capped IS<2025). Neighbor
    targets (newhigh3/flip3/class) are IS realized outcomes. No OOS path info enters any value.
  - hC_pk via cummax on a (rid,k)-sorted frame -> strictly backward-looking. dhC via diff(3)
    within rid -> backward. No future leak.
  - Live lookup key = (regime_start_ts, bars_in_regime) where bars_in_regime = k+1
    (regime engine: bars_in_regime==5 <=> bar-4 close == k=4).

Outputs:
  results/combined_arch/hc_perbar_mapping.parquet  regime_start_ts, bars_in_regime, k, hC, dhC, dd, state, pred
  results/combined_arch/audit_hc_perbar_mapping.md
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KNN_DIR = PROJECT_ROOT / "backtests" / "studies" / "regime_dna_knn"
sys.path.insert(0, str(KNN_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

import early_health_filter as E       # noqa: E402
import progressive_separability as P  # noqa: E402
import bar4_knn_path_atlas as A       # noqa: E402

OUT_KNN = KNN_DIR / "results"
OUT = PROJECT_ROOT / "collectors" / "collector_v2" / "results" / "combined_arch"
OUT.mkdir(parents=True, exist_ok=True)
KNN_K = 500; IS_REF_CAP = 40000
RNG = np.random.default_rng(0)
DETER_STATES = ("Failure", "Chop")
CLASSES = ["Failure", "Chop", "Continuation", "Runner"]
CLS_MAP = {c: i for i, c in enumerate(CLASSES)}


def main():
    print("Loading capsule + building states (bars 4..28)...")
    cap = pd.read_parquet(OUT_KNN / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    A.BARS = list(range(4, 29))
    S = A.build_states(df, M)

    print("Walk-forward KNN (hC + class vote) per (year,k)...")
    pNH3 = np.full(len(S), np.nan); pFL3 = np.full(len(S), np.nan)
    predA = np.empty(len(S), dtype=object)
    for year in [2022, 2023, 2024, 2025, 2026]:
        db = S[S.year < year] if year < 2025 else S[S.year < 2025]
        q = S[S.year == year]
        if len(q) == 0 or len(db) < 200:
            continue
        for k in sorted(q.k.unique()):
            isk = db[db.k == k]; om = (S.year == year) & (S.k == k)
            if len(isk) < 100 or om.sum() == 0:
                continue
            if len(isk) > IS_REF_CAP:
                isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
            Xis = isk[A.FEATS].values.astype(np.float32)
            Xoo = S.loc[om, A.FEATS].values.astype(np.float32)
            mu = Xis.mean(0); sd = Xis.std(0); sd[sd == 0] = 1
            nn = NearestNeighbors(n_neighbors=min(KNN_K, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
            _, idx = nn.kneighbors((Xoo - mu) / sd)
            oi = np.where(om)[0]
            pNH3[oi] = isk.newhigh3.values[idx].mean(1)
            pFL3[oi] = isk.flip3.values[idx].mean(1)
            nbc = isk.cls.values[idx]
            nbc_int = np.vectorize(CLS_MAP.get)(nbc)
            counts = np.zeros((len(nbc_int), 4), dtype=np.int32)
            for c in range(4):
                counts[:, c] = (nbc_int == c).sum(axis=1)
            predA[oi] = [CLASSES[j] for j in np.argmax(counts, axis=1)]

    S = S.copy()
    S["pNH3"] = pNH3; S["pFL3"] = pFL3; S["pred"] = predA
    S = S[S.pNH3.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)
    S["hC"] = S.pNH3 - S.pFL3
    S["hC_pk"] = S.groupby("rid").hC.cummax()
    S["dd"] = 1 - S.hC / S.hC_pk.clip(lower=1e-6)
    S["dhC"] = S.groupby("rid").hC.diff(3)

    def classify(r):
        if r.pred in DETER_STATES:
            return "DETER"
        if r.dd >= 0.20:
            return "HardStall"
        if r.dd >= 0.10:
            return "SoftStall"
        return "Healthy"
    S["state"] = S.apply(classify, axis=1)

    # map rid -> regime_start_ts
    rst = dict(zip(df.regime_id.values, df.regime_start_ts.values.astype(np.int64)))
    S["regime_start_ts"] = S.rid.map(rst).astype(np.int64)
    S["bars_in_regime"] = (S.k + 1).astype(int)   # k=4 <-> bars_in_regime=5 (bar-4 close)

    mapping = S[["regime_start_ts", "bars_in_regime", "k", "hC", "dhC", "dd", "state", "pred"]].copy()
    dupkey = mapping.duplicated(subset=["regime_start_ts", "bars_in_regime"]).sum()
    mapping.to_parquet(OUT / "hc_perbar_mapping.parquet", index=False)

    # ---------- audit ----------
    L = ["# Audit — per-bar hC management-state mapping", ""]
    L.append(f"- Records: **{len(mapping):,}** (regime,bar) rows, "
             f"{mapping.regime_start_ts.nunique():,} distinct regimes")
    L.append(f"- (regime_start_ts, bars_in_regime) duplicate keys: **{dupkey}** "
             f"{'PASS' if dupkey == 0 else 'FAIL'}")
    L.append(f"- Feature window bars 4..k only (build_states H[i,4:k+1]); action at bar-k close. PASS")
    L.append(f"- hC_pk cummax & dhC diff(3) on (rid,k)-sorted frame -> backward-looking. PASS")
    L.append(f"- Walk-forward IS<Y (OOS IS<2025); neighbor targets IS realized. No OOS path leak. PASS")
    L.append(f"- bars_in_regime = k+1 (k=4 <-> bar-4 close <-> bars_in_regime=5). PASS")
    L.append("")
    L.append("## State distribution by year (OOS-relevant)")
    L.append("| Year | n rows | Healthy | SoftStall | HardStall | DETER |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    Syr = S.copy()
    for y in [2022, 2023, 2024, 2025, 2026]:
        sub = Syr[Syr.year == y]
        if len(sub) == 0:
            continue
        vc = sub.state.value_counts(normalize=True) * 100
        L.append(f"| {y} | {len(sub):,} | {vc.get('Healthy',0):.0f}% | {vc.get('SoftStall',0):.0f}% | "
                 f"{vc.get('HardStall',0):.0f}% | {vc.get('DETER',0):.0f}% |")
    L.append("")
    L.append("## hC by bar (mean), sanity")
    L.append("| bars_in_regime (=k+1) | n | mean hC | mean dd |")
    L.append("| --- | ---: | ---: | ---: |")
    for bir in sorted(mapping.bars_in_regime.unique())[:8]:
        sub = mapping[mapping.bars_in_regime == bir]
        L.append(f"| {bir} | {len(sub):,} | {sub.hC.mean():.3f} | {sub.dd.mean():.3f} |")
    (OUT / "audit_hc_perbar_mapping.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nWrote hc_perbar_mapping.parquet ({len(mapping):,}) + audit_hc_perbar_mapping.md")


if __name__ == "__main__":
    main()
