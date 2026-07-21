"""Assembles the final manifest.json from all prior stage outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"


def main() -> None:
    phase0 = json.loads((RESULTS / "phase0_manifest.json").read_text(encoding="utf-8"))
    first_elig = pd.read_csv(RESULTS / "first_eligible_surface_summary.csv")
    feat_sep = pd.read_csv(RESULTS / "gate_feature_separation.csv")
    model_diag = pd.read_csv(RESULTS / "optional_model_diagnostics.csv")

    population_impact = (
        first_elig[["gate", "year", "rows", "regimes"]]
        .pivot(index="year", columns="gate", values="regimes")
        .to_dict()
    )

    manifest = {
        "gates": phase0["gates"], "timeout_s": phase0["timeout_s"],
        "years": [2021, 2022, 2023, 2024, 2025, 2026],
        "population_impact_regimes_by_gate_year": population_impact,
        "label_quality_first_eligible_summary": first_elig.to_dict(orient="records"),
        "feature_separation_family_summary": feat_sep.to_dict(orient="records"),
        "optional_model_diagnostics": model_diag.to_dict(orient="records"),
        "phase0_manifest_ref": "results/phase0_manifest.json",
    }
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("manifest.json written")


if __name__ == "__main__":
    main()
