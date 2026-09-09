# DETERMINISTIC_REPAIR 006 — `rehearsal_checkpoint_norm`

worker `claude:006_deterministic_repair_83703076` · branch `study/rehearsal_checkpoint_norm` · repair commit `3b63ccd2` · execution closure unchanged at `73db2ed0f213`

## Summary

The study-side defect that contract audit pass 01 named is **repaired and committed**. The controller is
**still BLOCKED with CONTRACT_BLOCKER**, and it will stay blocked no matter how many repair workers are
launched: clearing it requires a fresh independent contract audit (pass 02), which a repair worker may not
issue. The supervisor has no route to that audit. That routing gap is the platform defect reported here.

## First broken stage

`contract_audit`. Everything upstream is clean and stayed clean across the repair: preflight CLEAR,
readiness PASS, tests 137/0, causal audit CLEAR, execution composite `73db2ed0f213` unchanged (no platform
file was touched).

The audit blocker itself traces further back, to phase A. Commit `5ae67a7d` ("OWNER INTERVENTION — drop the
unregistrable fourth feature instance and compile") recorded the owner's decision to proceed single-arm
**only in `study.yaml`**, the lowest-precedence document. `research_decision.yaml` and `SPEC.md` both still
declared the checkpoint-vs-frozen normalization contrast, so the compiled contract had a question with no
treatment fit, no comparator frame and no deliverable — contract audit pass 01, CRITICAL-1.

## Repair (commit `3b63ccd2`)

Ratified the owner's decision **where it binds** rather than restoring the instance. Restoring it re-opens a
genuine CapabilityGap (`structural_max_expansion_checkpoint_atr` is unregistered; its capability flow already
ended in SUPERVISOR_ESCALATION_REQUIRED), and the owner has ruled on that fork.

Swept all four findings in one pass rather than one per freeze cycle:

| finding | change |
|---|---|
| CRITICAL-1 | `research_decision.yaml.research_question` is now SINGLE-ARM and names the three ratified instances. The checkpoint-epoch normalization is WITHDRAWN from scope and its question left explicitly OPEN — not answered negatively. `SPEC.md` question, embedded reference YAML and clause 2 amended to match; clause 2 keeps the violation on the record and states what a proper restoration would require. |
| WARNING-2 | `REHEARSAL_COMPLETE` now covers the FEATURE SURFACE (exactly the three ratified instances, none dropped/renamed/substituted/re-parameterized). `REHEARSAL_INCOMPLETE` now fires on a surface mismatch or on any report claiming the contrast. The old vocabulary would have returned COMPLETE with the treatment variable missing. |
| WARNING-3 | Dropped `model.validation`. It was `model_selection.random` with no candidate set, so the compiler resolved `max_trials` / `primary_metric` / `random_seed` to null and `model.arms` to `[]` — a selection protocol that selects nothing. Single fit, fixed params, determinism from `deterministic: true` / `n_jobs: 1` / `random_state: 42`. Verified null in the recompiled plan. |
| NOTE-1 | `SPEC.md` phase-D instructions now require reporting `excluded.rows_non_binary_label` with the tail table, the fitted feature surface, and an explicit statement that the contrast was not measured. |

Recompiled: `STATUS: COMPILED`, plan `50c8e6667a90` → `9eb2ff0d6e63`, four feature columns
(`prior_1m_regime_efficiency`, `prior_5m_regime_efficiency`, `rolling_300s_giveback_atr`,
`structural_max_expansion_atr`) from the three ratified instances, `model.validation: null`.

## Bounded check — still BLOCKED, by construction

```
python scripts/run_governed_study.py --study studies/rehearsal_checkpoint_norm --through seal
STATUS=BLOCKED state=NEEDS_CONTRACT_AUDIT stage=contract_audit blocker_code=CONTRACT_BLOCKER test_counts={'failed': 0, 'passed': 137}
```

The repair *did* register: `study_spec` `3af9393f69cc` → `a20e2be9efe2`, `plan_sha256` → `9eb2ff0d6e63`.
The controller re-ran compile through preflight and causal audit, then stopped at `contract_audit`.

`research_workflow/governed_controller.py:372-376` keys audit currency to the **execution composite alone**:

```python
verdict = _read(existing).get("verdict", _read(existing).get("status"))
if existing.is_file() and verdict in {"BLOCKED", "INCOMPLETE"} and _read(existing).get("audited_execution_composite_sha256") == fp.get("execution_composite"):
    blocker = ... BlockerType.CONTRACT_BLOCKER
```

`audit/contract_status.json` still holds pass 01's `verdict: BLOCKED` pinned to `73db2ed0f213`, and the
execution composite is unchanged — correctly so, since a study-contract repair must not touch platform code.
So a study-side repair can never clear a contract blocker. That much is intended: the controller's own
failure packet says `allowed_actions: ['submit independent audit']` and `deterministic_repair_possible: false`
(`governed_controller.py:333-337`). Auditor independence — the repairer must not write its own verdict.

## PLATFORM DEFECT — the supervisor has no re-audit route

`research_workflow/supervisor/derive.py:203` and `:220-222` both derive `AUDIT_BLOCKER` for a
`CONTRACT_BLOCKER` / `CAUSALITY_BLOCKER`. `research_workflow/supervisor/core.py:289-290` routes it:

```python
if code in ("DETERMINISTIC_BLOCKER", "AUDIT_BLOCKER"):
    return self._launch_repair(d)
```

`AUDIT_BLOCKER`'s only handler is `_launch_repair`, and `core.py:338` states the intent plainly:
`"AUDIT_BLOCKER": "launch DETERMINISTIC_REPAIR"`. The supervisor therefore answers "an independent audit
found a blocking finding" with a worker whose designated remedy the controller has already marked
`deterministic_repair_possible: false`.

Failure path, deterministic and already half-observed here: worker 006 repairs the study-side defect →
controller still BLOCKED (the pass-01 verdict is still current against an unchanged composite) → derive
returns `AUDIT_BLOCKER` again → `_launch_repair` again. Each fresh worker re-reads the same audit report,
finds the finding already fixed, and has nothing left to repair. `_launch_repair` (`core.py:627-628`) caps
this at `MAX_ATTEMPTS`, then `_escalate`s with `"blocker {bc} at {stage} persisted after independent repair
attempts"` — a message that says the blocker persisted through repair, when in fact the repair succeeded and
nobody ever asked for the re-audit that would prove it.

Cost in this rehearsal: two further disposable workers and an escalation whose text misdescribes the state.

Missing route: after a repair worker returns against an `AUDIT_BLOCKER`, the supervisor should launch a
CONTRACT_AUDIT / CAUSAL_AUDIT worker (pass N+1, distinct auditor identity — the study already alternates
`lookahead-auditor:004…` / `contract-checker:005…`) rather than another repair. A sufficient discriminator is
already on disk: the fingerprints show `study_spec` moved `3af9393f69cc` → `a20e2be9efe2` since the verdict
was issued. An audit verdict whose audited spec no longer matches the current spec is stale and should route
to a re-audit, not to a repair.

Not fixed here: `research_workflow/` is outside this packet's write surface, and
`autonomy_decisions.platform_change_required: chore_branch_and_fresh_session` forbids platform work in a
study session.

## State on exit

- controller: `BLOCKED` / `NEEDS_CONTRACT_AUDIT` / stage `contract_audit` / `CONTRACT_BLOCKER`
- study branch: `3b63ccd2`, clean apart from the study's own `artifacts/` and `audit/`
- next real step: contract audit **pass 02** against composite `73db2ed0f213` and spec `a20e2be9efe2`, by an
  identity distinct from `contract-checker:005_contract_audit_f4bffac6`. The four pass-01 findings are all
  addressed; pass 02 adjudicates them and, if CLEAR, the controller proceeds to seal.
