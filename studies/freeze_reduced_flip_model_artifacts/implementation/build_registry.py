"""Build MODEL_REGISTRY.md + results/model_registry.json + final decision.

All metrics are recomputed from the FROZEN score_reference_*.parquet artifacts
themselves (not copied from source studies), so the registry describes what the
frozen artifacts actually do. 2026 is used for reporting only - no model is
selected or altered here.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY.parents[1]
ART, RESULTS = STUDY / "artifacts", STUDY / "results"

TARGETS = {"short": "bearish_regime_flip_within_300s",
           "long": "bullish_regime_flip_within_300s"}

NEXT_USE = {
    "short_bearish_flip_top25_current_reference":
        "NT live-scoring parity (short) - already bound by "
        "nt_reduced_f3_top25_population_parity_smoke; PROVISIONAL until that smoke reports",
    "short_bearish_flip_top100_ref": "archival only (short reduction lineage reference)",
    "long_bullish_flip_top25":
        "NT live-scoring parity (long) + entry-trigger study + exit-warning study",
    "long_bullish_flip_top50": "archival only (long reduction lineage comparison)",
    "long_bullish_flip_top100": "archival only (long reduction reference)",
}


def decile_flip(y, p):
    d = pd.DataFrame({"y": y, "p": p})
    d["dec"] = pd.qcut(d["p"].rank(method="first"), 10, labels=False)
    return float(d.groupby("dec")["y"].mean().loc[9])


def main() -> None:
    inv = pd.read_csv(RESULTS / "artifact_inventory.csv")
    par = pd.read_csv(RESULTS / "parity_checks.csv")
    onx = pd.read_csv(RESULTS / "onnx_export_report.csv").set_index("model_id")

    rows = []
    for r in inv.itertuples():
        mid = r.model_id
        man = json.load(open(ART / mid / "manifest.json"))
        tgt = TARGETS[man["direction"]]
        met = {}
        for split in ("2025", "2026"):
            df = pd.read_parquet(ART / mid / f"score_reference_{split}.parquet")
            y, p = df[tgt].astype(int).to_numpy(), df["score"].to_numpy()
            met[f"{split}_auc"] = round(float(roc_auc_score(y, p)), 5)
            met[f"{split}_top_decile_flip"] = round(decile_flip(y, p), 5)
        mp = par[par.model_id == mid]
        rows.append({
            "model_id": mid, "status": man["status"], "provenance": man["provenance"],
            "path": r.path, "target": tgt, "direction": man["direction"],
            "n_features": man["n_raw_features"], "n_model_columns": man["n_model_columns"],
            "model_type": r.model_type, "model_class": man["model_class"],
            "selected_metric": man["selected_metric"], **met,
            "joblib_parity_status": "PASS" if (mp["status"] == "PASS").all() else "FAIL",
            "n_parity_checks": int(len(mp)),
            "onnx_status": onx.loc[mid, "onnx_status"],
            "onnx_max_abs_diff": (float(onx.loc[mid, "max_abs_diff"])
                                  if "max_abs_diff" in onx.columns
                                  and pd.notna(onx.loc[mid, "max_abs_diff"]) else None),
            "threshold_status": r.threshold_status,
            "model_artifact_sha256": man["model_artifact_sha256"],
            "feature_order_sha256": man["feature_order_sha256"],
            "recommended_next_use": NEXT_USE[mid],
        })
    reg = pd.DataFrame(rows)
    (RESULTS / "model_registry.json").write_text(
        json.dumps({"models": rows, "generated_from": "frozen score_reference_*.parquet"},
                   indent=2), encoding="utf-8")

    all_joblib = (reg["joblib_parity_status"] == "PASS").all()
    n_provisional = int((reg["status"] == "PROVISIONAL").sum())
    provisional = n_provisional > 0
    onnx_fail = reg["onnx_status"].isin(["FAIL", "ONNX_NOT_ATTEMPTED_DEPENDENCY_MISSING"]).any()

    if not all_joblib:
        decision = "MODEL_FREEZE_BLOCKED_PARITY_FAILED"
    elif provisional:
        decision = "MODEL_FREEZE_COMPLETE_WITH_PROVISIONAL_SHORT"
    elif onnx_fail:
        decision = "MODEL_FREEZE_PARTIAL_ONNX_FAILED"
    else:
        decision = "MODEL_FREEZE_COMPLETE"

    (RESULTS / "final_decision.json").write_text(json.dumps({
        "study": "freeze_reduced_flip_model_artifacts",
        "decision": decision,
        "decision_rationale":
            "Every joblib artifact passed parity (source of truth intact) and the "
            "registry is complete, so the freeze itself succeeded. The label reflects "
            "the PROVISIONAL short-side model, which is the materially limiting caveat "
            "for downstream use: its source manifest carries status 'candidate' and the "
            "NT parity smoke consuming it has published no STUDY_REPORT. "
            "MODEL_FREEZE_PARTIAL_ONNX_FAILED also technically applies (2 of 5 ONNX "
            "exports failed) but is subordinate - the brief defines ONNX as a secondary "
            "artifact that must not block, and joblib remains the source of truth.",
        "secondary_qualifier": "MODEL_FREEZE_PARTIAL_ONNX_FAILED (2/5 ONNX exports failed; "
                               "both are GBT, both non-blocking)",
        "n_models_frozen": int(len(reg)),
        "n_final": int((reg["status"] == "FINAL").sum()),
        "n_provisional": n_provisional,
        "source_of_truth_format": "joblib (sklearn estimator/Pipeline)",
        "all_joblib_parity_pass": bool(all_joblib),
        "total_parity_checks": int(len(par)),
        "parity_checks_passed": int((par["status"] == "PASS").sum()),
        "onnx_pass": reg[reg.onnx_status.isin(["PASS", "PASS_RELAXED"])]["model_id"].tolist(),
        "onnx_fail": reg[reg.onnx_status == "FAIL"]["model_id"].tolist(),
        "models": reg[["model_id", "status", "model_type", "2025_auc", "2026_auc",
                       "joblib_parity_status", "onnx_status", "threshold_status"]
                      ].to_dict(orient="records"),
    }, indent=2), encoding="utf-8")

    # ---------------- MODEL_REGISTRY.md ----------------
    hdr = ("| model_id | status | dir | n_feat | type | 2025 AUC | 2026 AUC | 2025 top-dec | "
           "2026 top-dec | joblib | ONNX | thresholds | next use |")
    sep = "|" + "---|" * 13
    lines = [
        "# Model Registry — Reduced Pure-Flip Models",
        "",
        f"**Decision: `{decision}`** · source of truth: **joblib** · "
        f"{len(reg)} models · {int((par['status']=='PASS').sum())}/{len(par)} parity checks PASS",
        "",
        "> **Loading is TRUSTED-LOCAL-ONLY.** `joblib`/`pickle` executes arbitrary code on "
        "load. Load these files only from this repository. Never load a model artifact "
        "received from an untrusted source.",
        "", hdr, sep,
    ]
    for r in reg.to_dict(orient="records"):
        lines.append(
            f"| `{r['model_id']}` | **{r['status']}** | {r['direction']} | "
            f"{r['n_features']} | {r['model_type']} | {r['2025_auc']} | {r['2026_auc']} | "
            f"{r['2025_top_decile_flip']} | {r['2026_top_decile_flip']} | "
            f"{r['joblib_parity_status']} | {r['onnx_status']} | {r['threshold_status']} | "
            f"{r['recommended_next_use']} |")
    lines += [
        "",
        "## Recommended next use — by task",
        "",
        "| Task | Model |",
        "|---|---|",
        "| Short NT live-scoring parity | `short_bearish_flip_top25_current_reference` "
        "(**PROVISIONAL** — already bound by the NT smoke) |",
        "| Long NT live-scoring parity | `long_bullish_flip_top25` |",
        "| Entry-trigger study | `long_bullish_flip_top25` (long counter-regime entry timing) |",
        "| Exit-warning study | `long_bullish_flip_top25` (short exit warning) |",
        "| Archival / lineage only | `long_bullish_flip_top50`, `long_bullish_flip_top100`, "
        "`short_bearish_flip_top100_ref` |",
        "",
        "## Provenance classes",
        "",
        "- **COPIED_EXISTING_FITTED_ARTIFACT** — a fitted model already existed; byte-copied, "
        "recorded sha256 re-verified, reloaded from disk and proven to reproduce the source "
        "study's own published metrics.",
        "- **RECONSTRUCTED_NO_FITTED_ARTIFACT_EXISTED** — no fitted object was ever persisted. "
        "The exact original fit path was re-run and the refit reproduces the source study's "
        "stored per-row predictions **bit-identically (max_abs_diff = 0.0)**.",
        "",
        "## What these models are not",
        "",
        "Every model here predicts **regime-flip probability, not trade PnL**. Regime-level "
        "AUC is ~0.50 (chance) for the long family — the signal is *within-regime timing*, "
        "not regime selection. No economics, stops, or NT execution have validated any of them.",
        "",
        "## Missing by design",
        "",
        "- **Short-side TOP50 does not exist.** The short reduction ladder is "
        "25/40/60/80/100/150/250; there is no 50 rung. TOP100 serves as the short lineage "
        "reference. Recorded, not silently skipped.",
    ]
    (STUDY / "MODEL_REGISTRY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(reg[["model_id", "status", "2025_auc", "2026_auc", "2025_top_decile_flip",
               "2026_top_decile_flip", "joblib_parity_status", "onnx_status",
               "threshold_status"]].to_string(index=False))
    print(f"\nDECISION: {decision}")


if __name__ == "__main__":
    main()
