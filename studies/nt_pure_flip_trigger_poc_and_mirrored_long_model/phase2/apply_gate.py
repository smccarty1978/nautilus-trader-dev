"""Applies the Phase 2 proof-of-concept gate (SPEC.md / brief verbatim)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402


def main() -> None:
    variant_summary = pd.read_csv(C.PHASE2 / "variant_summary.csv")
    regime_parity = pd.read_csv(C.PHASE2 / "regime_runtime_parity.csv")
    trigger_parity = pd.read_csv(C.PHASE2 / "trigger_runtime_parity.csv")
    atr_parity = pd.read_csv(C.PHASE2 / "score_runtime_parity.csv")
    exit_summary = pd.read_csv(C.PHASE2 / "exit_reason_summary.csv")

    infra_ok = (
        bool(regime_parity["exact_match"].all())
        and bool(trigger_parity["exact_match"].all())
        and bool(atr_parity["atr_exact_match"].all())
        and not bool(atr_parity["any_unmatched_rows"].any())
    )

    econ_checks = {}
    any_variant_passes_econ = False
    for _, row in variant_summary.iterrows():
        label = row["variant"]
        trades = row.get("trades", 0)
        if pd.isna(trades) or trades == 0:
            econ_checks[label] = {"trades": 0, "passes": False}
            continue
        net_positive = row["net_pnl"] > 0
        pf_ok = row["profit_factor"] > 1.05
        n_trades_ok = trades >= 30
        pct_flip_ok = row["pct_reached_bearish_flip_before_stop"] >= 0.55
        opp = exit_summary[(exit_summary.variant == label) & (exit_summary.exit_reason == "opposing_flip_exit")]
        opp_positive = bool((opp["net_pnl"] > 0).all()) if len(opp) else False
        # not-one-outlier-driven: largest single trade's |pnl| should not
        # exceed the variant's own total |net_pnl| (i.e. removing it
        # wouldn't flip the sign) -- documented, simple check.
        largest_abs = max(abs(row.get("largest_winner", 0) or 0), abs(row.get("largest_loser", 0) or 0))
        not_outlier_driven = abs(row["net_pnl"]) > largest_abs if row["net_pnl"] != 0 else False

        passes = (net_positive or pf_ok) and n_trades_ok and pct_flip_ok and opp_positive and not_outlier_driven
        econ_checks[label] = {
            "trades": int(trades), "net_positive": bool(net_positive), "pf_ok": bool(pf_ok),
            "n_trades_ok": bool(n_trades_ok), "pct_flip_ok": bool(pct_flip_ok),
            "opposing_flip_bucket_positive": opp_positive, "not_outlier_driven": not_outlier_driven,
            "passes": bool(passes),
        }
        any_variant_passes_econ = any_variant_passes_econ or passes

    if not infra_ok:
        decision = "NT_POC_FAILS_CAUSAL_PARITY"
    elif not any_variant_passes_econ:
        decision = "NT_POC_FAILS_ECONOMICS"
    else:
        decision = "NT_POC_PROMISING_LONG_MODEL_NOT_RUN"

    manifest = {
        "phase2_nt_poc_decision": decision,
        "infrastructure_gate_pass": infra_ok,
        "economic_gate_checks": econ_checks,
        "any_variant_passes_econ_gate": any_variant_passes_econ,
    }
    (C.PHASE2 / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("PHASE 2 DECISION:", decision)
    print(json.dumps(econ_checks, indent=2, default=str))


if __name__ == "__main__":
    main()
