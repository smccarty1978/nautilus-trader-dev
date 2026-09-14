# S2 — RESUME AND COLLECT — nq_mtf_regime_atlas_pilot2023

Session 2026-09-14 · human-attended · study branch head at report time: see `git log` (commits b3b45d4c → c2209196 and after)
Frame `80e644d1ac611a8911b570c3d6354b7558344f0fb5e8461595c426670b59bc0f` · plan `ed2b9dfa…` · closure `041379f7…` · seal `1d135a78…` · dataset NQ_1S_V2_GLOBEX digest `9e7aecb7…` (bytes VERIFIED) · years 2023 only, 2026 not opened.

## 0. Starting state was not the packet's

The packet assumed `c84b9ad1`. The branch was at `59320d8f`: a 2026-09-12 session had already merged G7,
recompiled, audited (pass_03), sealed, smoked, renamed `triggering_1s_ts_init → decision_epoch_ts_ns`, and
stopped because `session_end: censor` censored 1380/1380 smoke rows. Its lease was still "live"; force-released
(recorded on the lease) and claimed.

## 1. CENSUS — read before any table

| | |
|---|---|
| rows (1m checkpoints) | **353,358** |
| unique 1m regimes | **28,030** (flips: **28,029**; the first regime of the run has no flip) |
| session-day clusters | **258** Globex trading days (unique `session_close_ts`); flips per day median 109, range 75–140 |
| censored fraction, flips, by cause | trading-day close **258 / 28,029 = 0.92%** · data gap **0** · chronology boundary (DATA_END) **0** |
| censored fraction, all checkpoint rows | 3,180 / 353,358 = 0.90%, all SESSION_END |
| censoring pattern | exactly one censored flip per session day (the regime open at the close) |
| ETH / RTH split (flips, `decision_epoch_ts_ns`) | ETH **20,358** · RTH **7,671** (27.4%) · censored ETH 243 / RTH 15 — **verification count, not a governed table** (platform `CalendarSessionTable` RTH = (08:30 CT, min(15:15 CT, close)]; no registered op classifies ETH/RTH) |
| collect wall time | replay 3,269 s; controller run through merge 57 m 45 s (08:35:16 → 09:33:01 local); frame register 10.8 s |
| owner interventions during collect | **0** (2 owner decisions before collection — §3) |
| frame-to-table on real data | **1.2 s** total (load 0.45 s, pipeline 0.34 s, frame verify 0.36 s) |
| tables produced / wanted | **1 / 8** — T6 (1m census by direction and censor cause) |
| capability gaps hit | 6 (§4) + 1 wrong-results defect (§2) |

**Censoring is small (0.92% of flips), so the 1m time-to-flip distribution is essentially complete.**
Resolved-flip time to next flip: median 540 s, p10 180 s, p90 1,620 s, p99 3,120 s, max 8,280 s; identical
medians by direction. (Verification read; T2 itself is unsatisfied — §4.)

**Uncertainty: none.** No registered op produces session-day-clustered uncertainty (contract §9). Every number
here is a bare count or quantile over 28,029 flips in 258 clusters and carries NO uncertainty estimate.

### T6 (governed: `analysis.classify.precedence`, explore record `…/explore/80e644d1…/2257791f8912/`)

| class | −1 | +1 | total |
|---|---|---|---|
| flip_resolved_next_flip | 13,879 | 13,892 | 27,771 |
| flip_censored_session_end | 136 | 122 | 258 |
| flip_censored_gap / other / unresolved_horizon | 0 | 0 | 0 |
| checkpoint_not_anchor | 156,588 | 168,741 | 325,329 |

Matches the independent verification count exactly.

## 2. ESCALATION — a defect producing wrong scientific results (the freeze exception)

**Higher-timeframe regime context is effectively absent for the whole year.** Derived buckets publish only when
every source 1s bar is present (`research_workflow/host/mux.py:91-93`, `_complete`: `count == expected`), and
only ~58% of Globex seconds carry a 1s bar (12,395,770 1s bars vs 358,816 1m bars × 60).

| stream | bars 2023 | ≈ upper bound (1s bars / bucket s) | regimes 2023 | median age at a 1m flip |
|---|---|---|---|---|
| nq_5s | 1,346,678 | ~2.48 M (54%) | 89,210 | 0.1 h |
| nq_30s | 139,039 | ~413 k (34%) | 11,471 | 5.0 h |
| nq_1m (external) | 358,816 | complete | 28,030 | — |
| nq_3m | 11,667 | ~69 k (17%) | 977 | 11.4 h |
| nq_5m | 5,513 | ~41 k (13%) | 474 | 14.8 h |
| nq_15m | 1,026 | ~13.8 k (7%) | 95 | 65.3 h |
| nq_30m | 318 | ~6.9 k (5%) | 35 | 157 h |
| nq_1h | 28 | ~3.4 k (0.8%) | **3** | **2,594 h** |
| nq_4h | 0 | ~860 | **0** (dir 0 and ATR null on 100% of rows) | — |

Values are non-null, so "no all-null feature columns" (contract §12) cannot see it. Affected: every
`dir_/age_s_/bars_/start_ns_/atr_<tf>` for 3m–4h; the 1h ATR secondary denominator (§5, null on 49%); and the
registered 5m features (`regime_alignment`, `current_5m_*`, `prior_5m_*`, `distance_to_completed_5m_*`), which
read the same `regime_5m`. **Q4 / Q5 / T4 / T5 cannot be answered from this frame.** Unaffected: the 1m flip
population, 1m outcome, 1m path columns, T6, T2's inputs. The 5s/30s context is degraded, not absent.
The six-year atlas must not start on this composition until it is resolved.

Not escalated (all four §5 conditions checked): no runtime failure after compile + seal (G7b held); the `at_epoch`
relaxation is cadence-stream-only in `availability.rows`; the collect needed no intervention; frame-to-table is seconds.

## 3. What changed this session, and why

1. **OWNER AMENDMENT 02** — `session_end: truncate`. `censor` censors whenever T+24h passes the close
   (`host/outcomes.py:277`) = every row; `truncate` (`:267-272`) is A2 as written. Plan delta vs bed51b46 is
   exactly `outcome.session_end_rule` (+ hashes). Six-year question doc carries it.
2. **§1.3 scope, from the plan** — old plan 67c7b47d vs ed2b9dfa: `streams[]` — only `nq_1m` (sole context stream)
   `strictly_before → at_epoch` + `epoch_bearing`; `availability.rows` — 30/2 → 32/0, the two being `regime_1m`
   and `excursion_1m` (both on nq_1m). Feature rows are written `at_epoch` unconditionally (`compiler.py:1614`),
   so they carry no scope information.
3. **pass_04** delta causal audit CLEAR (0 C / 4 W / 1 N); truncate touches only outcome/observation columns.
4. **Controller did not notice a plan-only change** (owner-approved remedy, no code change). With closure 041379f7
   unchanged it returned READY_TO_SMOKE and then READY_TO_COLLECT while seal, preflight, readiness, frozen
   manifest AND the smoke card were bound to bed51b46 (the smoke card being the 100%-censored one). Freshness is
   composite-keyed (`governed_controller_v2.py:110-132`; smoke receipt likewise). The stale generated files were
   deleted and rebuilt by the controller's own stages; all name ed2b9dfa, seal cites pass_04. Collection
   partitions ARE plan-bound (`lifecycle_v2.py:645`).
5. **Smoke at ed2b9dfa**: 1360 LABELED_POSITIVE / 20 SESSION_END (1.45%), median 480 s, 45 s.
6. **EXPLORE spec repaired** (declarative): symbols `>`/`==` → `gt`/`eq` (`explore compile` passed the symbols;
   `explore run` refused them); anchor `flipped_1m == true`; T2 removed from the executed spec (§4).

## 4. Unsatisfied tables and capability gaps (findings, not failures)

| table | status | reason |
|---|---|---|
| T1 | not produced | no grouped descriptive-summary op (mean/median by group) |
| T2 | **unsatisfied** | `analysis.incidence.cumulative` requires `observed_seconds_column` (`diagnostic_ops.py:252`); the flip-kernel frame has none (observations: flip_ts, time_to_flip_seconds, horizon_end_ts, session_close_ts, resolved_at_ts); no registered op derives it; not substituted |
| T3 | not attempted | `analysis.path.anchored_offsets` exists; not in the committed spec |
| T4, T5 | blocked twice | no grouped op AND the HTF context is invalid (§2) |
| T6 | **produced** | 1m census by direction + cause; ETH/RTH only as a verification count |
| T7, T8 | not produced | no grouped descriptive-summary op |
| §9 | not produced | no session-day-clustered uncertainty op |

Registered analysis ops (`capabilities_index.d/analysis_ops.yaml`): anchor.first_threshold_crossing,
incidence.cumulative, decomposition.buckets, control.cell_matched, path.anchored_offsets, classify.precedence,
gate.population_parity, gate.arm_delta_integrity, metric.tail_lift.

Gaps hit: (G-a) derived-bucket completeness rule vs sparse 1s tape (§2); (G-b) flip kernel emits no
observed-seconds column; (G-c) no grouped descriptive op; (G-d) no clustered-uncertainty op; (G-e) no ETH/RTH
classification on the frame (feature.session_membership has no runtime adapter, G6); (G-f) controller freshness
not bound to plan_sha256.

## 5. Corrections to the decision record (not edited — would stale compile provenance of a registered frame)

- `research_decision.yaml` population_cadence says "the flip row is … bars_1m == 1". The flip row is
  **bars_1m == 0, flipped_1m == true**; bars_1m == 1 is the next checkpoint (550 one-bar regimes have none).
- Declared identity `(regime_start_ns, checkpoint_index)`: `checkpoint_index` is **null on 100% of rows**.
  `(regime_start_ns, observation_ts)` is unique (0 duplicates).
- `WORKFLOW.md:946-947` (main) recommends `session_end: censor` for an ETH+RTH census — wrong for event labels.

## 6. Carried-forward items, resolved

- Tests stage and the 1s+1m path: the stage runs `test_host_core.py` (synthetic 1s+1m tape,
  `delivered == [a_1s@60, a_1m@60, a_1s@61]`) — fixture-level only, no catalog path. It did not and could not catch §2.
- T2 `observed_seconds`: confirmed absent on real rows.

## 7. After

Rows exist; one table exists. Per the packet the freeze resumes — with the §2 defect as the named exception.
Recommended order: fix derived-bucket completeness for a sparse 1s tape (or derive 3m–4h from the external 1m
stream) on a chore → re-collect this pilot (≈1 h) → only then the six-year atlas. G-b/G-c/G-d decide how many of
T1–T8 the atlas can produce; the features dropped from the pilot are still unchosen, because the alignment
tables that were meant to choose them could not be built.
