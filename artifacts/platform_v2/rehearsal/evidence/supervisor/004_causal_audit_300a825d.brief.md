# AUDIT BRIEF 004_causal_audit_300a825d -- CAUSAL audit, pass 01, study `rehearsal_checkpoint_norm`

You are `lookahead-auditor` (owns A, B, C1-C3, F, G, H). This brief is the SMALLEST packet sufficient to verify the changed executable surface.
Read it, then the audit packet it names, then your role file. Do NOT re-discover the repository.

## 1. Facts the deterministic gates already proved (do not re-derive; cite them)

- audited execution composite (declare exactly this): `73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7`
- plan_sha256 `50c8e6667a90124b06d78c7a1c1981ec67c741d4c7f1d1c0cbc93ef7fad16de3`  spec_sha256 `3af9393f69cc0ff384ba3bd2248a88ec713be074465eb29be11b382c24804945`  closure files 115 (hash v2)
- preflight: CLEAR (8/8 required checks PASSED; leaked_outcome_columns=[]; composite 73db2ed0f213)
- readiness: PASS (R1_NQ=pass, R8_host_boundary_lint=pass, R5_binding_proof=pass, R3_session_table=pass, R9_closure_current=pass, R10_zero_study_python=pass; composite 73db2ed0f213)
- tests: PASS 137 passed / 0 failed @ composite 73db2ed0f213 (6 files)
- controller: STATUS=OK state=NEEDS_CAUSAL_AUDIT stage=causal_audit blocker=None; fingerprints execution_composite=73db2ed0f213 current=73db2ed0f213 plan=50c8e6667a90 spec=3af9393f69cc
- worktree `C:\Users\Scott McCarty\Projects\Nautilus Trader-rehearsal_checkpoint_norm` branch `study/rehearsal_checkpoint_norm` @ `5ae67a7d7a7fc3d3365091b59ae00330348f136b`; dirty paths: 2 (listed in the packet; all under studies/ unless noted)

## 2. Audit packet = the compiled semantic contract (primary surface)

- `C:\Users\Scott McCarty\Projects\Nautilus Trader-rehearsal_checkpoint_norm\studies\rehearsal_checkpoint_norm\_work\controller\audit_packet_causal.json` (18978 bytes, sha256 `168ba1ea9cbb05dcb5fd1dce2a3002c75fa2d4f5a084ac470db52bcf1d3f89ef`, packet_version 2)
- Its `instructions` field describes the MANUAL flow (audit/pass_NN.md + `research audit ingest`); under the supervisor the report path and result card in your worker packet take precedence. Never write under studies/<id>/.
- `packet.closure.stages` lists every closure file per stage; `audit/frozen_execution_manifest.json` carries the per-file hashes. Open it only to verify a membership claim -- never compute closure membership yourself (Python is not on your allowlist).

## 3. Executable surface: what changed

- closure per stage: audit 1, collection 100, lifecycle 12, modeling 5, oos 6, outcome 4, replay 92; composite `73db2ed0f213`
- first pass of this kind under the supervisor: no prior manifest snapshot; the surface is the full closure named in the packet
- closure files the STUDY BRANCH changed against `main`: none (the platform under audit is main's)
- Every other closure file is unchanged since the last audit / since main and needs NO re-read. Open a source file only for a claim the packet cannot prove, and cite `file:line`.

## 4. Prior findings to adjudicate FIRST (pass 01)

- none: this is pass 01. Adjudication table not required.

## 5. Your checklist subset (verbatim from docs/CAUSAL_CHECKLIST.md; `contract-checker` owns the rest -- refer, never report)

## A. NautilusTrader timestamp conventions

- **A1.** Bars use `b.ts_init` (close time, post `ts_init_delta` shift) — not
  `b.ts_event` (open time) — when indexing or stratifying.
- **A2.** When constructing `BarType` from raw Databento data, `ts_init_delta`
  shifts 1m bars +60_000_000_000 ns and 5m bars +300_000_000_000 ns. 1s bars
  need no adjustment.
- **A3.** Inside strategies, "current price" uses `self.cache.bar(bar_type)` or
  the `bar` argument to `on_bar`, never a future-indexed lookup.
- **A4.** Timer/alert callbacks (`on_event` for `TimeEvent`) do not assume bar
  data has already arrived for that timestamp.
- **A5.** Datetime conversion preserves close-time semantics. Resampling uses
  explicit `label`/`closed` arguments; `closed='right'` on a 1m resample of 1s
  bars injects look-ahead (see `catalog_1m_resample_bug`) — use `closed='left'`.

## B. Feature engineering look-ahead

- **B1.** Rolling computations (`rolling`, `ewm`, `expanding`) do not use
  `center=True`.
- **B2.** Indicator values used at bar `i` were computed using only data up to
  and including bar `i` — never bar `i+1`.
- **B3.** ATR, EMA and other recursive indicators are sampled at the correct bar
  — typically `i-1` or earlier when used as a feature for predicting bar `i`.
- **B4.** No `.shift(-N)` or negative-lag operations in the feature path.
- **B5.** Forward-fill does not leak future values into past timestamps. `bfill`
  is essentially always a bug in time-series features.
- **B6.** Joins/merges align on the correct boundary — `merge_asof` must carry an
  explicit `direction=` (normally `"backward"`).
- **B7.** Normalization statistics (z-score, scaling) come from a strictly past
  window, not the full dataset.
- **B9.** Feature trackers contain no undocumented or implicit timeframe
  assumptions. Window units, cadence, warmup and reset policy are explicit.
- **B10.** Multi-timeframe variants reuse the same verified tracker when the
  mathematical semantics are identical.

## C. Label construction

- **C1.** Labels use future windows *by design* — verify the look-ahead is
  **only** in label columns, never features.
- **C2.** Label timestamps align so the label at row `i` is what the model is
  asked to predict from features at row `i`.
- **C3.** Train/test splits are temporal, not random.
## F. Session and time handling
- **F1.** RTH/ETH classification uses bar **close** time, not open time. This is
  a repeat offender: `ts_event` in an RTH gate has been found in
  `studies/_shared_exit_mgmt/base_strategy.py:232` across multiple audits.
- **F2.** Session boundaries are explicitly handled — rolling windows spanning
  session boundaries either reset or are flagged.
- **F3.** Timezone handling is explicit. Naive timestamps are a red flag.
- **F4.** DST transitions do not break time-of-day filters. Use named zones
  (`America/Chicago`), never fixed UTC offsets.

## G. Data integrity

- **G1.** Continuous-contract data is back-adjusted at quarterly rolls, or rolls
  are handled explicitly. Only `*.v.0` (volume-continuous) data is permitted.
- **G2.** Missing bars are handled — neither forward-filled with stale prices nor
  silently dropped.
- **G3.** When 1s data is resampled to 1m, the resampler uses correct
  `label`/`closed` arguments and drops empty minutes.
- **G4.** Volume-zero or single-tick bars are not used to compute indicators.

## H. Offline bracket simulation price resolution

- **H1.** SL/PT detection uses bar **HIGH and LOW**, not close.
- **H2.** Temporal resolution matches NT execution. Flag any sim iterating over
  bars coarser than 1s when the NT strategy monitors stops on 1s bars.
- **H3.** Re-entry logic matches the NT strategy's re-entry rules.
- **H4.** Fill price is the actual next-bar open or NT-reported fill — **not** the
  trigger price. Flag any sim computing
  `exit_pnl = (sl_px - entry_px) * direction * MULT`. This is the single most
  repeated finding in repository history (8 occurrences).

---

## Severity definitions

| Severity | Meaning | Gate effect |
|---|---|---|
| `CRITICAL` | Demonstrated defect that changes results, or an unenforced invariant the study's conclusion depends on | Blocks |
| `WARNING` | Real defect that does not change the headline result, or an enforced-in-practice-but-not-in-code invariant | Blocks unless explicitly adjudicated in the SPEC |
| `NOTE` | Disclosure, hygiene, or inherited upstream limitation | Does not block |

A finding is `CRITICAL` only if you can state a concrete failure path. "This is
not independently validated" is a `WARNING` unless you can show the validation
would fail.

## 6. docs/RESEARCH_WORKFLOW.md section 17 -- runtime guarantees already provided (do not re-derive)

## 17. Timestamps

- Raw Databento OHLCV bars are **OPEN-stamped** (`ts_event`). Complete OHLCV is usable only at
  interval close.
- Offline research normalizes derived bars to **CLOSE-stamped** indices
  (`label='right', closed='left'`).
- NT catalogs preserve open-stamped `ts_event` and set `ts_init = ts_event + bar_duration_ns`
  (1s +1s, 1m +60s, 3m +180s, 5m +300s), so the event loop dispatches completed bars at
  interval close.
- **1s bars therefore arrive before their parent 1m bar** (`add_bars_causal_order`,
  `verify_callback_causal_order`; proven per-study by R4). Buffer recent 1s bars and replay
  them retroactively from fill time, or you will miss the first minute of price action.
- Derived timeframes are aggregated from **completed** lower-timeframe bars, never loaded as an
  independent stream.
- Per-event callback ordering beyond these guarantees is a property of a study family and
  belongs in that study's `SPEC.md`, not here.
- Display and analysis in Central Time (`America/Chicago`); NT internals are UTC.
  RTH 08:30–15:15 CT.

---

## 7. Bounded procedure (mandatory)

1. Do not reopen unchanged files. Section 3 names what changed; everything else was audited at the prior composite or is main's platform.
2. Use packet references first: streams/visibility, trackers, outcome kernel, chronology, closure membership, deliverables all come from the packet and this brief.
3. Inspect source only for a claim the packet cannot prove (state flow, callback order, a write site). Read the smallest range; cite `file:line`.
4. Stop when every rule id in section 5 is under `Clean checks`, a finding, or `Not applicable`. Then write the report and the result card.
5. No speculative architecture findings. A finding needs a concrete failure path (CRITICAL) or a real defect (WARNING); hygiene is a NOTE.
6. Do NOT read WORKFLOW.md, AGENTS.md, docs/RESEARCH_WORKFLOW.md, docs/CAUSAL_CHECKLIST.md, PLATFORM_STATE.json or compiled_plan.json: this brief carries the subset you need. compiled_plan.json only for a specific field the packet omits.
7. Do not run Python (`python -c`, heredocs), PowerShell variable assignments or recursive listings: the read-only allowlist denies them and every denial costs a turn. The only commands you need are `python scripts/research.py study result ...` and, if useful, `git diff`/`git log`/`git status`.
8. Keep `--notes` / `--next-action` free of `;`, `|`, `&`, `>` characters (compound commands are refused by the allowlist); keep them under 300 characters.
9. Report budget: causal 1,500 words / contract 1,000 words. Write the report to `C:\Users\Scott McCarty\.nt_research\supervisor\rehearsal_checkpoint_norm\results\004_causal_audit_300a825d.report.md` and declare auditor `lookahead-auditor:004_causal_audit_300a825d`.
