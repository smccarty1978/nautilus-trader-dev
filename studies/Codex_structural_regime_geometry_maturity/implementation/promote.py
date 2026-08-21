"""Verify the sealed decision surface before any study result can be promoted."""
from __future__ import annotations

import json
from pathlib import Path

from studies.Codex_structural_regime_geometry_maturity.implementation.contracts import verify_selection_seal, write_selection_seal

ROOT = Path(__file__).resolve().parents[3]
STUDY, OUT = ROOT / "studies/Codex_structural_regime_geometry_maturity", ROOT / "studies/Codex_structural_regime_geometry_maturity/results"
ARTIFACTS = ["phase0_contract.json", "collection_manifest.json", "models_manifest.json", "model_artifacts/SHORT_TOP25.joblib", "model_artifacts/SHORT_TOP25_PLUS_STRUCTURAL.joblib", "model_artifacts/LONG_TOP25.joblib", "model_artifacts/LONG_TOP25_PLUS_STRUCTURAL.joblib", "structural_checkpoints.parquet", "oos_scores.parquet", "oos_row_metrics.csv", "oos_timing_metrics.csv", "oos_deciles.csv", "oos_first_crossings.parquet", "oos_crossing_metrics.csv", "oos_family_attribution.csv", "validation_report.json", "summary.json", "../REPORT.md"]


def status_ok(path: Path) -> bool:
    if not path.is_file(): return False
    item = json.loads(path.read_text())
    return int(item.get("critical", item.get("blocking", 99))) == 0 and item.get("verdict") in {"PASS", "CLEAR"}


def phase0_ok(path: Path) -> bool:
    return path.is_file() and json.loads(path.read_text()).get("status") == "PASS"


def lint_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    item = json.loads(path.read_text())
    return int(item.get("critical", 99)) == 0 and int(item.get("warning", 99)) == 0


def promotion_status(*, verification: dict, report_hash: str | None, validation: dict,
                     phase0_pass: bool, lint_pass: bool, causal_pass: bool,
                     contract_pass: bool, terminal: str | None) -> str:
    return "PASS" if (verification["pass"] and report_hash is not None
                      and validation.get("status") == "PASS" and phase0_pass
                      and lint_pass and causal_pass and contract_pass
                      and terminal not in (None, "ABORT_CONTRACT_OR_CAUSAL_FAILURE")) else "BLOCKED"


def main() -> None:
    # `../REPORT.md` is intentionally part of the seal: the human conclusion is
    # authenticated alongside the model, metrics, and summary.
    report = STUDY / "REPORT.md"
    seal = write_selection_seal(OUT, ARTIFACTS)
    report_hash = None if not report.is_file() else __import__("hashlib").sha256(report.read_bytes()).hexdigest()
    verification = verify_selection_seal(OUT)
    validation = json.loads((OUT / "validation_report.json").read_text()) if (OUT / "validation_report.json").is_file() else {"status": "FAIL"}
    terminal = json.loads((OUT / "summary.json").read_text()).get("terminal_label") if (OUT / "summary.json").is_file() else None
    phase0_pass = phase0_ok(OUT / "phase0_contract.json")
    lint_pass = lint_ok(STUDY / "audit/lint.json")
    causal_pass, contract_pass = status_ok(STUDY / "audit/status.json"), status_ok(STUDY / "audit/contract_status.json")
    gate = {"status": promotion_status(verification=verification, report_hash=report_hash,
            validation=validation, phase0_pass=phase0_pass, lint_pass=lint_pass,
            causal_pass=causal_pass, contract_pass=contract_pass, terminal=terminal),
            "selection_seal_sha256": seal["seal_sha256"], "report_sha256": report_hash,
            "seal_verification": verification, "validation_status": validation.get("status"),
            "phase0_contract_pass": phase0_pass, "lint_pass": lint_pass,
            "causal_audit_pass": causal_pass, "contract_audit_pass": contract_pass,
            "terminal_label": terminal}
    (OUT / "promotion_gate.json").write_text(json.dumps(gate, indent=2))
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
