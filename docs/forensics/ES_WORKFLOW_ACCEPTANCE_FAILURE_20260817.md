# Forensic Record — ES Workflow Acceptance Test, 2026-08-17

**Verdict: `WORKFLOW_ACCEPTANCE_FAIL`**

This is the preserved evidence of the **first** workflow acceptance attempt, which an
independent Red Team failed. Everything referenced here is retained **as it was at the
moment of failure**. Nothing in this record is to be regenerated, corrected, backfilled,
or made to conform to the repaired workflow. It exists so a later reader can tell what
the controls actually permitted before remediation.

Remediation of the shared layers is tracked in
[`WORKFLOW_HARDENING_REMEDIATION_REPORT.md`](../../WORKFLOW_HARDENING_REMEDIATION_REPORT.md).

---

## 1. Identity

| Field | Value |
| --- | --- |
| Study id | `es_wick_imbalance_exploratory` |
| Study path | `studies/es_wick_imbalance_exploratory` |
| Study type | `flip_prediction` (canonical) |
| Risk tier | 2 |
| Instrument | ES / XCME |
| Strategy | `strategies.flip_prediction_collector.FlipPredictionCollector` |
| Declared feature set | `['latest_1m_wick_imbalance']` (1 feature) |
| Feature list SHA-256 | `f5cddfd93e1bda3b8ff3db0524413c3d8f1fd3fca62490806c3aeb640cf8aa20` |
| `study.yaml` spec SHA-256 | `7151bc7640ebb98526b28d07b673317aa6009975b142e277b0851d572e3eeb08` |

## 2. Repository state at time of failure

| Field | Value |
| --- | --- |
| Branch | `study/Codex_clean_maturity_flip_rolling_5m_productivity` |
| HEAD commit | `b367c58182effd57fd21314707bd3ab97f25e4cc` (2026-08-17 08:49:42 -0500) |
| Working tree | dirty — one untracked run directory, `runs/20260817_135158_es_wick_imbalance_exploratory_day/` |
| Commit that introduced the wick feature | `39a4296fed4ac4320471efb0926a34d9d43c4d7e` (2026-08-17 08:25:52 -0500) |

## 3. Execution composite

The study was sealed and audited against a **single** execution composite:

```
5232e5cd840825ffb22665127e155584024a94a494aa419355cf11ccc0be738e
```

recorded identically in `audit/execution_manifest.json`, `audit/status.json`,
`audit/contract_status.json`, `artifacts/preexec_audit_seal.json`, and in the
`run_manifest.json` of every completed run.

**The composite covered 53 files and was reported at `coverage_pct: 100.0`.** It omitted
repo-local Python modules that provably execute — see §6, finding A1.

## 4. Audit and seal artifact hashes (SHA-256, first 16 hex)

| Artifact | SHA-256 (16) |
| --- | --- |
| `audit/status.json` | `4952a1faad3cc1ce` |
| `audit/contract_status.json` | `a9929ce43148ffbe` |
| `audit/pass_01.md` | `cc0537f4a6e2c3c8` |
| `audit/contract_pass_01.md` | `5f6a0c419dd15ed9` |
| `audit/execution_manifest.json` | `2502780b98b3eeae` |
| `audit/preflight.json` | `ebff8cf1bf9650f9` |
| `audit/failure_packet.json` | `b96d9dad0d5a15f0` |
| `audit/lint.json` | `ee891240bf4b8975` |
| `audit/schema_check.json` | `e5ce268011ee864c` |
| `artifacts/preexec_audit_seal.json` | `5c2230f3a1047d2a` |
| `artifacts/phase0_source_manifest.json` | `5dc7efc76b671224` |
| `compiled_study.json` | `eee0c68214420efe` |

Seal id: `preexec_seal_es_wick_imbalance_exploratory_5232e5cd840825ff`, `seal_status: LOCKED`.

Both audit statuses declare `pass: 1`, `verdict: CLEAR`, `critical/blocking: 0`,
`warning: 0`, `audit_provenance_version: 2`, and **`transcript_sha256: null`**.
The declared reviewers are the role strings `lookahead-auditor` and `contract-checker`.

## 5. Run inventory

Ten run directories under `runs/`, all `*_es_wick_imbalance_exploratory_day`:

| Run id | `run_manifest.status` | `status.json` | Collection outputs |
| --- | --- | --- | --- |
| `20260817_125134_…` | RUNNING | *(absent)* | none |
| `20260817_125237_…` | RUNNING | *(absent)* | none |
| `20260817_125254_…` | COMPLETED | SUCCESS | candidates + observations (**1748 rows, wick 100 % NULL**) |
| `20260817_125629_…` | COMPLETED | SUCCESS | candidates + observations (1748 rows, wick populated) |
| `20260817_131940_…` | RUNNING | *(absent)* | none |
| `20260817_132452_…` | RUNNING | *(absent)* | none |
| `20260817_133122_…` | COMPLETED | SUCCESS | candidates + observations (2233 rows, 2024-09-04) |
| `20260817_133706_…` | RUNNING | *(absent)* | none |
| `20260817_134324_…` | RUNNING | *(absent)* | none |
| `20260817_135158_…` | RUNNING | *(absent)* | none |

Six of ten runs terminated without ever reaching a terminal status.

The 2024-09-04 run emitted candidates spanning **08:30:00 to 14:52:00 America/Chicago**;
`observations.parquet` has 2233 rows with **zero null `flip_ts`** — no candidate was
censored, and none was recorded as unresolved.

## 6. Findings preserved by this record

Each was independently reproduced against this fixture before any remediation.

| ID | Finding | Primary evidence in this fixture |
| --- | --- | --- |
| A1 | Sealed execution closure omits executing repo-local modules | `combined_files` (53) contains `features/registry.py` and the trackers but **not** `features/__init__.py`, `features/engine.py`, `features/library.py`, `features/collector.py`, `features/trackers/median_center.py`. `features/__init__.py` imports `library`, `collector`, `engine` and executes on any `from features.trackers.wick import …`. Reported `coverage_pct` was nevertheless `100.0`. |
| A2 | Phase-0 source manifest claims an incompatible commit | Manifest records `git_commit_hash: 5972556b82ef087d65649075b3020b6694a473e0` while enumerating `latest_1m_wick_imbalance` in the verified candidate universe. At `5972556`, `features/trackers/wick.py` **did not exist** and the registry contained no such entry. |
| B1 | Audit pass artifacts are not immutable | `pass_01.md` / `contract_pass_01.md` are the only pass artifacts; the non-ingest issuance path had no protection against rewriting a pass number in place for a different composite. |
| B2 | Reviewer provenance is role-name only | `auditor` fields hold the role strings `lookahead-auditor` / `contract-checker`; `transcript_sha256` is `null` in both statuses and was never populated. Absence of session evidence was not distinguished from authenticated independence. |
| C1 | Declared feature need not be emitted | Run `20260817_125254_…` recorded `status: SUCCESS`, `COMPLETED`, 1748 candidates, with `latest_1m_wick_imbalance` **100 % NULL** (1748/1748). Column-existence and ordered-hash checks passed. |
| C2 | Wick unavailable state conflated with a real value | `WickTracker.calculate()` returned `0.0` before any completed 1m bar, indistinguishable from a balanced wick or a zero-range bar, while the registry declared `null_policy='allow'`. |
| D | Feature self-granted `verified` status | `latest_1m_wick_imbalance` was registered with `status='verified'` in the same change that implemented it. |
| E | Declared censoring not implemented | `config/target_contract.json` declares `censoring_policy.session_end_censoring: true`; the collector resolved pending candidates only on an opposing flip and had no `on_stop` disposition, so unresolved candidates could leave the observation set entirely. |
| F1 | Contract checker scope not bound to authoritative deliverables | `SPEC.md` §4 declares `candidates.parquet`, `scores.parquet`, `triggers.parquet`, `metrics.json`. Collect mode produces `candidates.parquet`, `observations.parquet`, `collection_manifest.json`. Three declared deliverables are unproducible in this mode; the produced `observations.parquet` is undeclared. |
| F2 | Generated contract tests are tautologies | `tests/test_study_contracts.py` contains `assert "nautilustrader" == "nautilustrader"` and `assert expected_sha256 == "f5cddfd9…"` where both sides are the same baked literal. No artifact is loaded. |
| G1 | ES study carries NQ timestamp evidence | `config/timestamp_contract.json` `empirical_measurement` cites `data/catalog/NQ_v0_2020_2026` and `NQ.XCME-*` bar types for an ES study. |
| G2 | RTH boundary ambiguous and internally inconsistent | Within `strategies/flip_prediction_collector.py`: the OHLCV RTH accumulator used 08:30–15:15 CT, the candidate emission gate used `510 <= minute_of_day < 900` (08:30–15:00), and the `is_rth` context feature used 08:30–15:00. `population_contract.json` says only `session: "RTH"`. |
| H1 | Stale failure packet indistinguishable from current state | `audit/failure_packet.json` reads `BLOCKED` alongside `audit/preflight.json` reading `CLEAR`; neither artifact carries a generation id, binding hash, or timestamp permitting ordering. |
| H2 | Abandoned runs have no terminal status | Six run directories left at `RUNNING` (§5). |
| Scope | Bounded date scope not expressible | `chronology.train: [2024]` was the only date authority; the acceptance request intended only 2024-09-03/04/05. Nothing in the schema or runtime could express or enforce exact authorized dates. |

## 7. Preservation rules

- No file listed in §4 or §5 may be edited, deleted, regenerated, or re-sealed.
- The historical `pass_01.md` and `contract_pass_01.md` remain the pass-01 evidence for
  composite `5232e5cd…`. The repaired workflow issues **new** pass numbers; it does not
  reuse or overwrite these.
- The `RUNNING` run directories are retained as-is. Reconciliation tooling introduced
  during remediation marks abandoned runs in a **separate** artifact and never rewrites
  a historical `run_manifest.json`.
- The 100 %-NULL collection in `20260817_125254_…` is retained deliberately: it is the
  regression fixture's real-world referent.
