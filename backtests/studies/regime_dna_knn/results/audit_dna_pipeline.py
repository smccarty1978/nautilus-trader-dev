"""Data-driven causal-invariant audit of the Regime DNA pipeline.
Complements the lookahead-auditor subagent (static code analysis). Checks the
produced parquets for the invariants the SPEC + amendments require.

    python studies/regime_dna_knn/audit_dna_pipeline.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
ATLAS = Path("studies/regime_state_transition_atlas/results")


def main():
    L = ["# DNA Pipeline Data Audit", ""]
    ok = True

    dna = pd.read_parquet(OUT / "regime_dna.parquet")
    lab = pd.read_parquet(OUT / "dna_race_labels.parquet")

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        L.append(f"- {'PASS' if cond else 'FAIL'} — {name}. {detail}")

    # 1. ATR floor: no denominator blow-ups (atlas had 90-ATR artifacts)
    mx = float(np.abs(lab["pt200_sl100_gross_pnl"]).max())
    check("ATR floor bounds payoff (no 90-ATR blow-ups)", mx < 50000,
          f"max |pt200 gross| = ${mx:,.0f} (a 2-ATR target at floored ATR is bounded).")
    check("atr_norm_at_flip strictly positive", float(dna["atr_norm_at_flip"].min()) > 0,
          f"min={dna['atr_norm_at_flip'].min():.3f}")

    # 2. Session features are real (not stubbed to 0)
    sess_std = float(dna["distance_to_vwap_atr"].std())
    check("Session features are populated (not stubbed)", sess_std > 0.01, f"vwap-dist std={sess_std:.3f}")

    # 3. Labels: race hit rates in [0,1], bars positive
    for b in ("pt050_sl025", "pt100_sl050", "pt200_sl100"):
        hr = float(lab[f"{b}_pt_hit"].mean())
        check(f"{b} hit rate plausible", 0.0 < hr < 1.0, f"hit={hr:.3f}")
    check("race bars strictly positive", float(lab["pt100_sl050_bars"].min()) > 0,
          f"min bars={lab['pt100_sl050_bars'].min():.2f}")

    # 4. regime_id alignment with atlas live states
    sr = pd.read_parquet(ATLAS / "state_rows.parquet", columns=["regime_id"])
    shared = len(set(sr.regime_id.unique()) & set(dna.regime_id.unique()))
    check("regime_id aligns with atlas state_rows", shared > 100000,
          f"{shared:,} shared regime_ids (merge feasible)")

    # 5. bars 1-4 uniform soft-archetype prob (amendment 3)
    p = OUT / "dna_live_state_rows.parquet"
    if p.exists():
        dl = pd.read_parquet(p)
        pcols = [c for c in dl.columns if c.startswith("prob_cluster_")]
        K = len(pcols)
        early = dl[dl.bar_index_in_regime <= 4]
        uni = np.allclose(early[pcols].values, 1.0 / K, atol=1e-6) if len(early) else True
        check("bars 1-4 use uniform archetype prob (1/K)", uni, f"K={K}")
        psum = dl[pcols].sum(axis=1)
        check("archetype prob vectors sum to ~1", bool(np.allclose(psum, 1.0, atol=1e-3)),
              f"mean sum={psum.mean():.4f}")
    else:
        L.append("- (dna_live_state_rows.parquet not built yet — skipping prob checks)")

    # 6. walk-forward scores: OOS rows only from 2025/2026
    sp = OUT / "dna_knn_scores.parquet"
    if sp.exists():
        sc = pd.read_parquet(sp, columns=["year", "is_oos"])
        check("OOS scores only from 2025/2026",
              bool(set(sc[sc.is_oos == 1].year.unique()) <= {2025, 2026}),
              f"OOS years={sorted(sc[sc.is_oos==1].year.unique())}")

    L.insert(1, f"**Overall: {'ALL PASS' if ok else 'FAILURES PRESENT'}**\n")
    (OUT / "dna_data_audit.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print("\nWrote dna_data_audit.md")


if __name__ == "__main__":
    main()
