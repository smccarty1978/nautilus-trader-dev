# W4 Countertrade Path Diagnostic — Pre-Execution Audit

**Date:** 2026-07-15
**Scope:** `studies/w4_countertrade_path_diagnostic/SPEC.md`, `collect_paths.py`, `analyze_paths.py`, traced against their frozen read-only inputs (`studies/CODEX_5_X_weakness_atlas_repair/results/CODEX_5_X_established_fade_{2025,2026}_trades.parquet`, `.../CODEX_5_X_repaired_w4_scores_{2025,2026}.parquet`, `data/raw/NQ_v0_1s_2025.parquet`, `data/raw/NQ_v0_1s_2026_ytd.parquet`) and the upstream runner `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py` for semantic consistency.
**Mode:** read-only static analysis plus empirical spot-checks against the current frozen artifacts (no diagnostic code was executed; `collect_paths.py`/`analyze_paths.py` were never run). This is a **pre-execution** gate per the repo's pre-execution trigger rule for "stop/exit fill-timing mechanics ... reused from another study."
**Auditor:** lookahead-auditor v1

## Summary (original pass)

- Critical: 0
- Warning: 7
- Note: 2

No CRITICAL findings were confirmed. Two candidate issues that looked CRITICAL on static reading (invalid/non-finite W4 scores silently miscoded as "below threshold"; possible non-whole-second or malformed raw bars) were empirically checked against the actual frozen files and found to be currently clean — they are downgraded to WARNING (missing defensive gate, not a live corruption) per the instruction to not inflate severity. One WARNING (checkpoint/exit-timestamp coincidence) **is** confirmed live in the current frozen trade set, with measured price discrepancies up to ~6.2 points (~$124/trade) on the affected rows.

## Warnings (original pass — see Re-Audit section below for current disposition)

### [H1/B2 analogue — causal-quantity coding gap] `collect_paths.py:68-82, 190-217` — missing `score_valid` gate on the W4 score stream

`load_score_series()` reads `CODEX_5_X_repaired_w4_scores_{year}.parquet` with columns `["observation_time", "regime_start_ns", "w4_score", "direction_threshold"]` and does **not** load or filter on the `score_valid` column that the upstream runner treats as mandatory (`CODEX_5_X_run_established_fade.py:197-200`: `score_valid == np.isfinite(calibrated)` per `CODEX_5_X_train_repaired_w4.py:274`, and the runner hard-fails if any row in its own merged stream has `score_valid != True`).

If any row for a regime in `needed` (a trade's `regime_start_ns` or `confirm_flip_ns`) ever has a non-finite `w4_score`, `ScoreSeries.at()` returns that `NaN` as a legitimate observation. Downstream, `w4_fields()` computes `"w4_above_threshold": float(val >= thr)` (line 211) — a NumPy comparison against `NaN` evaluates to `False`, so `float(False) == 0.0` is written, **not** `NaN`. `analyze_paths.py`'s `frac()` helper (`analyze_paths.py:24-26`) does `series.dropna().mean()`, so this silently-wrong `0.0` is **not** dropped and is counted as a genuine "below threshold" observation, biasing `pct_w4_above_threshold`, `w4_last_above_threshold`, and (via the same unfiltered `aligned` series) the "first adverse W4 warning" detector at `collect_paths.py:346-352`, which would simply skip an invalid row instead of flagging it as untrustworthy.

**Empirical check (this audit):** read both `CODEX_5_X_repaired_w4_scores_2025.parquet` (3,934,266 rows) and `..._2026.parquet` (1,289,840 rows) in full, and the subsets restricted to `regime_start_ns` values actually referenced by the frozen trades (`needed` in `collect_paths.py`). **0 invalid / non-finite rows in either year, full or restricted.** So this cannot currently corrupt the diagnostic's first run — but it is an unenforced assumption on a "read-only frozen" artifact rather than a checked one, and the score export for other regimes (already shown to contain the column, hence the possibility) is not otherwise guaranteed to stay finite if the file is regenerated.

**Recommended fix (do not apply):** load `score_valid` alongside the other columns; either `raise` if any row within `needed` regimes has `score_valid == False`/`w4_score` non-finite (matching the upstream fail-closed convention), or explicitly drop such rows before constructing `ScoreSeries`, and make the `>= ` comparisons NaN-safe (`np.where(np.isfinite(val), val >= thr, np.nan)`) as defense in depth.

### [H4 analogue — checkpoint fill-price mismatch] `collect_paths.py:219-230, 261-278` — non-"exit" checkpoint rows that land exactly on `exit_fill_ts` use the wrong price

Every fixed-offset checkpoint (`entry`, `t+30s...t+300s`, `aligned_flip`, `flip+60s`, `flip+120s`) is only suppressed when `cp > exit_ts` (`collect_paths.py:264, 270`); when `cp == exit_ts` exactly, the row is still emitted as if the trade were merely "alive" at that instant, and `path_at(cp)` prices it from the generic mark `opens[searchsorted(ts, cp, "left")]` (line 226) rather than the trade's actual `exit_fill_px`. Only the dedicated `"exit"` row (line 274-278) gets the authoritative override (`pnl_pts_override=(exit_px - ep) * d`, `mfe_override=final_mfe`, `mae_override=final_mae`). For stop exits, `exit_fill_px` is the **stop trigger level** (or the gap-through open), not necessarily the next bar's open — so when a stop fires at exactly one of the fixed offsets, the "still alive" row and the "exit" row report two different prices for literally the same instant.

**Empirical check (this audit):** computed `hold_s = (exit_fill_ts - entry_fill_ts)/1e9` for every frozen trade (all hold times are exact whole seconds, confirming bar-boundary alignment) and counted exact matches against the offset set `{30, 60, 90, 120, 180, 300}`:

| Year | trades | 30s | 60s | 90s | 120s | 180s | 300s |
|---|---|---|---|---|---|---|---|
| 2025 | 3,246 | 0 | 7 | 4 | 7 | 4 | 4 |
| 2026 | 1,137 | 1 | 1 | 3 | 1 | 4 | 1 |

26/3,246 (2025, ~0.8%) and 11/1,137 (2026, ~1.0%) trades hit this coincidence. Spot-checking the generic-mark price against the real `exit_fill_px` for these exact rows showed discrepancies up to **6.22 points (~$124 at the $20/pt multiplier)**, mostly on `stop_before_aligned_flip`/`stop_after_aligned_flip` exits, in both directions (sometimes better, sometimes worse than the true fill). These rows would be silently mixed into `early_window_summary`'s "alive" `t+60s`/`t+120s` aggregates (`analyze_paths.py:71-104`) as if the trade were still open and unrealized, when it had in fact just been stopped out.

**Recommended fix (do not apply):** when building the offset/flip-offset checkpoint list, skip emitting the non-`"exit"` row if `cp == exit_ts` (the `"exit"` row already covers that instant with the correct price), or explicitly reuse the same `pnl_pts_override`/`mfe_override`/`mae_override` values for it.

### [G-analogue — data integrity, unenforced] `collect_paths.py:98-104` — no raw-bar OHLC geometry/finiteness validation

Unlike the upstream runner's `validate_raw_bars()` (`CODEX_5_X_run_established_fade.py:152-164`, checking finiteness and `H >= max(O,C)`, `L <= min(O,C)`), `collect_paths.py` loads `open/high/low` from the raw 1s parquet and only asserts the timestamp index is strictly increasing (line 100-101). No check on OHLC finiteness or geometry.

**Empirical check (this audit):** verified both `data/raw/NQ_v0_1s_2025.parquet` (12,083,801 rows) and `data/raw/NQ_v0_1s_2026_ytd.parquet` (4,255,466 rows) — all OHLC values finite, zero `high < low`, zero `high < open`, zero `low > open` violations. Currently clean.

**Recommended fix (do not apply):** port or import the upstream `validate_raw_bars` check (or at minimum assert finiteness and `high >= low`) before using `opens/highs/lows` for any mark or excursion computation. This matters specifically because `NQ_v0_1s_2026_ytd.parquet` is a year-to-date file that is expected to be extended/regenerated as 2026 progresses — the current cleanliness does not bind future re-runs.

### [A5/F3 analogue — unenforced whole-second contract] `collect_paths.py:99-101` — no assertion that raw timestamps are exactly whole-second aligned

The entire causality contract in `SPEC.md:19-25` ("All timestamps are whole seconds, so a bar with `ts_event < cp` is complete at checkpoint `cp`") is load-bearing for every `cp <= exit_ts`/`ts_event < cp` comparison in `collect_paths.py`, but there is no runtime check that `ts % NS == 0` for the loaded raw index — only strict monotonicity is checked.

**Empirical check (this audit):** `ts % 1_000_000_000 != 0` count is 0/12,083,801 (2025) and 0/4,255,466 (2026). Currently clean.

**Recommended fix (do not apply):** add `if np.any(ts % NS != 0): raise RuntimeError(...)` alongside the existing monotonicity assertion at line 100-101, so a future non-whole-second raw file (e.g. accidental sub-second data or a different bar spec) fails loudly instead of silently shifting every checkpoint boundary.

### [Provenance] `collect_paths.py:36-39, 92-109` — no hash verification against the frozen input contract before reading "read-only frozen" artifacts

The upstream runner treats its own inputs as bound by cryptographic hash (`validate_frozen_input_contract`, `require_passed_audits`, `require_clean_2025_predecessor` in `CODEX_5_X_run_established_fade.py`) and refuses to execute on any mismatch. `collect_paths.py` reads the same three artifact classes (raw 1s bars, established-fade trades, repaired W4 scores) with no equivalent check — only bar-existence assertions (`int(ts[i0]) != entry_ts`, etc., lines 128) and a trigger-score parity assertion (lines 184-188), neither of which would catch an in-place *revision* of existing timestamps' OHLC or score values (as opposed to missing/added rows).

**Empirical check (this audit):** recomputed SHA-256 of `data/raw/NQ_v0_1s_2025.parquet`, `data/raw/NQ_v0_1s_2026_ytd.parquet`, `CODEX_5_X_repaired_w4_scores_2025.parquet`, and `..._2026.parquet` and compared against the values frozen in `CODEX_5_X_policy_input_contract.json`. All four match exactly today.

**Recommended fix (do not apply):** before the first run, verify (and optionally hard-fail on mismatch) the same SHA-256 values already recorded in `CODEX_5_X_policy_input_contract.json` / `CODEX_5_X_established_fade_reconciliation_{year}.json`, especially given the `_ytd` raw file is explicitly a moving target as 2026 progresses.

### [Documentation/mislabeling risk] `collect_paths.py:284-363`, `analyze_paths.py:29-117` — retrospective quantities are not self-labeled in the saved summary artifacts

`path_checkpoints.parquet` correctly tags retrospective rows with `retrospective=True`/`False` (`collect_paths.py:232-273`). However, the per-trade scalar diagnostics (`peak_mfe_atr`, `t_peak_s`, `t_peak_to_exit_s`, `capture_ratio`, `giveback_from_peak_atr/usd`, `post_flip_peak_mfe_atr`, `t_flip_to_post_peak_s`, `post_flip_giveback_atr/usd`, all computed at `collect_paths.py:291-343`) and everything derived from them in `outcome_group_summary.parquet` and `post_flip_exit_diagnostic.parquet` carry **no equivalent marker**. A reader of these parquet files in isolation from `SPEC.md` (e.g., in a later study that imports them) could mistake `median_capture_ratio` or `median_giveback_from_peak_usd` for a causally realizable, actionable statistic rather than a full-trade-hindsight descriptor, in tension with the audit-focus requirement that retrospective quantities never be "silently used as if causal in the aggregations."

**Recommended fix (do not apply):** prefix retrospective-derived column names with `retro_` (or embed a `# retrospective` comment block / sidecar README in `results/`) so the distinction survives outside this script's docstring and `SPEC.md`.

### [Deliverable gap] `analyze_paths.py` — `results/final_report.md` and the SPEC-mandated decision label are never produced

`SPEC.md:63-71` lists `results/final_report.md` as an output and specifies a mandatory "Final decision label" (`NO_MANAGEMENT_EDGE_VISIBLE`, `EARLY_EXIT_DIAGNOSTIC_PROMISING`, `POST_FLIP_EXIT_DIAGNOSTIC_PROMISING`, `BOTH_EARLY_AND_POST_FLIP_MANAGEMENT_PROMISING`). `analyze_paths.py:main()` only writes the three summary parquets and prints tables to stdout — it never writes `final_report.md` and no code computes the decision label. This is not itself a causality bug, but it means a human must manually author the report after running the scripts; when doing so they must explicitly carry forward the retrospective-vs-causal distinction (see prior finding) and the survivorship framing (`pct_alive`, `n_alive`/`n_group_total` in `early_window_summary`) into the label's rationale, since nothing in the code enforces that discipline for text written after the fact.

## Notes (original pass)

### [Defensive coding] `collect_paths.py:211` — NaN-unsafe threshold comparison independent of the `score_valid` gap

Even after fixing the `score_valid` gap above, `"w4_above_threshold": float(val >= thr)` will keep converting any future NaN `val` to `0.0` rather than `NaN`. Recommend an explicit `np.isfinite` guard as defense in depth, not solely reliance on upstream filtering.

### [Informational] `collect_paths.py:157-171` — "old-regime new favorable extreme" window semantics confirmed correct

`pre_ext` is computed over `highs[r0:i0]`/`lows[r0:i0]` — i.e. strictly `[regime_start bar, trade_entry bar)`, excluding the entry bar — while `ext_prefix`/`run_mfe`/`run_mae` include the entry bar (`b_hi[:n_core]`/`fav[:n_core]` start at index `i0`). This is causally sound and intentionally asymmetric with the exit-bar exclusion: entry occurs at the bar's *open*, so any high/low within that same bar is realized at or after the entry instant (open-labelled bars begin with their open), whereas the exit-bar exclusion exists because a stop-touch bar's *low/high* ordering relative to the trigger cannot be resolved at 1s granularity. No fix needed.

## Clean checks (original pass)

- **A1/A2-analogue (causal as-of lookup).** `ScoreSeries.at(cp)` (`collect_paths.py:52-57`) correctly implements "latest observation with `observation_time <= cp`" via `searchsorted(..., side="right") - 1`, matching the documented upstream contract that a score at `observation_time=t` uses only data strictly before `t`.
- **B2/B4 (no forward-looking feature construction).** `path_at()` (`collect_paths.py:219-230`) restricts running MFE/MAE to `run_mfe[j-1]`/`run_mae[j-1]` where `j = searchsorted(b_ts, cp, "left")`, i.e. bars strictly before `cp` only; no `.shift(-N)` or negative-lag operation exists anywhere in either file.
- **Exit-bar exclusion, single-bar (`ie == i0`) edge case.** Verified by trace: `n_core = len(b_ts) - 1 = 0` when the entry bar is also the exit bar, so `run_mfe`/`run_mae` are empty and `path_at`/`final_mfe`/`final_mae` fall back correctly to `exit_fav`/`exit_adv` derived from the actual entry/exit prices, never indexing out of bounds.
- **Trigger-score parity.** `collect_paths.py:183-188` independently re-derives the frozen entry-trigger `w4_score` from the reconstructed `ScoreSeries` and hard-asserts exact match (`atol=1e-12`) — a genuine causal-reproducibility check, not a tautology.
- **Regime-identity correctness for the aligned lookup.** `aligned = series.get(confirm)` (`collect_paths.py:180`) correctly keys the post-flip W4 series by `regime_start_ns == confirm_flip_ns`, matching the documented "aligned regime post-flip" contract; `w4_fields()`'s `cp < confirm` branch selection is a clean, non-overlapping partition.
- **"First adverse W4 warning" causality.** `collect_paths.py:346-352` detects the first aligned-regime observation with `observation_time` in `(confirm, exit_ts]` and `val >= thr`; since each observation's `w4_score` is (by upstream contract) computed from data strictly before its own `observation_time`, using the observation timestamp itself as the causal detection instant is sound (matches how the upstream runner's own `strict_threshold_cross` treats `observation_time` as the decision instant).
- **Survivorship framing.** `early_window_summary()` (`analyze_paths.py:71-104`) explicitly carries `n_alive`, `n_group_total`, and `pct_alive` alongside every early-window statistic — the conditioning-on-survival is visible in the output table, not hidden.
- **Outcome-group / label usage.** `outcome_group` and `net_pnl_usd_final` are used exclusively as post-hoc grouping keys for retrospective attribution on already-closed, frozen trades (never fed back as an input feature to any causal computation) — consistent with the SPEC's explicit "no threshold optimization, no new policy backtest" guardrail.
- **Raw-file path consistency.** `RAW_1S` in `collect_paths.py:36-39` points at exactly the same files (`NQ_v0_1s_2025.parquet`, `NQ_v0_1s_2026_ytd.parquet`) as `CODEX_5_X_common.py:36-41`, and this audit's SHA-256 comparison confirms current bit-identity with the frozen input contract.
- **Censored-trade guard.** `collect_paths.py:95-96` hard-fails if any frozen trade has `NaN` `net_pnl_usd`/`exit_fill_ts`, correctly refusing to silently process a `data_end_censored` trade through path logic built for closed trades.

---

## Re-Audit (post-fix)

**Date:** 2026-07-15 (same day, second pass)
**Trigger:** coordinator applied fixes to `collect_paths.py` addressing findings 1-4 below (all line numbers refer to the current, fixed `collect_paths.py` unless stated otherwise). `analyze_paths.py` is unchanged.
**Method:** full re-read of the current `collect_paths.py`, line-by-line diff against the audited version, plus fresh empirical checks re-run against the frozen artifacts (independent of the coordinator's own claims).

### 1. Checkpoint/exit-timestamp coincidence — CLOSED

`collect_paths.py:306-319` now gates every fixed-offset checkpoint with a **strict** inequality against `exit_ts`:
- `t+Ns` offsets: `if cp < exit_ts:` (line 312), was `cp <= exit_ts`.
- `aligned_flip` row and `flip+60s`/`flip+120s` offsets: `if reached_flip and confirm < exit_ts:` (line 314) plus `if cp < exit_ts:` inside the flip-offset loop (line 318), was `reached_flip` alone (which only guaranteed `confirm <= exit_ts`).

Re-verified empirically: filtering the frozen trades by `hold_s` exactly matching `{30, 60, 90, 120, 180, 300}` still finds the same 26 (2025) / 11 (2026) trades identified in the original audit; under the new strict `<` condition, precisely the coincident offset is now skipped for each of these trades (no other offset for the same trade is affected). The "exit" checkpoint row remains the sole representation of the exit instant, still correctly priced from `exit_fill_px` via `pnl_pts_override`/`mfe_override`/`mae_override` (lines 322-326, unchanged).

I additionally checked for the analogous `confirm == exit_ts` edge case (a same-bar coincidence of the aligned flip and a stop touch, possible in principle per the upstream `simulate()` loop when `ts[i] >= confirm_flip_ns` and `touched` fire on the same iteration) — the new `confirm < exit_ts` guard on line 314 correctly closes this too, even though it does not currently occur in the frozen data (0/3,246 2025 trades and 0/1,137 2026 trades have `confirm_flip_ns == exit_fill_ts`). This is a case where the fix is more thorough than the literal finding required, which is appropriate defensive coding.

**On the coordinator's specific question (single-bar stop, `entry_ts == exit_ts`):** confirmed correct. The unconditional `"entry"` row (`collect_paths.py:309`) always reports `pnl_pts = 0`, `mfe = 0`, `mae = 0` by construction — `path_at(entry_ts)` marks at `opens[i0] == ep` (the entry fill price itself), so the zero is not an approximation or a stale "still alive" claim, it is the literal definition of unrealized PnL at the fill instant. This holds regardless of whether the same bar is also the exit bar. The `"exit"` row, emitted separately and unconditionally at line 322, correctly carries the real realized economics via its overrides. Both rows can coexist at `cp_ts == entry_ts == exit_ts` without contradiction because they answer different questions ("what was true the instant you entered" vs. "what was true the instant you left") — this is not the coincidence bug (which was two rows disagreeing about the *same* question, unrealized-mark-to-market, using two different pricing methods). **Agreed: no further fix needed for this case.** One residual note: `early_window_summary`'s `checkpoint.isin(["t+60s","t+120s"])` filter never touches `"entry"` rows, so this trivial-zero row cannot leak into any current aggregate; if a future consumer of `path_checkpoints.parquet` ever groups by `checkpoint=="entry"` expecting a non-degenerate distribution, they should be aware it is definitionally a point mass at zero.

**Disposition: CLOSED.** No remaining discrepancy found.

### 2. `score_valid` gate — CLOSED

`collect_paths.py:110-127` now loads `score_valid` alongside the other score columns and raises before constructing any `ScoreSeries` if `not scores["score_valid"].fillna(False).all() or scores["w4_score"].isna().any()` (line 117), scoped to exactly the `needed` regimes (post `.isin(needed)` filter at line 116) — matching the recommendation precisely (fail-closed, scoped to what's actually used, not the whole-file population). Re-confirmed empirically that the current `needed`-regime subsets for both years still contain 0 invalid rows, so this gate is provably inert today and will only fire if future data regenerates with a non-finite score in a referenced regime, which is the intended behavior.

**Disposition: CLOSED.**

### 3. `validate_raw_bars` — CLOSED (with one scope note, already disclosed)

`collect_paths.py:70-81` adds: DatetimeIndex + strict monotonicity check, whole-second alignment (`ts % NS != 0`), OHLC finiteness, and geometry (`h>=o`, `l<=o`, `h>=l`). Wired in at `collect_paths.py:144-145` before any bar values are used. Re-ran the same finiteness/geometry/whole-second checks independently against both raw files; all pass, consistent with what the new code will find at runtime.

Geometry is checked against `open` only (not `close`, since `close` is never loaded by this script — `columns=["open","high","low"]` at line 144). This is a narrower check than the upstream's `validate_raw_bars` (which also checks `close`), but it is the maximal check possible given the columns this diagnostic actually uses, and it is explicitly disclosed by the coordinator. Accepted as-is; no `close`-based excursion or mark is computed anywhere in `collect_paths.py`, so there is no causal exposure to unchecked `close` values.

**Minor robustness note (not blocking):** `validate_raw_bars` computes `ts = raw.index.view(np.int64)` (line 71) *before* checking `isinstance(raw.index, pd.DatetimeIndex)` (line 72). If `raw.index` were ever not a `DatetimeIndex`, `.view(np.int64)` could raise its own (less legible) exception before the intended `RuntimeError("...must be ordered and unique")` fires. This does not create a silent-success risk — the script would still fail loudly, just with a less informative message — so it is a NOTE, not a WARNING. Reordering the isinstance check first would be a trivial improvement.

**Disposition: CLOSED** (functionally); NOTE carried forward for message clarity only.

### 4. `verify_frozen_inputs` — CLOSED for raw + scores; residual limitation on trades (accepted)

`collect_paths.py:54-67` reads `CODEX_5_X_policy_input_contract.json`, checks `status == "FROZEN_BEFORE_POLICY_EXECUTION"`, and hard-compares SHA-256 of `RAW_1S[year]` and `CODEX_5_X_repaired_w4_scores_{year}.parquet` against the frozen `expected["raw"]`/`expected["scores"]` values, called at `collect_paths.py:143` before either file is otherwise read. Re-verified independently: computed SHA-256 of both raw files and both scores files and confirmed exact equality with the values in `CODEX_5_X_policy_input_contract.json` (same result as the original audit pass) — the gate will pass on the current artifacts and would correctly block on any future drift in the raw or scores bytes.

**Trades-parquet hash — confirmed unfixable as scoped, not a fix gap.** I checked `CODEX_5_X_policy_input_contract.json` (keys: `status`, `"2025"`, `"2026"`, `"common"`, each with only `raw`/`atlas`/`scores` or `manifest`/`bundle`/`first_open`) and `CODEX_5_X_established_fade_reconciliation_{2025,2026}.json` (records `input_hashes_current_year` for raw/atlas/scores/manifest/bundle/first_open, plus trade/candidate/skip *counts*, but no hash of the output trades parquet itself). There is genuinely no upstream-frozen hash of `CODEX_5_X_established_fade_{year}_trades.parquet` to check against — it is the runner's *output*, not a governed input, so no contract binds its bytes. The coordinator's framing (documented limitation, not a silent gap) is accurate. The existing `int(ts[i0]) != entry_ts`/`int(ts[ie]) != exit_ts` bar-existence assertions (lines 173) and the trigger-score parity assertion (lines 229-233) remain the only integrity checks on the trades file; they would catch a trades file referencing timestamps absent from the raw/score files, but not an in-place value revision at an existing, still-present timestamp.

**Optional (non-blocking) enhancement for the study author to consider when writing `final_report.md`:** self-record the SHA-256 of both trades parquets at first successful run (e.g., in a small provenance JSON alongside the diagnostic's own outputs) so that *subsequent* re-runs of this diagnostic can at least detect drift in the trades file relative to its own prior run, even without an upstream ground truth to compare to. This is a nice-to-have, not required to proceed.

**Disposition: CLOSED** for raw + scores (the two artifact classes that actually have a governing contract); trades-hash gap **downgraded from WARNING to accepted, documented residual limitation** — it was never closable within this diagnostic's own scope, and the existing bar-existence/parity assertions provide a meaningful (if partial) substitute.

### Findings deferred by design (not re-scored)

The coordinator explicitly deferred two items to the eventual `results/final_report.md` authoring step rather than fixing them in code now:
- **Retrospective-labeling in summary parquets** (original finding 5): coordinator states the forthcoming `final_report.md` will explicitly mark `capture_ratio`/`peak_mfe`/`giveback` columns as retrospective descriptors. Acceptable as a documentation-time mitigation; the underlying parquet columns will still lack a machine-readable marker, so this remains a WARNING against the *artifacts*, downgraded to NOTE against the *study* now that the mitigation plan is explicit and on record.
- **`final_report.md` / decision-label deliverable gap** (original finding 6): unchanged, explicitly acknowledged as pending, to be produced at the end of the study. Remains open by design, not a defect.

Both are non-causal (documentation/deliverable) items and do not gate execution.

### Re-Audit summary

| # | Finding | Original severity | Disposition | New severity |
|---|---|---|---|---|
| 1 | Checkpoint/exit-timestamp coincidence (t+Ns, flip+Ns, aligned_flip) | WARNING (confirmed live, ~1% of trades, up to $124/row) | **Fixed** — strict `cp < exit_ts` / `confirm < exit_ts`, re-verified against the same 37 previously-affected trades | Closed |
| 2 | Missing `score_valid` gate | WARNING (latent) | **Fixed** — fail-closed gate scoped to `needed` regimes | Closed |
| 3 | Missing raw OHLC geometry/finiteness validation | WARNING (latent) | **Fixed** — `validate_raw_bars`, open-relative geometry (close not loaded, by design) | Closed (+1 clarity NOTE) |
| 4 | Missing whole-second timestamp assertion | WARNING (latent) | **Fixed** — folded into `validate_raw_bars` | Closed |
| 5 | No hash verification vs. frozen input contract | WARNING (latent) | **Fixed for raw + scores.** Trades-parquet hash confirmed to have no upstream contract to check against — accepted residual limitation, not a fix gap | Closed (raw/scores) / documented limitation (trades) |
| 6 | Retrospective columns not self-labeled in summary parquets | WARNING | Deferred to `final_report.md` authoring, mitigation plan on record | Downgraded to NOTE (documentation-time) |
| 7 | `final_report.md` / decision label not produced | WARNING | Deferred by design, explicitly acknowledged, non-causal | NOTE (open by design, tracked) |

No new causal, look-ahead, or survivorship defects were introduced by the fixes. The fixes were narrowly scoped to exactly the reported findings plus one appropriately-defensive extension (the `confirm == exit_ts` edge case in finding 1), and did not touch any of the previously-confirmed clean checks (as-of W4 lookup, MFE/MAE windowing, exit-bar exclusion, trigger-score parity, aligned-regime identity, survivorship framing) — all re-read and re-confirmed unchanged in the current file.

---

## Completion Audit (post-execution)

**Date:** 2026-07-15 (same day, third pass)
**Trigger:** the study has now been executed end-to-end. Two changes since the Re-Audit: (1) `collect_paths.py` gained four new post-flip adverse-excursion fields (`post_flip_max_adverse_atr`, `post_flip_revisit_entry`, `post_flip_adverse_beyond_025_atr`, `post_flip_adverse_beyond_05_atr`), exported by `analyze_paths.py` into `post_flip_exit_diagnostic.parquet`; (2) `results/final_report.md` was authored with decision label `NO_MANAGEMENT_EDGE_VISIBLE`.
**Method:** re-read the current `collect_paths.py`/`analyze_paths.py` in full; independently re-derived every headline claim in `final_report.md` from the committed output parquets (not from the report's own prose) using fresh, from-scratch computations; cross-checked window boundaries both by code trace and by empirical recomputation against raw bars for a random sample of trades plus all edge cases.

### 1. New post-flip adverse-excursion fields — window boundaries CONFIRMED CORRECT

Code (`collect_paths.py:378-387`):
```python
post = b_ts[:n_core] >= confirm
post_fav = np.maximum(fav[:n_core][post], 0.0) if post.any() else np.empty(0)
post_adv = np.maximum(adv[:n_core][post], 0.0) if post.any() else np.empty(0)
post_max_adv = max(float(post_adv.max()) if len(post_adv) else 0.0, exit_adv)
diag["post_flip_max_adverse_atr"] = post_max_adv / atr
diag["post_flip_revisit_entry"] = post_max_adv > 0
diag["post_flip_adverse_beyond_025_atr"] = post_max_adv / atr >= 0.25
diag["post_flip_adverse_beyond_05_atr"] = post_max_adv / atr >= 0.50
```

- **Post window = core bars with `ts_event >= confirm`.** `b_ts[:n_core]` is exactly the same core-bar truncation used everywhere else in the file (`n_core = len(b_ts) - 1`, i.e. every bar from the trade's entry bar through the bar immediately before the exit bar) — the exit bar's own intrabar high/low is excluded from `post_adv`, consistent with the file's established, previously-audited "exit bar excluded from every MFE/peak computation" convention. `>= confirm` matches the existing `aligned_flip_occurred = cp >= confirm` convention used throughout (the flip instant itself counts as post-flip). This is the identical mask (`post`) already used for the pre-existing, previously-audited `post_flip_peak_mfe_atr`/`t_flip_to_post_peak_s`/`post_flip_giveback_*` fields — no new boundary logic was introduced, only a second reduction (`adv` instead of `fav`) over the same window.
- **Exit mark folded in via `exit_adv`, not exit-bar extremes.** `exit_adv = max((ep - exit_px) * d, 0.0)` (line 191, unchanged, computed once per trade from the actual realized `exit_fill_px`) is combined with `post_adv.max()` via `max(...)`, exactly mirroring how `post_peak` already folds in `exit_fav`. The exit bar's own `high`/`low` are never read for this purpose.
- **Adverse direction is relative to the trade's own entry direction (`d`), not the prevailing/faded direction (`p`).** `adv = ep - b_lo` (long fade) / `b_hi - ep` (short fade), i.e. "how far price moved against the position measured from the entry price" — the docstring's own gloss ("`>0` means price revisited the countertrade entry after the aligning flip") is accurate: `post_flip_revisit_entry` is true exactly when the post-flip low (long) / high (short) touches or crosses back through the entry price.
- **`post.any() == False` fallback exercised and correct.** Only one trade in the entire 4,383-trade dataset has an empty post-flip core window (aligned flip occurs on or after the last pre-exit bar); verified its `post_flip_max_adverse_atr` correctly falls back to `exit_adv / atr` alone.

**Independent empirical re-derivation:** recomputed all four fields from scratch (raw bars + frozen trades table, not from `collect_paths.py`) for 40 randomly sampled `reached_flip` trades (20/year) plus the single empty-post-window trade — **0/41 mismatches**, exact agreement to floating-point tolerance on `post_flip_max_adverse_atr` and exact boolean agreement on the three threshold flags.

**Disposition: CLEAN.** No window-boundary defect; matches the "three fixed descriptive levels, no level selection" framing (0.25/0.50 ATR reuse the existing `MFE_THRESHOLDS_ATR` convention already used for the pre-existing `reached_XXX_atr` fields).

### 2. `final_report.md` — causality and survivorship spot-checks

For each of the coordinator's five items, I independently re-derived the underlying numbers from the committed parquet outputs (`trade_diagnostics.parquet`, `path_checkpoints.parquet`, `post_flip_exit_diagnostic.parquet`) — not from the report's prose — to check both correctness and framing.

**(a) Forward-PnL-by-quartile analysis (kills the early-exit hypothesis).** Re-derived independently: for each checkpoint (`t+60s`/`t+120s`), restricted to alive-trade checkpoint rows (the same causal "alive" set audited clean in the Re-Audit), quartiled by the checkpoint's causal `pnl_atr`, and computed `forward_usd = gross_pnl_usd (final, retrospective) - pnl_usd (at checkpoint, causal)`. Result: AUC(eventual-stop | checkpoint PnL) = 0.781/0.764 at +120s for 2025/2026 (report: "0.78/0.76" ✓); quartile-mean forward PnL at +120s = {Q1 +$11.5, Q2 −$16.7, Q3 +$10.0, Q4 +$21.5} (2025) and {Q1 +$31.7, Q2 −$10.0, Q3 +$14.1, Q4 +$39.7} (2026), matching the report's stated figures essentially to the dollar. **Framing check:** the report correctly treats this as a *retrospective counterfactual test of a proposed rule* ("kills the early-exit hypothesis in expectation terms"), not a real-time signal, and explicitly separates "identity AUC" (real, causal, high) from "forward money" (flat, inconsistent sign) — this is exactly the "High AUC ≠ PnL discrimination" distinction the corpus has repeatedly required (see `MEMORY.md` "Fundamental Insight"). No overstatement found.

**(b) Pooled W4-warning-exit counterfactual.** Re-derived independently and reproduced the report's headline numbers **exactly**: restricting to the `warned_before_exit == True` subset of `reached_flip` trades, actual net = $290,762 vs. counterfactual net (exit at `pnl_at_warn_usd - $10`) = $261,285 for 2025 (report: "$261K vs $291K" ✓); $119,246 vs. $113,500 for 2026 (report: "$119K vs $113.5K" ✓). The counterfactual mark (`pnl_at_warn_usd`) and the warning-detection logic (`warned_before_exit`) are both causal quantities already audited clean (Re-Audit, original pass) — using them in a full-hindsight "what if this rule had fired" comparison is the correct, non-look-ahead way to evaluate a proposed exit rule against history. No overstatement found.

**(c) BE-at-flip envelope math.** Re-derived a natural version independently (exit at ~entry, net of $10, whenever `post_flip_revisit_entry` is true; actual outcome otherwise) and got delta ≈ **−$5,528 (2025) / +$7,330 (2026)**, matching the report's "≈ −$5K worse / ≈ +$7K better" almost exactly. **Framing check:** this is the most conservatively-labeled claim in the report — flagged as speculation at first mention ("under generous exact-at-entry fills"), reiterated in §5 ("generous fills"), and explicitly separated into the "Speculation" bullet of the Limitations section ("assumes exact-at-entry exit fills, ignores gap-through and re-entry effects; not a simulation"). This matches the audit-focus requirement precisely — the report never treats this number as evidence of an edge, only as a rough plausibility check that even a generous version of the idea is a wash. No overstatement found.

**(d) Retrospective columns listed in the scope-guards paragraph — INCOMPLETE (WARNING).** The paragraph (`final_report.md:14-18`) lists `peak_mfe_*`, `capture_ratio`, `giveback_*`, `post_flip_peak_*`, `post_flip_max_adverse_*`, `t_peak_*` as retrospective. Read as literal prefix patterns (as the glob-style notation implies), this list does **not** cover several other hindsight-derived columns that are just as retrospective and are present in the same parquet files:
  - `final_mae_atr` (max adverse excursion over the *entire* trade — the adverse-side twin of `peak_mfe_atr`, which *is* listed).
  - `old_regime_new_extreme_ever` / `t_old_regime_new_extreme_s` (requires seeing the whole trade to know whether the old regime *ever* made a new extreme).
  - `reached_025_atr` / `reached_05_atr` / `reached_075_atr` / `reached_10_atr` (all derived from `final_mfe`, i.e. full-path hindsight, despite the name not containing "peak" or "mfe").
  - `w4_last_preexit` / `w4_last_staleness_s` / `w4_last_above_threshold` / `w4_change_entry_to_last` ("last observation *before exit*" is bounded by the not-yet-known exit time).
  - `t_flip_to_post_peak_s` (does not literally start with `post_flip_peak_*`, though it is the timing companion of a listed field).
  - `warned_before_exit` / `t_flip_to_warn_s` / `pnl_at_warn_usd` (whether *any* warning fired "before exit" is bounded by the not-yet-known exit time, even though each individual warning observation is itself causal).
  - **Three of the four brand-new fields from this round**: `post_flip_revisit_entry`, `post_flip_adverse_beyond_025_atr`, `post_flip_adverse_beyond_05_atr` do not literally match the stated `post_flip_max_adverse_*` pattern (only `post_flip_max_adverse_atr` itself does).

  This partially undermines the specific mitigation the coordinator implemented to close the original audit's finding 6 ("retrospective columns not self-labeled"). It is a documentation-completeness gap, not a computational defect — none of these columns are used anywhere in the report as if they were causal, and the report's prose elsewhere (survivorship caveat, "definitional" caveat, per-item hedging on (a)/(b)/(c) above) provides substantial independent protection against misuse. Severity: **WARNING**, not CRITICAL — recommend replacing the enumerated list with a structural rule (e.g. "every column in `trade_diagnostics.parquet` other than `entry_direction`, `session`, `atr_at_checkpoint`, `w4_entry`, `w4_threshold`, `pnl_at_flip_*`, `t_flip_s`, `reached_flip`, and the `w4_*` fields on `path_checkpoints.parquet` checkpoint rows with `retrospective=False`, is a retrospective, full-path descriptor") before this report or its parquet outputs are cited outside this study.

**(e) "% flipped = 0 for stop_before is definitional" caveat — CONFIRMED CORRECT.** `final_report.md:88-89`. Verified mechanically: a `stop_before_aligned_flip` trade's `exit_ts` is by definition strictly before `confirm_flip_ns`; every surviving checkpoint row for such a trade requires `cp < exit_ts < confirm`, so `aligned_flip_occurred = cp >= confirm` is `False` for every single row of every trade in that group — `pct_flipped` is mechanically `0/n = 0%` by construction, carrying zero empirical information. The caveat correctly warns readers not to read this as "these trades don't flip within the window" (an empirical claim) when it is actually "these trades cannot flip before they've already exited" (a tautology of the grouping definition). This is exactly the kind of definitional-vs-empirical distinction the audit charter requires, and it is stated plainly and directly adjacent to the number it qualifies. **Clean — exemplary, no issue.**

### 3. Additional checks beyond the coordinator's five items

- **Header reconciliation.** "2025 development: 3,246 trades, net −$17,609; 2026 final test... 1,137 trades, net +$7,596" — recomputed directly from the frozen CODEX trades parquets: exact match ($-17,609.0$ / $7,595.8$, rounds to $7,596$).
- **Outcome-group table spot-check.** 2025 `stop_before_aligned_flip` row: recomputed n=1,107, mean net −$322.5, median peak MFE 0.33 ATR, %≥0.25=58.7%, %≥0.50=34.3%, median t_peak=23s — all match the table exactly.
- **"98% W4 collapse" / "11-12% new extreme" claims** — recomputed `w4_last_above_threshold` (fresh-only) and `old_regime_new_extreme_ever` for `stop_before_aligned_flip`: 2%/0.9% above threshold (i.e. ~98%/~99% collapsed) and 11.4%/11.9% new-extreme — both match the report's stated ranges.
- **Post-flip revisit percentages** — recomputed by `outcome_group`: losers 99.1%/98.4%, `stop_after` 100%/100%, winners 36.9%/38.7% (2025/2026) — matches "98–100% losers... 37–39% winners" exactly, including the 0.50-ATR-buffer figures (75.6%/71.8% for losers, matching "72–76%").
- **Artifact counts.** `path_checkpoints.parquet` = 44,252 rows across 4,383 trades — matches the report's Artifacts section exactly, including the per-checkpoint breakdown being consistent with "up to 12 checkpoints" (entry + up to 6 offsets + aligned_flip + 2 flip-offsets + peak_mfe + exit = 12, with attrition from trades that exit before reaching a given offset).
- **Trades-hash disclosure.** The report's own Limitations section ("The trades parquet itself is a runner output with no upstream hash contract, verified only by exact PnL reconciliation") independently states the exact residual limitation identified in Re-Audit finding 4 — confirms the study team carried that finding forward correctly into the write-up.
- **No evidence found of any table, claim, or recommendation treating a retrospective/hindsight quantity as a real-time-executable signal.** The proposed next steps (H1/H2, §7) are explicitly gated behind "Safe Exit Replay Framework, matched-placebo controls, and a pre-execution audit" before any further pursuit, and are labeled "Expectation: LOW" — appropriately hedged, consistent with the repo's established causal-testing discipline (`MEMORY.md`: grid-tune/validate separation, matched-donor placebo requirements).

### Completion-Audit summary

| Item | Result |
|---|---|
| New post-flip adverse fields — window boundaries | CLEAN — empirically confirmed 0/41 mismatches (including the one empty-post-window edge case) |
| (a) Forward-PnL-by-quartile / AUC | CLEAN in framing; numbers independently reproduced; **not implemented as committed, re-runnable code** (WARNING, reproducibility) |
| (b) Pooled W4-warning counterfactual | CLEAN in framing; numbers reproduced exactly; **same reproducibility gap** as (a) |
| (c) BE-at-flip envelope | CLEAN — correctly and repeatedly labeled speculation with disclosed assumptions |
| (d) Scope-guards retrospective-column list | **WARNING — incomplete**, partially undermines the intended mitigation of original finding 6 |
| (e) "% flipped = 0 ... definitional" caveat | CLEAN — mechanically verified correct and well-placed |
| Header/table/artifact reconciliation | CLEAN — every spot-checked number matches independent recomputation |

**New WARNING (process, this pass):** the specific aggregations behind (a) and (b) — forward-PnL-by-quartile, the eventual-stop AUC, and the pooled warned-subset counterfactual total — exist only as ad hoc computations reflected in `final_report.md`'s prose; there is no committed script (`analyze_paths.py` or otherwise) that reproduces them mechanically. I independently re-derived all of them from the committed parquet outputs and found exact or near-exact agreement, so there is no evidence of miscalculation or a hidden defect — but per this repo's reproducibility principle ("Any NT user should be able to clone this repo and replicate results exactly"), these headline numbers are not currently one-command-reproducible. Recommend adding a small `analyze_paths_report.py` (or extending `analyze_paths.py`) that computes and saves these three quantities before this report is relied upon beyond internal diagnosis.

No CRITICAL or causally-live WARNING findings were identified in this pass. The two new WARNINGs (scope-guards list completeness; forward-PnL/AUC/counterfactual reproducibility) are both documentation/process items, independently verified not to reflect any computational error, look-ahead bias, or survivorship artifact in the underlying data.

---

## Final Status (updated after Completion Audit)

**PASS.**

**0 CRITICAL, 2 WARNING (process/documentation, non-blocking, independently verified non-causal), 3 NOTE.** `collect_paths.py`'s new post-flip adverse-excursion fields are causally and boundary-correct (empirically confirmed). `results/final_report.md`'s decision label `NO_MANAGEMENT_EDGE_VISIBLE` is well-supported: every spot-checked claim — including all five items the coordinator flagged for retrospective-vs-causal review — was independently re-derived from the committed parquet outputs and found numerically accurate and appropriately hedged between "evidence" (causal-input, hindsight-outcome counterfactual tests, correctly framed) and "speculation" (explicitly and repeatedly labeled). No overstatement of causality, no un-caveated survivorship artifact, and no new look-ahead bias were found anywhere in the study as executed.

Before closing the study out or citing it to justify any of the H1/H2 follow-on hypotheses: (1) broaden or replace the scope-guards retrospective-column list per finding (d) above; (2) consider committing the forward-PnL/AUC and pooled-counterfactual computations as reusable code per the new process WARNING. Neither is required to accept the current `NO_MANAGEMENT_EDGE_VISIBLE` conclusion, which this audit independently corroborates.
