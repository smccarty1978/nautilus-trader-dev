# Stage-2 Pre-Execution Lookahead / Timestamp / Execution-Contract Audit

**Scope:** `SPEC.md`, `stage2_frozen_policy.json`, `run_stage2_ohlc.py`, `analyze_stage2.py`, and imported constants from `common.py`  
**Phase:** pre-execution audit plus tolerance-only re-audit after the authorized 2025 attempt failed closed; 2026 remains sealed  
**Status:** **PASS — STAGE 2 MAY RUN**  
**Open findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The final Stage-2 implementation passes the mandatory pre-execution lookahead, timestamp, and execution-contract gate. The policy was frozen before monetization and before 2026 exposure; Jan-Feb 2025 threshold-calibration observations cannot become monetized entries; all established-regime filter fields use state known at the decision boundary; strict W4 crossing and `T+1s` availability are enforced; entry uses the explicit next available 1-second open; the stop is exactly 1.5 ATR from fill and active on the entry bar; stop/flip same-bar priority is declared and implemented; positions hold through the aligning flip and exit only at the next flip against the countertrade; final-open regimes are handled without future-exit selection; and candidate/trade/skip accounting is fail-closed.

The output remains explicitly limited to a 1-second OHLC research simulation. It is not NT-native executable validation, does not claim tick/quote fill accuracy, and is not deployable.

## Mandated checks

| Check | Result | Evidence |
|---|---|---|
| Policy frozen before monetization and 2026 | **PASS** | `stage2_frozen_policy.json` contains one policy and predates any Stage-2 result. The runner embeds its SHA-256 in every trade. The analyzer requires both years to match the current frozen hash. A 2026 run additionally requires a clean, closed 2025 reconciliation under the same hash. |
| No 2026 selection | **PASS** | Filter rationale uses 2021-2024 discovery and 2025 descriptive sanity values only. No Stage-2 output existed during audit. The 2026 command cannot run without the PASS audit and same-policy clean 2025 predecessor. No 2026 value can modify the policy JSON, threshold, stop, or exit. |
| 2025 calibration window excluded | **PASS** | The authorized 2025 window is `[2025-03-01, 2025-12-31)` UTC. Candidate decisions and actual fills are both required to be in that window. Jan-Feb threshold-calibration observations may establish previous-score state but cannot create a monetized decision/fill. |
| Filter features causal at decision | **PASS** | For a decision at `D`, the state index is the last bar with open `< D`; that bar has completed by `D`. Running MFE at the prefix, progress-window prefix, current close PnL, retained ratio, and age therefore use no later data. Regime ATR is finite/positive and fixed at the start; trigger ATR is independently finite/positive before candidate acceptance. |
| W4 observation `T` available at `T+1s` | **PASS** | `decision_ts = score_observation_ts + 1s`. Filter state uses bars completed strictly before that boundary. The fill lookup starts at that availability boundary and selects the next actual raw-bar open. |
| Strict crossing semantics | **PASS** | A trigger requires `previous_valid_score < threshold <= current_valid_score`. An initial above-threshold score is not a crossing. If a crossing occurs while the filter is false, only a later true recross can qualify. Once an established crossing produces a candidate, that prevailing regime is closed to further candidates. |
| Explicit next-open entry timing | **PASS** | `searchsorted(raw_open_ts, decision_ts, left)` selects the first available open at or after score availability. Missing-bar delays are recorded. A fill at/after a real confirming flip, outside the authorized window, or with no next open becomes a named skip rather than a trade. |
| Stop exactly 1.5 ATR from fill | **PASS** | `stop_px = entry_fill - entry_direction * 1.5 * trigger_ATR` has no tick rounding. `realized_stop_atr` is persisted per trade; reconciliation applies a zero-relative-tolerance/`1e-9` ATR absolute-tolerance check and persists the maximum observed reconstruction error. The tolerance covers IEEE-754 reconstruction noise only and is many orders of magnitude below a tick. |
| Stop active on entry bar | **PASS** | The stop loop begins at `entry_i`, after the explicit entry open, and checks the entry bar's high/low. The trade artifact records `stop_active_entry_bar = True`. |
| Gap/touch/same-bar ordering | **PASS** | On every stop-active bar, a gap beyond the stop fills at that bar's open; otherwise an OHLC touch fills at the exact stop trigger. A scheduled flip exit fills at its boundary/next-available open before that bar's intrabar range, so the stop loop excludes the scheduled-exit bar. There is no profit target and thus no stop/target tie path. |
| Hold through aligning flip; exit next flip against trade | **PASS** | For an ordinary prevailing regime, `confirm_flip_ns` is its end. Replay remains open across that aligning flip; the scheduled exit is the confirming regime's true end, the next flip against the countertrade. Stops remain active before and after confirmation. |
| Data-end censoring without future selection | **PASS** | The final open regime is retained and marked censored. It may originate a fully causal candidate; such a position receives no fabricated confirming flip, remains stop-active to data end, and is either `stop_before_flip` or censored. A penultimate-regime entry that confirms into the final regime is also replayed to data end, with post-confirmation stops or censoring. No candidate is excluded merely because a future exit flip is absent. |
| One-position overlap state | **PASS** | Candidates are ordered by decision. Decisions strictly before the current position-availability boundary are skipped. A stop-touch bar conservatively keeps the strategy busy through that 1-second bar; a scheduled market exit releases it at the known exit open, matching the frozen overlap rule. |
| No future labels enter filter | **PASS** | Stage-1 final PnL, peak MFE, giveback outcome, and winner labels are not loaded. Future regime boundaries are used only to expire a pre-flip order, update confirmation state, schedule the declared exit, and identify data-end censoring—not to compute entry filter values. Final-open candidates remain included, removing future-exit-availability selection. |
| Regime chronology | **PASS** | The current runner rebuilds the flip stream from raw 1-second data with a fresh per-year canonical `aggregate_and_run_regimes`/`RegimeEngine`, sorts and uniquely keys exact flip-close boundaries, and fail-fast checks direction against the causal score stream. Score groups key on exact regime start. Decisions at/after a real prevailing flip are rejected; actual fills must also precede that flip. Confirmation and exit use successive fresh-engine boundaries. The trailing open regime ends at the raw-data boundary with explicit censor state rather than a fabricated executable flip. |
| 2025-before-2026 sequencing | **PASS** | Every run requires this audit file to state PASS with zero findings. A 2026 run additionally requires the 2025 reconciliation file, the same policy hash, zero blocking errors, and zero closure residual. |
| No NT-native validation claim | **PASS** | SPEC, policy, runner, trade contract, analyzer, and report consistently label the work `EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT` / 1-second OHLC research simulation and explicitly reject an NT-native executable-validation interpretation. |
| Research limitations disclosed | **PASS** | The report disclaims exact intrabar ordering and tick/quote fill accuracy; states entry-bar stop activity; declares scheduled-exit priority; and notes there is no stop/target tie because no target exists. |
| Reporting and reconciliation | **PASS** | Every generated candidate routes to exactly one trade or named skip. The runner asserts candidate closure and zero blocking errors across duplicates, negative delays, wrong contract, stop distance, ATR, fill-after-flip, fill-window, exit chronology, exit/censor state, and exit-reason accounting. The analyzer reads both yearly reconciliations, verifies their hashes/closure/zero-error state, and refuses to report otherwise. |
| Path isolation | **PASS** | Inputs are frozen prior/upstream artifacts. Outputs remain under this study's `results` directory and the audit under its `audit` directory. |

## Causal state trace

For a qualifying checkpoint with `observation_time = T`:

1. The score uses the completed open-stamped 1-second bar `[T,T+1s)` and is available at `D = T+1s`.
2. Strict crossing is evaluated from the previous valid score to the current valid score.
3. The established filter at `D` uses only bars opening before `D`, hence completed by `D`.
4. If the filter is true and the strategy is flat at the decision boundary, an entry is scheduled for the first actual 1-second bar open at or after `D`.
5. A delayed fill is canceled if the old regime has already flipped or the authorized evaluation window has ended.
6. At the explicit entry open, the fill-anchored 1.5-ATR stop becomes active and the entry bar's range is eligible to touch it.
7. The first flip in the trade direction confirms/alines the countertrade but does not exit it.
8. The next flip against the countertrade schedules a market exit at its first available boundary open; that open has priority over the exit bar's range.
9. If the required future flip never occurs before data end, stops remain active and a surviving position is right-censored.

## Reconciliation contract

The yearly run must satisfy all of the following before it writes a clean reconciliation:

- `candidate_count = trade_count + skip_count`;
- no duplicate candidate regime;
- no negative decision-to-fill delay;
- every trade has the frozen research contract and policy hash;
- every trigger ATR is finite and positive;
- every realized stop distance is 1.5 ATR;
- no non-censored-origin fill occurs at/after its confirming flip;
- every fill lies inside its authorized monetization window;
- no exit precedes entry;
- completed trades have exit time/price and censored trades do not claim an exit fill;
- exit-reason counts sum exactly to accepted trades.

The analyzer independently consumes the two reconciliation files and checks their policy hashes, zero blocking errors, candidate closure, and exit-reason closure before calculating metrics or a decision.

## Resolved findings across audit passes

### Resolved CRITICAL — exact stop distance

Nearest-tick rounding was removed. The stop is now the exact fill-anchored 1.5-ATR level and is reconciled per trade.

### Re-audited numerical tolerance — PASS

The first authorized 2025 attempt closed candidate accounting exactly (`2,505 = 2,403 trades + 102 skips`) and reported zero errors in every reconciliation category except seven `realized_stop_atr` reconstructions whose absolute IEEE-754 error was between approximately `1.03e-12` and `1.09e-12` ATR. Independent inspection of all 2,403 trade rows confirmed a maximum error of `1.0935696792557792e-12` ATR, seven rows above `1e-12`, and zero rows above `1e-9`. Changing only the equality tolerance from `1e-12` to `1e-9` ATR does not change any stop level, touch, fill, trade, PnL, overlap state, or policy parameter. Persisting `max_stop_distance_error_atr` makes the numerical slack visible. This tolerance-only change is accepted; all causal and economic logic remains as previously audited.

### Resolved CRITICAL — censoring/future-exit selection

The initial implementation removed the final F1 regime and skipped penultimate entries that confirmed into it. An intermediate correction retained the final regime for exits but still prevented it from originating candidates. The final implementation handles both cases causally: penultimate-to-final and final-origin positions are stop-replayed through data end and survivors are censored.

### Resolved CRITICAL — overlap boundary

Overlap now compares candidate decision time—not delayed fill time—with the current position-availability boundary, so signals generated while busy cannot queue for later entry.

### Resolved CRITICAL — delayed fill after regime/window expiry

Every next-open fill is checked against the real confirming flip and authorized window; expired entries become named skips.

### Resolved CRITICAL — 2026 execution seal

The runner now requires a PASS audit for all runs and a same-hash, zero-error, closed 2025 reconciliation before opening 2026.

### Resolved CRITICAL — accounting closure

Silent candidate loss was removed. The runner and analyzer now fail closed on candidate accounting and timing/contract/state reconciliation.

### Resolved WARNING — ATR validity

Both regime ATR and trigger-checkpoint ATR must be finite and positive; invalid states cannot become trades, and accepted-trade ATR validity is reconciled.

### Re-audited regime-source repair — PASS

The first saved Stage-2 outputs were produced before the Stage-1 completion repair established that the cached flip-atlas `direction.fillna(regime)` source is unusable for 2025. Those saved outputs are invalid and must be replaced. The current `run_stage2_ohlc.py` no longer consumes atlas direction or regime identity: `load_regimes(year)` loads only the authorized year's raw 1-second OHLCV, aggregates sequentially to completed 1-minute bars with the canonical upstream `aggregate_and_run_regimes`, extracts flips from consecutive completed regime states, carries each flip's causal ATR/direction, and retains the final open regime with `regime_end_ns = raw data end` and `end_censored=True`.

The fresh engine is sequential and uses no future bar in a flip decision. Future flip boundaries are used only for the already-audited order-expiry, confirmation, scheduled-exit, and censor state. Candidate filter values remain causal prefixes at `decision_ts`; no outcome label is introduced. Before candidate construction, the runner joins fresh regime starts to the frozen causal score stream and asserts zero direction mismatch. Stage-1 artifact evidence shows complete coverage for all 27,138 validly scored 2025 regime keys (0 score keys absent from the fresh stream, 0 direction mismatches; 27 additional fresh completed regimes simply have no valid score and cannot trigger). The same fail-fast check runs independently for 2026 before any test candidate can be built.

The frozen policy file and snapshot remain byte-identical with SHA-256 `e290fe0726a309295b930eaeeba6cc491fd68cb21c186fd05cb4d55529fc8e7d`. No threshold, filter, stop, exit, cost, or reporting decision changed. The repaired current runner is authorized for a fresh 2025 run. The old 2025/2026 artifacts must not be used. 2026 remains sealed until the repaired runner produces a new clean same-hash 2025 reconciliation.

## Additional clean checks

- The Stage-1 gate artifact reports `ESTABLISHED_REGIME_FILTER_FOUND` before Stage 2.
- Threshold `0.6183278577387376` exactly matches the previously frozen W4 threshold.
- The policy has one filter, one W4 trigger, one 1.5-ATR stop, and one primary exit; no grid or optional secondary exit is implemented.
- Costs are fixed at $10 round trip and net PnL is decisive.
- Year, direction, session, and exit-reason reporting is implemented.
- Policy SHA-256 is carried per trade and checked by the final analyzer.
- Both Stage-2 scripts pass Python compilation.

## Final disposition

**PASS.** The current fresh-engine runner is authorized to re-execute 2025 under the unchanged frozen policy. The saved pre-repair Stage-2 artifacts are invalid. Execute 2026 only after the repaired runner produces a new clean same-hash 2025 reconciliation, then run the final analyzer. A new completion lookahead/execution-contract audit remains mandatory before the study is declared done.

---

## Loader re-audit (engine-derived regimes)

**Trigger:** `load_regimes()` (`run_stage2_ohlc.py:59-112`) was rewritten to stop reading `flip_context_atlas` F1 `direction` (100% NaN for 2021-2025, ~25% sign flips in the `regime` fallback where comparable — Stage-1 pass-2 audit CRITICAL) and instead reproduce regime identities from a fresh per-year `RegimeEngine` run on raw 1s data via `reproduce_regimes.aggregate_and_run_regimes`, matching the fix already applied and gate-confirmed in Stage-1 (`build_stage1.py:load_regime_population()`).

### Scope of the edit confirmed

Read `run_stage2_ohlc.py` end to end (all 424 lines) against this document's existing "Mandated checks" and "Causal state trace." Only `load_regimes()` differs from what this file already certified. `build_candidates`, `simulate`, `main`, `require_passed_audit`, `require_clean_2025_predecessor`, `progress_window_counts`, `POLICY_PATH`, `SCORES_PATH`, and `WINDOWS` are unchanged and match every bullet in the tables above line for line (strict crossing, `T+1s` availability, next-open entry via `searchsorted`, exact 1.5-ATR stop with `1e-9` tolerance, entry-bar stop activity, overlap `busy_until` state machine, censoring/right-censoring handling, and the full reconciliation gate). No other file (`analyze_stage2.py`, `common.py`) changed.

### 1. Construction convention matches Stage-1 / everywhere else

`regime_start_ns = int(r.close_ts)` (1m bucket close time from `aggregate_and_run_regimes`), `direction = int(r.regime)`, one fresh `RegimeEngine` per year — identical to the already gate-confirmed `build_stage1.py:load_regime_population()`. The one intentional divergence: Stage-1 discards the trailing open regime (`frows[:-1]`), Stage-2 retains it with `end_censored=True` and `regime_end_ns=data_end_ns` (`data_end_ns = last raw ts_event + NS`). This is not an inconsistency — it is required by Stage-2's own already-audited contract: the "Data-end censoring without future selection" bullet and causal-state-trace step 9 above already mandate that a final open regime be retained and eligible to originate a stop-replayed, right-censorable candidate. Confirmed `searchsorted(ts, data_end_ns, "left") == len(ts)` (one bar past the last raw timestamp), so the censored-tail path length in `build_candidates` runs through the full remaining array exactly as the non-censored path does through its true end.

### 2. Censored-tail semantics match what the audited replay expects

Traced `build_candidates` line 182 (`decision >= r.regime_end_ns` guard) and `simulate` lines 259-289 (`has_confirming_flip` / `prevailing_end_censored` branch) for both the ordinary-regime and censored-tail cases. `confirm_flip_ns=0` is an integer sentinel that is never compared on its own — every consumer branches on the boolean `end_censored`/`prevailing_end_censored` flag first, so the sentinel cannot be mistaken for a real boundary. Behavior for the censored tail (no fabricated confirming flip, stop-active replay to `data_end_ns`, `stop_before_flip` or `data_end_censored` outcome only) is identical to what this document already certified as PASS.

### 3. Parity fail-fast is sound, and empirically verified (not merely asserted)

- Checked `causal_scores.parquet` (`studies/fable5_pre_flip_d10_reversal_entry/_work/causal_scores.parquet`) directly: grouping by `(year, regime_start_ns)`, the maximum number of distinct `direction` values per group is 1 (0 groups with >1) — `drop_duplicates("regime_start_ns")` after year-filtering cannot silently pick an arbitrary/wrong direction.
- Both years the runner can be invoked with are present: `year==2025` has 3,959,663 rows, `year==2026` has 1,298,168 rows.
- Actually executed `load_regimes(2025)` and `load_regimes(2026)` (read-only; writes nothing to `results/` or `audit/`): 2025 produced 27,166 regimes (1 censored tail), 27,138 matched the score stream on `regime_start_ns` with **0 mismatches**; 2026 produced 8,935 regimes (1 censored tail), 8,922 matched with **0 mismatches**. Both the `assert not d.duplicated("regime_start_ns").any()` and the direction-parity assert passed live for both years. A coincidental 100% match across ~36,060 combined matched rows would not occur under the old F1-fallback semantics, which exhibited ~25% sign disagreement where comparable — this is strong evidence the fix is real, not merely asserted.

### Residual, non-blocking observation (NOTE, not WARNING)

`FLIP_ATLAS` is still imported at `run_stage2_ohlc.py:16` (`from common import FLIP_ATLAS, ...`) but is never referenced anywhere else in the file — a dead import, not a live data path. Grepped `fillna`, `regime`, `direction`, `FLIP_ATLAS`/`flip_context_atlas`, and `WEAKNESS_ATLAS` across both `run_stage2_ohlc.py` and `analyze_stage2.py`: no remaining consumer of the broken F1 direction/regime fallback exists in either file. Recommend dropping the unused import next time the file is touched; it carries no risk today since nothing reads `FLIP_ATLAS`.

### Disposition

0 CRITICAL, 0 WARNING against the rewritten loader and its interaction with the rest of the file. The causal mechanics this document already certified (candidate construction, next-open entry, stop, exit, windows, reconciliation) are unchanged and were re-read end to end with no discrepancy found. The direction-parity fail-fast is sound in design and passes on live data for both 2025 and 2026.

**Status line stands: PASS — STAGE 2 MAY RUN. 0 CRITICAL, 0 WARNING.**
