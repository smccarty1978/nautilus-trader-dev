# nq_fair_pricing_reversion: 1m vs 1s outcome-contract audit

**Verdict:** NO_CHANGE_REQUIRED

The 1m TRAIN run stays the immutable baseline. Switching barrier resolution to 1s changes no candidate, signal, entry price or censoring. It changes labels only where the 1m run had already flagged a same-minute ambiguity, and none of those are in A1∩A2.

## 1. State (Phase 0)
- **Lease:** `antigravity` holds it, with a 72-hour TTL; no controller is running. I did not claim it.
- **Sealed identity:** plan `9b9b80c6…`, composite `dad232b5…`, dataset `9e7aecb7…`. These match the compiled plan and the TRAIN manifests.
- **Uncommitted worktree state** (HEAD `e622784c`):
  - Modified: `study.yaml`, `compiled_plan.json`, the seal, authorization, smoke acceptance, and the audit and readiness files.
  - Untracked: `audit/pass_04.md`, `audit/contract_pass_04.md` and `artifacts/train_scientific_analysis.json`. The last file is new since the TRAIN run and was written by the lease owner.
  - I modified nothing; the worktree status is unchanged before and after.
- **Reproducibility:** the TRAIN artifacts reproduce exactly from the current worktree. All 28 sessions I replayed in 1m mode match TRAIN on every candidate and observation column. One of them, 2022-05-09, used the completely unmodified sealed plan.
  - Reproduction depends on the uncommitted files (see §10).

## 2. Authoritative outcome contract (Phase 1): SPEC_AMBIGUITY
| Layer | What it says |
|---|---|
| SPEC.md §2.2, §3 | entry `next_bar_open`; "next actual executable print"; max tape gap 60 s. It never names a resolution bar granularity. |
| study.yaml `outcome:` | no stream key. The grammar has none to give: `OutcomeSpec` is strict (`research_workflow/grammar/spec.py:173-214`). |
| Compiler | `research_workflow/grammar/compiler.py:1260` sets `stream = population.cadence.stream`, which is `nq_1m` for `cadence: completed_1m`. It is copied into the contract at `:1307`. This is not an overridable default: no other source exists. |
| Compiled plan | `outcome.stream: "nq_1m"`, while `streams[]` declares `nq_1s` with `role: execution`. |
| Host routing | `research_workflow/host/strategy.py:200`: `plan.outcome.stream or epoch_stream`. `:278` and `:305` feed only that stream to the kernel. Its own comment calls it "the outcome (execution) stream". |
| Kernel | `research_workflow/host/outcomes.py:440-620`: the kernel resolves on whatever bars it is fed. The entry is the open of the first bar with `ts_init > T`, `entry_ts` = that bar's `ts_event`, and the cutoff test is `entry_ts > cutoff` (`:456-466`). |
| Manifests | every resolution second is a multiple of 60, confirming 1m resolution. |

The spec does not require 1s resolution, so this is not a SPEC_VIOLATION. The "1s sequencing" expectation came from the conversation and the plan's execution role, not from SPEC.md.

There is a platform-level mismatch underneath. The plan labels `nq_1s` as the execution stream, yet a `completed_1m` population can only ever resolve outcomes on 1m bars, and nothing in the YAML can change that.

## 3. The 11:00 boundary (Phase 2)
- **Decision time:** T = 11:00 is the decision time. It is the 1m bar whose `ts_init` is 11:00:00, and the population qualifier `rth_open_elapsed_seconds <= 5400` admits it.
- **Entry:** the open of the next bar. In 1m mode, `entry_ts` is that bar's open instant, 11:00:00; in 1s mode it is the first traded second.
- **Causality:** this is causal. The decision bar's close is the last trade before 11:00:00, and the entry is the first trade at or after 11:00:00.
- **Where the cutoff applies:** to candidate generation (the qualifier) and to entry execution (`entry_ts > 11:00:00` → `ENTRY_PAST_CUTOFF`).
- **Replay result:** all 27 sampled 11:00 candidates have the same entry timestamp and price under 1s, so none would be rejected.
- **Retraction:** my TRAIN report said most 11:00 entries "would probably be rejected" under 1s. That was wrong, and I retract it.
- **Residual ambiguity:** the remaining issue is sub-second. The spec says a print "after 11:00:00" is rejected, while the platform counts a bar opening at 11:00:00 as an entry at 11:00:00. This affects 772 candidates (1.1%) identically under 1m and 1s. It is a wording matter, separate from resolution granularity.

## 4. Affected population (Phase 3, full TRAIN, from the 1m artifact)
| Set | n | No signal | A1 only | A2 only | A1∩A2 | Years | Time of day (09:31–10:00 / 10:01–10:30 / 10:31–11:00) |
|---|---|---|---|---|---|---|---|
| tp38 AMBIGUOUS_SAME_BAR_TOUCH | 31 | 30 | 0 | 1 | **0** | all 2022 | 20 / 9 / 2 |
| anchor AMBIGUOUS_SAME_BAR_TOUCH | 124 | 111 | 9 | 2 | 2 | 16 / 95 / 13 | 91 / 27 / 6 |
| 11:00 candidates | 772 | 705 | 29 | 32 | 6 | — | — |

Other mechanisms that could change a label without being flagged:
- an entry-time or entry-price difference;
- a 1s tape gap over 60 s;
- 1m bar high/low not matching the 1s bars.

The replay measured all three. Candidate identities are in `ambiguous_candidates.csv`.

## 5. Method (Phase 4)
- **Engine:** the governed host, `research_workflow.host_runner.run_plan_on_catalog`. It runs the real NautilusTrader engine on the governed catalog with a 5-day warmup and byte-verified dataset `9e7aecb7…`. I built no simulator.
- **Plans:**
  - 1s run: the sealed plan with one in-memory override, `outcome.stream = nq_1s`.
  - Both modes: the observation-only flag `outcome.entry_observation = true`, which adds `executable_entry_*` columns and has no label logic.
- **Sessions:** 27, selected deterministically:
  - all 9 sessions with tp38 ambiguities;
  - 8 anchor-ambiguity sessions, chosen by hash;
  - 8 A1∩A2 sessions, chosen by hash;
  - 2 shortened sessions (2023-07-03 and 2023-07-04).
- **Sample size:** 2,427 candidates, including 27 at 11:00 and 31 in A1∩A2.
- **Isolation:** scratch output only, and the worktree was untouched.

## 6–7. Candidate-level parity (1m replay vs 1s replay)
| Check | Result |
|---|---|
| Candidate identity / A1 and A2 membership | 2,427 / 2,427 identical |
| Entry price (so all tp38 and anchor barrier levels) | 2,427 identical |
| Entry timestamp | 2,393 identical; 34 later under 1s by 1–10 s (no trade in the first second); price identical and no label effect |
| Entry unavailable (GAP / ENTRY_PAST_CUTOFF) | 0 in either mode |
| tp38_sl25 | 2,206 resolution-precision only; 190 identical; **31 same-minute disambiguations: 23 stop-first, 8 target-first** |
| anchor_sl25 | 2,106 precision only; 292 identical; **29 disambiguations: 12 stop-first, 17 target-first** |
| m25–m100 | precision or identical only; no censoring change |
| Actual label flips (target↔stop) | **0** |
| Censoring changes (TIMEOUT, GAP and so on) | **0** |
| Contract or implementation defects | none |

**Resolution-precision cases:** 1s resolves earlier by 1–59 s (median 33 s for tp38), and the 1m time equals the 1s time rounded up to the minute.

**Exceptions:** 4 milestone rows on the 2023-07-04 holiday session resolve 1 minute later under 1m than that rule predicts. In all four, the 1s entry is 2–3 s late and the label is unchanged. The likely cause is that the 1m bar's high and low don't match the 1s bars on that thin session; the root cause is unverified.

## 8. A1∩A2 sensitivity (Phase 5), tp38_sl25
| | n |
|---|---|
| A1∩A2 candidates | 900 |
| Exposed to the only label-changing mechanism found (same-minute ambiguity) | **0** (exact, full census) |
| Replayed and proven unchanged | 31 |
| Changed under 1s | 0 |
| Not replayed (869) | Their labels can change only through mechanisms that produced 0 changes in 2,396 non-ambiguous replayed candidates. |

**Bound on the 869 not replayed** (rule of three):
- The per-candidate change rate is at most about 0.13%, so at most about 1.1 of them are expected to change.
- Each flip moves the overlap rate by about 0.12 pp.
- A strict, assumption-free bound for these 869 cannot come from a sample. It would require replaying the 538 overlap sessions.

**Exact full-population effect of the one mechanism found** (all 31 tp38 ambiguities resolved):

| Population | 1m | 1s-corrected |
|---|---|---|
| A0 | 38.12% | 38.11% |
| A2 | 38.74% | 38.76% |
| A2 only | 37.52% | 37.54% |
| A1∩A2 | 42.13% | 42.13% (unchanged) |
| A1∩A2 vs no-signal | +4.0 pp | +4.0 pp (unchanged) |

95 of the anchor-arm ambiguities were not replayed; at most 1 of them is in A1∩A2.

## 9. Correction
No collection is needed: the TRAIN conclusions do not depend on bar granularity.

Optional platform change, for future studies (not needed now):
- A chore letting a study route barrier outcomes to the execution-role stream, for example an explicit `outcome.stream`.
- It needs a reseal, and validation that the 1s runs reproduce this parity table.
- Any 1s collection would need separate approval.

## 10. Governance and reproducibility blockers
1. **The sealed contract is uncommitted.** The study.yaml outcome rewrite, compiled plan, seal, authorization and audit passes exist only as working-tree changes. The TRAIN artifacts reproduce from them today, but git does not preserve them. Only the lease owner (`antigravity`), or you, can commit them. This remains unresolved.
2. **Untracked file:** `artifacts/train_scientific_analysis.json` appeared after TRAIN; I did not read or change it.

## 12. Recommendation
- Keep the 1m TRAIN run as the baseline. The 1m/1s difference is immaterial to the A0/A1/A2 conclusions.
- Record the outcome stream (`nq_1m`) and the 11:00 entry convention explicitly in the study's decision record, once the contract is committed.
- Decide whether the platform should support execution-stream outcomes before any future study needs 1s resolution.
