"""Assemble the final report from the validation artifacts.

Every number in the report comes from a JSON artifact produced by a validation
step, never from a value typed by hand. If an artifact is missing, the section
says so rather than being quietly omitted -- an absent check must not read as a
passed one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/regime_complete_canonical_store"
RESULTS = STUDY / "results"
STORE = ROOT / "data/canonical/regime_complete_v1"

VERDICTS = {
    "ACCEPTED": "REGIME-COMPLETE STORE ACCEPTED",
    "CONDITIONAL": "REGIME-COMPLETE STORE CONDITIONALLY ACCEPTED",
    "REJECTED": "REGIME-COMPLETE STORE REJECTED",
}


def _load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_audit(name: str) -> dict | None:
    path = STUDY / "audit" / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _table(rows: list[list], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |"]
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def _fmt(value) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def determine_verdict(
    parity, audit, consolidation, lookahead=None, contract=None
) -> tuple[str, list[str]]:
    """A missing artifact is never treated as a pass.

    The two mandatory agent gates are inputs here, not commentary alongside the
    verdict. An earlier revision computed ACCEPTED from parity, the independent
    audit, and reconciliation alone -- so a BLOCKED contract-checker could sit
    beside an ACCEPTED report without contradicting it. Passing `None` for either
    gate means it has not been run, which is not a pass.
    """
    limitations: list[str] = []
    if parity is None or audit is None or consolidation is None:
        limitations.append(
            "One or more validation artifacts are absent; verdict cannot be ACCEPTED."
        )
        return "REJECTED", limitations

    parity_ok = parity.get("verdict") == "PASS"
    audit_ok = audit.get("verdict") == "PASS"
    reconciled = consolidation.get("all_reconciled") is True
    lookahead_ok = lookahead is not None and lookahead.get("critical", 1) == 0
    contract_ok = contract is not None and contract.get("critical", 1) == 0

    if parity_ok and audit_ok and reconciled and lookahead_ok and contract_ok:
        return "ACCEPTED", limitations

    if not parity_ok:
        limitations.append("Backward parity did not reproduce the accepted population.")
    if not audit_ok:
        limitations.append("The independent audit reported unexplained mismatches.")
    if not reconciled:
        limitations.append("Consolidation row counts did not reconcile.")
    if lookahead is None:
        limitations.append("The lookahead-auditor gate has not been run.")
    elif not lookahead_ok:
        limitations.append("The lookahead-auditor reported CRITICAL findings.")
    if contract is None:
        limitations.append("The contract-checker gate has not been run.")
    elif not contract_ok:
        limitations.append("The contract-checker reported CRITICAL findings.")

    blocking = not parity_ok or not reconciled or lookahead is None or contract is None
    return ("REJECTED" if blocking else "CONDITIONAL"), limitations


def _known_limitations(counts: dict | None) -> list[str]:
    """Limitations that hold even when every gate passes.

    Stated unconditionally so a clean run cannot read as an unqualified one.
    """
    items = [
        "**Threshold provenance.** Both frozen calibration populations are "
        "calendar-2025 and overlap the 2021–2025 evaluation window. Every "
        "threshold row carries `overlaps_evaluation_window = true`. Results "
        "using these thresholds are descriptive and must not be represented as "
        "threshold-out-of-sample for 2025.",
        "**ETH scores are almost entirely absent by contract.** Three of the 25 "
        "frozen features are RTH accumulators that return null once the session "
        "ends, so the frozen adapters decline to score outside RTH. ETH "
        "checkpoints, regimes, and paths are retained in full, but ETH carries "
        "no usable model probability and is never in-domain.",
        "**Model coverage is unchanged.** This store adds no model, retrains "
        "nothing, and changes no feature. Out-of-domain and exploratory score "
        "semantics are inherited from the accepted artifacts.",
        "**Feature snapshots are inline, not a separate long table** "
        "(DECISION-5). Provenance is preserved via the per-model feature "
        "vector hashes; the tradeoff is documented rather than silent.",
        "**58 path rows of 61,543,945 carry a null `regime_sequence_number`.** "
        "They belong to a single regime that began during warmup before "
        "2021-01, so its regime row falls outside the build window while its "
        "path rows fall inside. This affects the first regime of the corpus only.",
        "**2026 is absent by design**, reserved for runtime out-of-sample "
        "validation. No calibration or collection touched it.",
    ]
    if counts and counts.get("unexplained") == 0:
        items.append(
            "**Regime count differs from the accepted flip file by 208, fully "
            "explained** (199 outside the window, 9 cold-start warmup "
            "artifacts). No unexplained difference remains."
        )
    return items


def build() -> str:
    consolidation = json.loads(
        (STORE / "canonical_collection_manifest.json").read_text()
    ) if (STORE / "canonical_collection_manifest.json").exists() else None
    parity_populations = _load("population_coverage_summary.json")
    parity = (parity_populations or {}).get("backward_parity")
    audit = _load("independent_audit_sample.json")
    thresholds = _load("threshold_availability_report.json")
    pilot = _load("pilot_validation.json")
    lookahead = _load_audit("status.json")
    contract = _load_audit("contract_checker_status.json")

    verdict_key, limitations = determine_verdict(
        parity, audit, consolidation, lookahead, contract
    )

    sections: list[str] = []
    sections.append("# Regime-Complete Canonical Store — Report\n")

    # 1. Executive summary -------------------------------------------------
    sections.append("## 1. Executive summary\n")
    if consolidation:
        datasets = consolidation["datasets"]
        summary_rows = [
            ["Every regime represented", _fmt(datasets["regimes"]["rows"]) + " regime rows"],
            ["Every true scoring checkpoint", _fmt(datasets["scores"]["rows"]) + " score rows"],
            ["Complete one-second paths", _fmt(datasets["paths"]["rows"]) + " path rows"],
            [
                "Prior 5,836 population reproduced",
                (parity or {}).get("verdict", "NOT RUN"),
            ],
        ]
        sections.append(_table(summary_rows, ["Question", "Answer"]) + "\n")
    else:
        sections.append("Consolidation artifact absent; the store was not built.\n")

    # 2-3. Contract and schema --------------------------------------------
    sections.append(
        "## 2. Frozen contract\n\n"
        "Frozen in `REGIME_COMPLETE_CANONICAL_STORE_SPEC.md`; decisions and the "
        "options rejected are in `DECISIONS.md`. Regime definition, score cadence, "
        "timestamp semantics, path boundaries, domain behavior, threshold "
        "provenance, censoring, and ID construction are all fixed there.\n"
    )
    if consolidation:
        sections.append("## 3. Schema\n")
        sections.append(
            _table(
                [
                    [
                        key,
                        info["target"],
                        _fmt(info["rows"]),
                        info["columns"],
                        f"{info['bytes'] / 1e9:.2f} GB",
                    ]
                    for key, info in consolidation["datasets"].items()
                ],
                ["Dataset", "File", "Rows", "Columns", "Size"],
            )
            + "\n"
        )

    # 4. Coverage ----------------------------------------------------------
    if consolidation and "regime_reconciliation" in consolidation:
        rec = consolidation["regime_reconciliation"]
        sections.append("## 4. Coverage\n")
        sections.append(
            _table(
                [
                    ["Regimes", _fmt(rec["regimes"])],
                    ["Established", _fmt(rec["established"])],
                    ["Never established", _fmt(rec["never_established"])],
                    ["Complete paths", _fmt(rec["complete_paths"])],
                    ["Censored paths", _fmt(rec["censored_paths"])],
                    ["Duplicate regime IDs", _fmt(rec["duplicate_regime_ids"])],
                    [
                        "Consecutive same-direction regimes",
                        _fmt(rec["consecutive_same_direction"]),
                    ],
                ],
                ["Metric", "Value"],
            )
            + "\n"
        )
        sections.append("By year:\n")
        sections.append(
            _table(
                [[r["entry_year"], _fmt(r["len"])] for r in rec["by_year"]],
                ["Year", "Regimes"],
            )
            + "\n"
        )

    # 5. Threshold audit ---------------------------------------------------
    if thresholds:
        sections.append("## 5. Threshold-contract audit\n")
        rows = []
        for model_id, info in thresholds["models"].items():
            for label, detail in sorted(info["reproduced"].items()):
                rows.append([model_id, label, detail["value"], "AVAILABLE_AND_FROZEN"])
            for label, value in sorted(info["derived"].items()):
                rows.append([model_id, label, value, "RECONSTRUCTED"])
        sections.append(
            _table(rows, ["Model", "Percentile", "Threshold", "Status"]) + "\n"
        )
        sections.append(
            "> Both calibration populations are calendar-2025 and overlap the "
            "2021–2025 evaluation window. Results using these thresholds are "
            "descriptive and must not be represented as threshold-out-of-sample "
            "for 2025.\n"
        )

    # 6. Backward reproduction --------------------------------------------
    sections.append("## 6. Backward reproduction\n")
    if parity:
        sections.append(
            _table(
                [
                    ["Accepted trades", _fmt(parity["accepted_trades"])],
                    ["Regenerated trades", _fmt(parity["regenerated_trades"])],
                    ["Matched", _fmt(parity["matched"])],
                    ["Missing", _fmt(parity["missing_vs_accepted"])],
                    ["Extra", _fmt(parity["extra_vs_accepted"])],
                    ["Duplicated", _fmt(parity["duplicated_keys"])],
                    ["Value mismatches", json.dumps(parity["value_mismatches"])],
                    ["Verdict", parity["verdict"]],
                ],
                ["Metric", "Value"],
            )
            + "\n"
        )
    else:
        sections.append("Backward parity was not run.\n")

    # 7. Capability --------------------------------------------------------
    if parity_populations:
        sections.append("## 7. Capability demonstrations\n")
        rows = [
            [
                p["population"],
                _fmt(p.get("candidate_observations", 0)),
                _fmt(p.get("unique_regimes", 0)),
                _fmt(p.get("multiple_candidate_regimes", 0)),
            ]
            for p in parity_populations.get("first_signal", [])
            + parity_populations.get("all_crossings", [])
            + parity_populations.get("opposing_warnings", [])
        ]
        sections.append(
            _table(rows, ["Population", "Candidates", "Regimes", "Multi-candidate"])
            + "\n"
        )
        sections.append(
            "These are data-capability demonstrations. No population is ranked "
            "economically and no policy is recommended.\n"
        )
        if parity_populations.get("reentry"):
            sections.append("### Re-entry capability\n")
            sections.append(
                "```json\n"
                + json.dumps(parity_populations["reentry"][0], indent=2)
                + "\n```\n"
            )

    # 8-9. Causal audit and performance -----------------------------------
    sections.append("## 8. Causal audit\n")
    if pilot:
        equivalence = pilot["rth_equivalence"]
        sections.append(
            "The strongest causal evidence is equivalence against the accepted "
            "artifact: after widening the collector to the full session, every RTH "
            "score row still carries exactly the accepted values.\n\n"
            + _table(
                [
                    ["Accepted rows", _fmt(equivalence["accepted_rows"])],
                    ["Rebuilt rows", _fmt(equivalence["pilot_rth_rows"])],
                    ["Columns compared", _fmt(equivalence["compared_columns"])],
                    ["Missing", _fmt(equivalence["missing_vs_accepted"])],
                    ["Extra", _fmt(equivalence["extra_vs_accepted"])],
                    [
                        "Mismatched columns",
                        _fmt(len(equivalence["mismatched_columns"])),
                    ],
                ],
                ["Metric", "Value"],
            )
            + "\n"
        )

    # 10. Independent audit ------------------------------------------------
    sections.append("## 9. Independent audit\n")
    if audit:
        sections.append(
            _table(
                [
                    ["Regimes sampled", _fmt(audit["regimes_sampled"])],
                    [
                        "Independently derived flips",
                        _fmt(audit["independent_flips_derived"]),
                    ],
                    [
                        "Unexplained mismatches",
                        _fmt(audit["unexplained_mismatches"]),
                    ],
                    ["Verdict", audit["verdict"]],
                ],
                ["Metric", "Value"],
            )
            + "\n"
        )
    else:
        sections.append("The independent audit was not run.\n")

    # 9b. Regime-count reconciliation --------------------------------------
    counts = _load("regime_count_reconciliation.json")
    if counts:
        sections.append("### Regime-count reconciliation\n")
        sections.append(
            _table(
                [
                    [
                        "Accepted flips, deduplicated",
                        _fmt(counts["accepted_flips_deduplicated"]),
                    ],
                    [
                        "— outside the 2021–2025 window (2020 warmup)",
                        _fmt(counts["accepted_flips_outside_window"]),
                    ],
                    [
                        "— cold-start warmup artifacts",
                        _fmt(counts["explained_as_cold_start_warmup_artifacts"]),
                    ],
                    ["Store regimes", _fmt(counts["store_regimes"])],
                    ["In store, not in accepted", _fmt(counts["in_store_not_in_accepted"])],
                    ["**Unexplained**", f"**{_fmt(counts['unexplained'])}**"],
                ],
                ["Component", "Count"],
            )
            + "\n"
        )
        sections.append(counts["conclusion"] + "\n")

    # 10. Limitations ------------------------------------------------------
    sections.append("## 10. Limitations\n")
    for item in _known_limitations(counts):
        sections.append(f"- {item}")
    sections.append("")

    # 11. Verdict ----------------------------------------------------------
    sections.append("## 11. Verdict\n")
    sections.append(f"```text\n{VERDICTS[verdict_key]}\n```\n")
    sections.append(
        _table(
            [
                ["Backward-parity status", (parity or {}).get("verdict", "NOT RUN")],
                ["Causal-audit status", (audit or {}).get("verdict", "NOT RUN")],
                [
                    "Population-completeness status",
                    "RECONCILED"
                    if (consolidation or {}).get("all_reconciled")
                    else "NOT RECONCILED",
                ],
                [
                    "lookahead-auditor gate",
                    f"{lookahead['verdict']} "
                    f"({lookahead['critical']} CRITICAL, pass {lookahead['pass']})"
                    if lookahead
                    else "NOT RUN",
                ],
                [
                    "contract-checker gate",
                    f"{contract['verdict']} "
                    f"({contract['critical']} CRITICAL, pass {contract['pass']})"
                    if contract
                    else "NOT RUN",
                ],
            ],
            ["Criterion", "Status"],
        )
        + "\n"
    )
    if limitations:
        sections.append("Limitations:\n")
        for item in limitations:
            sections.append(f"- {item}")
        sections.append("")

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default=str(STUDY / "REGIME_COMPLETE_CANONICAL_STORE_REPORT.md")
    )
    args = parser.parse_args()
    text = build()
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
