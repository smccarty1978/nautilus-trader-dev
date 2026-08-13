# Contract Audit — top10_post_confirmation_mfe_monetization — Pass 01

**Date:** 2026-08-10 · **Verdict: CLEAR** · 0 critical · 0 blocking
**At time of pass:** 1 WARNING + 1 NOTE, both since resolved.

Scope: SPEC §6 deliverables, §7 classification reachability, §4 policy cap,
§1.2 stream labelling, §8 validation gates, §9 non-goals, C4/D/E. Causality is
out of scope — `lookahead-auditor` pass 1 BLOCKED on 1 CRITICAL, pass 2 PASS.

> Authored by the `contract-checker` agent and persisted by the main session,
> which has the Write tool the agent lacks. Table verbatim; remediation added after.

## Compliance table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| §6 core docs + JSON artifacts | PASS | SPEC, README, REPORT, `finalist_shortlist.json`, `validation_report.json`, `partition_manifest.json` all present with required content | — |
| §6 parquet + CSV mirrors | **WARNING** | only `policy_results` had a CSV sibling; seven others parquet-only, `giveback_recovery` JSON only | add mirrors or scope the parenthetical |
| §7 label F reachable and defensible | PASS | each of A–G tied to a concrete numeric rejection: P90 exit 0.6%, arm 1.0%, P80 worse, price-only ~0/negative, population reconciled so not G | — |
| Four trade-outcome labels reachable | PASS | all n>0: 822 / 1,359 / 2,350 / 174 | — |
| §4 policy cap ≤16, one buffer, one staircase | PASS | `POLICIES` = 15 incl. BASELINE; manifest shows one 0.25 ATR buffer and one 4-rung ladder; no grid construct in `engine.py` | REPORT header wording ambiguous — cosmetic |
| §1.2 stream labelling, never pooled | PASS | `DOMAIN` dict in `policies.py`; identical wording in README, REPORT, manifest, shortlist; no path sums or averages A and B | — |
| §8 fifteen numbered gates covered | PASS | twelve executed gates cover all fifteen requirements; 9+12 combined in `independent_replay_causal_fill`, 13–15 in `audit_gates` | — |
| §8 gate 12 logic | PASS | requires lint critical 0 and both agent verdicts in {CLEAR,PASS} with critical 0; reads JSON, never prose; correctly fail-closed | persist this file, re-run |
| §9 non-goals | PASS | entry params read frozen from the upstream artifact, thresholds imported from the frozen contract, no fit/train calls, stream B disclosed non-deployable | — |
| REPORT §6a correction record honesty | PASS | defect 1 fix verified at `engine.py` (`seg = slice(jb + 1, ...)`); defects 2–3 verified in `policies.py`; every REPORT number cross-checked against `results/policy_results.csv` to displayed precision | — |
| C4 selection seal / promotion | PASS | no promotion occurred (F); `finalists` is empty | — |
| D train/serve skew | N/A | no model trained or served; frozen score consumption only | — |
| E backtest config / fills | PASS | fills use the following-bar open, verified by a 240-trade independent replay with 0 mismatches; the one same-bar-close fallback at a truncated window boundary is disclosed and session-forced | carry the WARNING |

## Referred to lookahead-auditor

None beyond what pass 1 already referred.

## Blocking verdict

**CLEAR.** The manifest is present and every artifact defensible; both the four
trade-outcome labels and the seven A–G classification labels are reachable, and F
is correctly derived; the lookahead-auditor CRITICAL has a verified fix; §6a's
correction record is accurate against code and results; §9 non-goals hold. The
one WARNING is a completeness gap against an ambiguously scoped clause, not a
correctness defect.

---

## Remediation applied after this pass (main session, 2026-08-10)

- **CC-1 RESOLVED.** CSV mirrors written for all seven parquet deliverables, plus
  a flat tabular mirror of `giveback_recovery`. `results/` now carries nine CSVs.
- **CC-2 RESOLVED.** REPORT header reads "14 + baseline (15 total)"; SPEC §4
  heading notes "14 + baseline run" against the cap of 16.
- Separately, `lookahead-auditor` pass 2 raised two WARNINGs on `validate.py`,
  both since fixed: `score_causally_available` now checks **both** models rather
  than bullish only, and `crossing_uses_prior_true_observation_same_regime` now
  derives its check by a per-regime numpy scan instead of re-running build.py's
  polars shift expression — a shared bug can no longer pass a re-execution
  trivially. Re-run: all eleven data gates pass.
