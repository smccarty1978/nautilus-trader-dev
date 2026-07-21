"""Assembles the final manifest.json from all prior stage outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"


def main() -> None:
    summary = json.loads((RESULTS / "selected_trigger_summary.json").read_text(encoding="utf-8"))
    cutoffs = json.loads((WORK / "cutoffs.json").read_text(encoding="utf-8"))
    grid = pd.read_csv(RESULTS / "trigger_grid_results.csv")
    baseline_map = pd.read_csv(RESULTS / "baseline_mapping_attribution.csv")
    giveback = pd.read_csv(RESULTS / "winner_giveback_counts.csv")

    manifest = {
        "decision": summary["decision"], "selected_trigger": summary["selected_trigger"],
        "frozen_2025_cutoffs": cutoffs,
        "n_trigger_variants": int(grid["trigger"].nunique()),
        "dev_2025_economics": summary["dev_2025"], "test_2026_economics": summary["test_2026"],
        "signal_to_policy_gate": summary["signal_to_policy_gate"],
        "best_by_per_trade_2025": summary["best_by_per_trade_2025"],
        "best_by_pf_2025": summary["best_by_pf_2025"],
        "baseline_mapping_attribution": baseline_map.to_dict(orient="records"),
        "winner_giveback_counts": giveback.to_dict(orient="records"),
    }
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("manifest.json written")


if __name__ == "__main__":
    main()
