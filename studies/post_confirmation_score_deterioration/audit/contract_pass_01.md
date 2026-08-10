# Contract Audit — post_confirmation_score_deterioration — Pass 01

**Date:** 2026-08-10
**Scope:** C4, D, E, SPEC §7/§8/§9 (Deliverables Manifest, terminal labels, domain/completeness, validation gates)
**Verdict:** CLEAR — 0 critical. 1 completeness gap + 2 filename-drift warnings + 1 hygiene note, **all since remediated** (see foot of file).

Causality (A, B, C1–C3, F, G, H) is out of scope — `lookahead-auditor` returned
PASS, 0 critical / 0 warning (`audit/status.json`, `audit/pass_01.md`).

> Authored by the `contract-checker` agent and persisted by the main session,
> which has the Write tool the agent lacks. The table is verbatim; the
> remediation section was added afterwards.

## Compliance table

| Requirement | Verdict | Evidence | Smallest remediation |
|---|---|---|---|
| §7 manifest items 1–7, 9, 12–14 | PASS | `SPEC.md`, `README.md`, `REPORT.md`, `CHECKPOINT.md`, `population_reconciliation.json`, `phase0_probe.json` / `phase0_probe2.json` / `stream_b_coverage.json`, `post_confirm_paths.parquet` (present, gitignored per manifest note), `deterioration_event_table.json`, `runner_touch.json`, `stability.json`, `validation_report.json` all exist with the described contents; population counts match §3 exactly | — |
| §7 item 8 `landmark_features.json` | WARNING | Content ("Phase 2 landmark AUCs and medians by outcome") shipped as `phase0_gate1.json` — same schema, wrong filename | rename or emit under the manifest name |
| §7 item 10 `escalation_recovery.json` | **GAP** | No file, and no code path computed Phase 5's "how often was the escalation temporary" question — only first-firing economics | add a query over the panel: did `score_b` fall back below the fire threshold before terminal |
| §7 item 11 `divergence.json` | WARNING | Phase 3 divergence is computed (`events.py`) but its result is one row embedded in `deterioration_event_table.json`, not a standalone file | extract to the manifest name |
| §7 item 15 code hashes | NOTE | `build_panel.py` hashes `implementation/*.py` only (5 files); `analysis/*.py` and `validate.py` omitted | extend the glob |
| §7 item 16 audit trio | PASS on write | `lint.json` (0/0) and `status.json` (PASS, 0 critical) present; `contract_status.json` supplied by this pass | — |
| Terminal labels A–E reachable, mutually exclusive | PASS | SPEC §7 gives disjoint, evaluable conditions; no code hard-codes B. REPORT.md's B-vs-A/C/D/E disqualification is traceable: AUC 0.684→0.780 (`phase0_gate1.json`); 6.04% touch at t=120s/q=0.85 (`landmark_tradeoff.json`); `beats_random_95: false` at every point (`placebo.json`) | — |
| §8 domain/completeness | PASS | `session=="RTH"` filter; `YEARS=(2021..2025)`; population reconciled not assumed (gate 1 `matches: true`); stream A excluded structurally, never joined as a predictor; no new thresholds; exactly 5 horizons; 2025 non-OOS disclosed in REPORT §6 and README | — |
| Train/serve & §1.3 threshold non-transfer | PASS | No threshold invented; `events.py` uses only distribution-free constructions; `deterioration_event_table.json.not_applicable` lists the four excluded threshold events with reason; no percentile column referenced anywhere | — |
| C4 walk-forward / selection seals | NOT APPLICABLE | No model training, selection or promotion — a diagnostic query over a frozen upstream store | — |
| D train/serve skew | NOT APPLICABLE | No live-serving artifact; stream B read historically only | — |
| E backtest configuration | NOT APPLICABLE | No NT `BacktestEngine` run; offline panel study | — |
| §9 gates 1–9 | PASS structurally | `validate.py` implements all nine; gates 1–8 `passed: true`; gate 9 false only pending this pass's output | re-run `validate.py` after this file lands |

## Referred to lookahead-auditor

None.

## Blocking verdict

**CLEAR.** All nine §9 validation gates are correctly implemented and pass.
Domain/completeness, the C4/D/E scope, and the §1.3 threshold-non-transfer
handling are honoured in code, not merely in prose. Terminal label B is
defensible from the cited artifacts, and A/C/D/E are ruled out with traceable
evidence. The one real gap is manifest item 10, which is genuinely absent rather
than misnamed — real, but it does not threaten the conclusion, since the B-label
rests on the placebo null rather than on recovery framing.

---

## Remediation applied after this pass (main session, 2026-08-10)

- **Item 10 RESOLVED — and it changed the report.** `analysis/escalation_recovery.py`
  was written and run. The result was substantive rather than cosmetic: 58–78% of
  landmark flags are temporary, and **86–99% of flagged ≥2.5 ATR runners recover**
  before the trade ends. Added to REPORT.md as §5.3, where it independently
  reinforces the terminal label. The checker was right that this was a real gap.
- **Items 8 and 11 RESOLVED.** `landmark_features.json` and `divergence.json` are
  now written to their manifest names. The manifest was not amended to match the
  code; the code was made to match the manifest.
- **Hash note RESOLVED.** `build_panel.py` now hashes `analysis/*.py` as well as
  `implementation/*.py`.
