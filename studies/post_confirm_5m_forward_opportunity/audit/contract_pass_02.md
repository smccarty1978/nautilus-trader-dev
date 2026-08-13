# Contract-checker — Pass 2 (completion)

Scope: deliverables/manifest/seal completeness, terminal-label reachability,
C4/D/E (re-confirmed N/A — `implementation/` contains only `lineage.py`,
`join.py`, `analysis.py`, `validate.py`, no model/walk-forward/simulation).

## Adjudication of all 6 pass-1 findings

| # | Pass-1 finding | Adjudication | Evidence |
|---|---|---|---|
| 1 | C5 evaluation-order contradiction | **FIXED** | SPEC.md states a single order (C1→C3→C2→C4→C5); `validate.py::determine_verdict` implements it faithfully. |
| 2/3 | Manifest items 17/18 missing column lists | **FIXED** | Explicit long-format column lists added; `primary_table.csv`/`opportunity_capture_summary.csv` headers match. |
| 4 | Phase 11/12 `mfe_bucket` name collision | **FIXED** | Phase 12 renamed to `confirm_mfe_bucket`; Phase 11 explicitly disclaims aliasing; `validate.py`'s `CONFIRMATION_TIME_ONLY_COLS` contains `confirm_mfe_bucket`, not `mfe_bucket`. |
| 5 | Phase 8 audit-scope coverage | **Initially NOT fixed, now FIXED in this pass.** §3.1 item 9 claimed Phase 8 was in lookahead-auditor's scope, but §9's audit-plan text still listed Phase 8 among the exempted "pure reads" — a self-contradiction the earlier adjudication note missed. Corrected: §9 now excludes Phase 8 from the exempted list and explicitly names it as in-scope, matching §3.1 item 9. |
| 6 | Unnamed gates for stop conditions 4-5 | **FIXED** | Both stop conditions reference named gates (V-LABEL, V-MATCH); `validate.py` implements both, both pass. |

## New findings this pass

None (0 of the 3-per-pass cap used).

## Deliverables Manifest (§7) vs. actual output — all PASS

- All 21 `results/*` artifacts exist; `README.md`/`REPORT.md` present.
- CSV headers match declared columns (spot-checked: `transition_matrix.csv`,
  `landmark_attrition.csv`, `primary_table.csv`, `adverse_path.csv`,
  `mfe_quality_buckets.csv`).
- `partition_manifest.json` has input paths+rows, code hash, seed, frozen
  bucket edges.
- 9 audit gates (V1_V2, V_ANCHOR, V_CAUSAL, V_NOFUTURE, V_LABEL, V_SURVIVAL,
  V_MATCH, V_SEALED, V_RACE) all named per §3.1 and all ran;
  `validation_report.json` shows `n_failed: 0`.
- Terminal verdict `C3_EXPLAINED_BY_CONFIRMATION_QUALITY` is a declared §6
  label.
- Phase 0 correction (629/4,027, not the brief's 632/4,024) fully propagated
  into `lineage_reconciliation.json`, `transition_matrix.csv`, and
  `validate.py`'s constants.
- REPORT.md discloses Phase 12's cell sparsity (189/2,614 populated at
  +300s) honestly, as a data property, and does not overclaim the
  capture-curve timing-gap finding (explicitly states the 50%-timing gap is
  zero, not supportive of C1).
- `audit/run_status.json` shows a real bounded run, exit_code 0.

## Not independently verified by this agent (no Bash tool)

- `results/*.parquet`/`*.csv` not committed to git — orchestrating session
  confirmed via `git status` before commit (see below).

## Blocking verdict

**CLEAR**, after this pass's fix to finding #5's residual self-contradiction
(§9 vs §3.1 item 9). Five of six pass-1 findings were already correctly
fixed with direct evidence; the sixth is now fixed in this pass. No new
findings raised. Manifest, gate list, verdict-label reachability, Phase 0
numeric correction, and REPORT.md disclosures all check out clean against
direct file evidence.
