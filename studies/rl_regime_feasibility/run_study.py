"""Full study runner for RL regime feasibility.

Runs all phases in order:
  Phase 1: collect feature snapshots (NT BacktestEngine)
  Phase 2: compute forward labels (offline)
  Phase 3: oracle computation (Gate 2 ceiling)
  Phase 4: Gate 1 — causal ML models (train/val AUC)
  Phase 5: Gate 2 — policy vs oracle on test set
  Phase 6: write final_report.md

Usage:
  python studies/rl_regime_feasibility/run_study.py [--phase N]

  --phase 1  collection only
  --phase 2  labels only (requires phase 1 output)
  --phase 3  oracle only (requires phase 1+2)
  --phase 4  gate1 only  (requires phase 1+2)
  --phase 5  gate2 only  (requires phase 1+2+3+4)
  (no flag) run all phases
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR   = Path("studies/rl_regime_feasibility/results")
SNAP_FILE = OUT_DIR / "feature_snapshots.parquet"
LBL_FILE  = OUT_DIR / "forward_labels.parquet"
ORC_FILE  = OUT_DIR / "oracle_summary.parquet"
G1_FILE   = OUT_DIR / "gate1_metrics.parquet"
G2_FILE   = OUT_DIR / "gate2_policy_results.parquet"


def _header(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def phase1_collect() -> None:
    _header("PHASE 1 — NT FEATURE COLLECTION")
    from studies.rl_regime_feasibility.run_collection import run
    run()


def phase2_labels() -> None:
    _header("PHASE 2 — OFFLINE LABEL COMPUTATION")
    if not SNAP_FILE.exists():
        raise FileNotFoundError(f"Missing {SNAP_FILE} — run phase 1 first")
    from studies.rl_regime_feasibility.labels import compute_labels
    compute_labels()


def phase3_oracle() -> None:
    _header("PHASE 3 — ORACLE COMPUTATION")
    if not LBL_FILE.exists():
        raise FileNotFoundError(f"Missing {LBL_FILE} — run phase 2 first")
    from studies.rl_regime_feasibility.oracle import compute_oracle
    compute_oracle()


def phase4_gate1() -> None:
    _header("PHASE 4 — GATE 1: CAUSAL ML MODELS")
    if not LBL_FILE.exists():
        raise FileNotFoundError(f"Missing {LBL_FILE} — run phase 2 first")
    from studies.rl_regime_feasibility.causal_models import run_gate1
    run_gate1()


def phase5_gate2() -> None:
    _header("PHASE 5 — GATE 2: POLICY vs ORACLE")
    for f in [ORC_FILE, G1_FILE]:
        if not f.exists():
            raise FileNotFoundError(f"Missing {f} — run phases 3+4 first")
    from studies.rl_regime_feasibility.causal_policy import run_gate2
    run_gate2()


def phase6_report() -> None:
    _header("PHASE 6 — FINAL REPORT")

    import pandas as pd, math

    gate1_ok = False
    gate2_ok = False
    gate1_summary = "not run"
    gate2_summary = "not run"

    if G1_FILE.exists():
        g1 = pd.read_parquet(G1_FILE)
        n_pass = int((g1["gate_pass"] == True).sum())
        gate1_ok = n_pass >= 2
        best_auc = float(g1["auc_val"].max()) if len(g1) else float("nan")
        gate1_summary = f"Best val_AUC={best_auc:.4f}, passing horizons={n_pass}"

    if G2_FILE.exists():
        g2 = pd.read_parquet(G2_FILE)
        best_ev = float(g2["ev_per_ep"].max()) if len(g2) else float("nan")
        pct_orc = float(g2["pct_oracle"].max()) if len(g2) else float("nan")
        gate2_ok = (not math.isnan(pct_orc)) and pct_orc >= 50.0
        best_pol = g2.loc[g2["ev_per_ep"].idxmax(), "policy"] if len(g2) else "n/a"
        gate2_summary = (
            f"Best policy={best_pol}  EV/ep={best_ev:+.2f}  "
            f"({pct_orc:.1f}% of oracle)"
        )

    if ORC_FILE.exists():
        orc = pd.read_parquet(ORC_FILE)
        orc_test = orc[orc["period"] == "test"]
        oracle_ev = float(orc_test["oracle_pnl"].mean()) if len(orc_test) else float("nan")
    else:
        oracle_ev = float("nan")

    rl_recommended = gate1_ok and gate2_ok

    report = f"""# RL Regime Feasibility Study — Final Report

## Study Design
- **Signal**: 1m regime flip (EMA3/EMA9 on NQ.v.0 1s bars)
- **Observation**: every 5 seconds from flip through episode end
- **Features**: 28 features across 5 families (path, volatility/volume, momentum, multi-TF regime, structural)
- **Horizons**: 5s, 15s, 30s, 60s, 120s, 300s
- **Catastrophic stop**: 1.50 × ATR (from flip close)
- **Episode max duration**: 30 minutes
- **Cost**: $5 RT base commission

## Data Splits
| Period | Dates | Role |
|--------|-------|------|
| Train | 2024-01-01 to 2024-12-31 | Model fitting |
| Validation | 2025-01-01 to 2025-02-28 | Threshold selection |
| Historical test | 2025-03-01 to 2025-05-31 | Gate 2 evaluation |

## Gate 1: Conditional Predictability
**Criterion**: val_AUC >= 0.54 on at least 2 horizons

**Result**: {gate1_summary}

**Verdict**: {"PASS ✓" if gate1_ok else "FAIL ✗"}

## Gate 2: Causal Policy vs Oracle
**Criterion**: best causal policy EV >= 50% of oracle EV on test set

**Oracle test EV**: {oracle_ev:+.2f}/episode

**Result**: {gate2_summary}

**Verdict**: {"PASS ✓" if gate2_ok else "FAIL ✗"}

## RL Recommendation
{"**PROCEED** — Both gates pass. Sufficient predictability and policy headroom exist to justify building an RL agent on this signal." if rl_recommended else "**DO NOT PROCEED** — Insufficient predictability or policy headroom. OHLCV features on 1m regime flip are not sufficient. Next step: order flow / footprint data as additional feature families."}

## Key Caveats
- Models trained on OHLCV-derived features only; no order flow
- Bar execution mode (1s bar open fills) may overstate slightly vs tick execution
- Regime-capped labels assume exact flip-time exit; real exit has 5s delay
"""

    path = OUT_DIR / "final_report.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport saved -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, default=0,
                        help="Run only phase N (0=all)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    phase_map = {
        1: phase1_collect,
        2: phase2_labels,
        3: phase3_oracle,
        4: phase4_gate1,
        5: phase5_gate2,
        6: phase6_report,
    }

    if args.phase == 0:
        for fn in phase_map.values():
            fn()
    elif args.phase in phase_map:
        phase_map[args.phase]()
    else:
        print(f"Unknown phase: {args.phase}")
        return

    print(f"\nTotal elapsed: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
