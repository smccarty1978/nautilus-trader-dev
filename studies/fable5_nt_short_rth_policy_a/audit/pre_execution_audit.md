# Pre-Execution Look-Ahead & Timestamp Audit — Fable 5 NT Short-RTH Policy A (Phase 1)

**Date:** 2026-07-17
**Scope:** `studies/fable5_nt_short_rth_policy_a/{common.py, build_schedule.py, strategy.py, run_nt.py, tests/test_policy_a_fixture.py, reconcile.py}`. Read for context (imports / reused execution stack / offline ground truth, per CLAUDE.md's "audit reused-verbatim components" directive): `studies/fable5_pre_flip_d10_reversal_entry/{strategy.py, run_nt.py, test_fill_fixture.py, audit/pre_execution_lookahead_audit.md}`, `studies/CODEX_5_X_weakness_atlas_repair/{CODEX_5_X_run_established_fade.py, CODEX_5_X_common.py, CODEX_5_X_established_fade_policy.json}`, `studies/codex_5_w4_fade_confirmation_clock_isolation/{run_isolation.py, policy_freeze.json}`, `studies/codex_5_w4_policy_a_residual_loss_attribution/{config.json, input_freeze.json, results/final_report.md}`, `studies/_shared_exit_mgmt/bar_source_reconciliation_report.md`.
**Trigger:** pre-execution gate for new NT strategy + new state machine (confirmation-clock alignment/timeout hysteresis) before its first full-year run, per CLAUDE.md's pre-execution trigger for "state-smoothing / hysteresis state machines" and "stop/exit fill-timing mechanics ... reused from another study."
**Auditor:** lookahead-auditor v1

## Summary (Pass 1, superseded — see Pass 4 for current state)

- Critical: 1
- Warning: 1
- Note: 3

## Critical findings (Pass 1)

### [D1 / G1, cross-file identity gap] No parity check between the live NT `RegimeEngine`'s flip sequence and the frozen schedule's regime sequence; catalog and raw-file are two unverified-identical data sources, and Policy A's entire exit-management surface depends on their agreement

`strategy.py:71` instantiates a fresh `RegimeEngine()` (imported verbatim from `studies/fable5_pre_flip_d10_reversal_entry/strategy.py:46-48`) and feeds it exclusively from `run_nt.py:45-47`'s `ParquetDataCatalog(str(C.CATALOG_PATH))` where `CATALOG_PATH = data/catalog/NQ_v0_2020_2026` (`common.py:13`). This live engine is the **sole** source of every exit-management decision in Phase 1: alignment (`strategy.py:204-211`), the pre→post stop swap (`strategy.py:228-237`), and the opposing-flip exit (`strategy.py:221-225`). Entries, by contrast, are immune — they come from the frozen schedule's `target_fill_ts` (`build_schedule.py:26`, sourced from `CODEX_5_X_established_fade_{year}_trades.parquet`, `common.py:14`, which is a `frozen_trade_path` product of `CODEX_5_X_run_established_fade.py`, itself run against `RAW_1S[year] = data/raw/NQ_v0_1s_{year}(_ytd).parquet` (`CODEX_5_X_common.py:36-41`) — a **different file** from the catalog.

No artifact anywhere in this study's scope compared the live engine's realized flip timestamps against any offline-derived ground truth. The infrastructure to do so existed but was unused for validation: `self.flips` (`strategy.py:93,197-198`) logs every live flip, and each trade carries `recon_confirm_flip_ns` (`strategy.py:114,296`, documented as reconciliation-only and correctly never read by a decision — confirmed clean).

This was not a hypothetical concern for this instrument: project memory (`hhll_exit_overlay_finding.md`) documents "NQ catalog bars ≠ raw tick file on roll days — 100-250pt gaps," and the immediately-preceding sibling study using this exact same reused `RegimeEngine`/catalog architecture (`fable5_pre_flip_d10_reversal_entry`) hit exactly this failure mode in its own Pass-2 pre-execution audit (rated CRITICAL there). 2025 and 2026 (through April) between them span five quarterly roll boundaries (Mar/Jun/Sep/Dec 2025, Mar 2026).

**PASS 4 STATUS: RESOLVED, verified across Pass 2/3.** `reconcile.py`'s `flip_parity()` fail-fast gate closes this; see Pass 2/3 for the fix history and confirmation of the final correct implementation.

## Warnings (Pass 1)

### [H-adjacent / stop-fill-timing] Unverified same-`ts_init` tie between the last 1s bar of a minute and its parent 1m bar could let a cancel-then-exit sequence preempt an already-triggered resting stop

1m bars carry `ts_init = ts_event + 60s` and 1s bars carry `ts_init = ts_event + 1s`. For the **last** second of any minute, the 1s bar's `ts_init` is identical to the parent 1m bar's `ts_init` — a genuine dispatch-order tie, not a magnitude ordering. Both `_swap_to_post_stop` (`strategy.py:228-237`, alignment path) and `_submit_exit` (`strategy.py:239-257`, used for both `confirmation_timeout` and `opposite_flip`) unconditionally call `self._cancel_stop()` before submitting a new order. If, on a tied last-second-of-minute bar, that bar's own high/low would have triggered the currently-resting stop **and** the 1m bar is dispatched before the tied 1s bar's own intrabar stop resolution is delivered, the unconditional `_cancel_stop()` could cancel a stop that "should" have already fired. Inherited verbatim from the sibling `fable5_pre_flip_d10_reversal_entry` study's own unresolved Pass-2 Warning, and explicitly outside `tests/test_policy_a_fixture.py`'s stated coverage.

**PASS 4 STATUS: RESOLVED via measurement + disclosure (the agreed resolution strategy for this Warning), with one epistemic caveat carried forward as a Note.** See Pass 4 below for the full fix history (Pass 2/3 partial fixes) and final assessment.

## Notes (Pass 1, still open — informational, non-blocking)

### `build_schedule.py:31-32`, `strategy.py:114-115,296-297` — `recon_confirm_flip_ns`/`recon_scheduled_exit_ts` correctly never read by any decision path (confirmed clean, documented for completeness)

### `common.py:29-34` (`RTH_END_MIN`) — disclosed definitional deviation from task text, not a look-ahead issue

### `strategy.py:377-387` (`on_order_denied`) — stop-order handling omitted, unlike its `on_order_rejected`/`on_order_canceled` peers. Low severity, defensive-coding only.

---

# Pass 2 — `reconcile.py` review (2026-07-17)

Identified two defects in the first version of `reconcile.py`: (1) `flip_parity()`'s `.iloc[1:]` erroneously dropped the year's first genuine flip from the offline side, guaranteeing a spurious `SystemExit` on every run; (2) `tie_detection()` only measured the opposing-flip/post-stop half of the race, using a tautological minute-boundary check and a close-price-only proxy instead of true intrabar excursion.

Clean checks reconfirmed: `reconcile.py` is purely post-hoc/non-causal (no output feeds back into any `strategy.py` decision); the trade-level join key (`target_fill_ts` ↔ `entry_fill_ts`) has single, consistent provenance; `align_ts_delta_ns`/`align_match` are correctly computed diagnostics; the offline source (`isolation_trade_diffs.parquet`, `policy_id="POLICY_A_COMBINED_1P25_300S"`) is confirmed to be the correct causal reference implementation of Policy A, not the unrelated single-1.5-ATR `established_fade` policy; `roll_windows` uses a standard 3rd-Friday-of-quarter IMM convention.

---

# Pass 3 — re-verification of the flip_parity and tie_detection fixes (2026-07-17)

**Fix 1 (flip_parity off-by-one) — CONFIRMED RESOLVED.** The `.iloc[1:]` slice was removed; the updated comment correctly explains that `canonical_regime_timeline`'s `previous != 0` filter and `strategy.py`'s own flip-detection gate (`prev != 0 and new != 0 and new != prev`) *independently* already exclude the warmup-born transition, so both streams were already flip-for-flip comparable. The gate now only raises `SystemExit` on a genuine out-of-roll-window mismatch.

**Fix 2 (tie under-measurement) — substantially resolved, one residual gap identified.** The rewritten `tie_detection` replaced the tautological `at_min` check and the close-price proxy with the intrabar running-max `mae_atr` compared against the actually-active stop level, correctly covering: (a) `post_race` — aligned trades exiting `opposite_flip` whose `mae_atr` reached the 1.50-ATR post-stop; (b) `pre_race` — never-aligned trades exiting `confirmation_timeout` whose `mae_atr` reached the 1.25-ATR pre-stop. Residual gap identified: neither check covered a trade whose pre-stop was breached (1.25-1.49 ATR) on the same tied bar as a flip that goes on to **successfully align** — `pre_race` requires `~aligned` and `post_race` requires reaching the higher 1.50-ATR bar via an `opposite_flip` exit specifically, so this third sub-case was invisible to both. Recommended a `mae_atr_at_align` snapshot in `strategy.py`, taken inside `_swap_to_post_stop` before further excursion accumulates.

---

# Pass 4 — re-verification of the `mae_atr_at_align` fix (2026-07-17)

**Scope (Pass 4):** `studies/fable5_nt_short_rth_policy_a/{strategy.py:228-237,282-307, reconcile.py:225-268}`, re-read in full. **Trigger:** coordinator-reported third-sub-case fix; coordinator reports Phase 1 execution is proceeding concurrently with this re-verification. Nothing executed as of this pass.

## Change 1 (`strategy.py`) — confirmed diagnostic-only, correctly placed

```python
def _swap_to_post_stop(self, t: dict):
    t["mae_atr_at_align"] = float(t["mae_atr"])   # strategy.py:233
    self._cancel_stop()
    ...
```

Grepped `mae_atr_at_align` across the study: it is written exactly once (`strategy.py:233`, inside `_swap_to_post_stop`, before `_cancel_stop()` and the post-stop order submission), initialized to `None` at trade creation (`strategy.py:304`), and read exactly once, in `reconcile.py:252` — never in a conditional, order-submission argument, or any other decision path in `strategy.py`. Confirmed: this cannot introduce look-ahead or alter strategy behavior, exactly as the coordinator described. Since `_swap_to_post_stop` runs unconditionally on every alignment (`strategy.py:211`), every aligned trade gets a non-`None` snapshot; non-aligned trades correctly keep `None` (filtered out by `reconcile.py`'s `p.aligned &` gate downstream).

## Change 2 (`reconcile.py`) — confirmed correctly wired

```python
maa = pd.to_numeric(p.get("mae_atr_at_align"), errors="coerce")
pre_align_race = p.aligned & maa.notna() & (maa >= preflip_atr - eps)
```

Correctly scoped to aligned trades only, uses the same `eps` tolerance and the same `preflip_atr` constant (`C.PREFLIP_STOP_ATR`) as the strategy's actual pre-stop, and reports both count and summed `net_pnl` (`pre_align_race_pnl`), matching the "quantify the residual, don't hide it" pattern already established for the other two race checks.

## Assessment — does this fully close the Warning?

Yes, accepted as closing the Warning at the resolution bar already agreed in Pass 2/3 ("measurement + disclosure is an adequate strategy for this Warning; a strategy-level code change is not required"), with one carried-forward epistemic caveat, downgraded to a Note rather than kept as a blocking Warning:

**Note (carried forward, non-blocking):** the coordinator's stated justification — "because 1s bars up to a minute close are processed before that minute's 1m flip, `mae_atr` already includes all pre-alignment excursion at that point" — is the standard, documented dispatch-order convention used throughout this project (CLAUDE.md's "Common Pitfalls #7," the MFE/MAE collector pattern, and this same convention independently assumed by the sibling `fable5_pre_flip_d10_reversal_entry` study). It is *not*, however, a convention that has ever been empirically fixture-verified for this specific engine configuration (`bar_execution=True, bar_adaptive_high_low_ordering=True`) when a 1-minute and a 1-second `BarType` share an exact `ts_init` — the sibling d10 study's own Pass-2 audit explicitly left this exact question open as an unresolved (non-blocking) Warning, and no fixture in either study has since closed it. This means `mae_atr_at_align`'s completeness *for the single tied bar itself* (as opposed to all strictly-earlier 1s bars in the trade's pre-alignment life, which are unambiguously included regardless of this convention) inherits the same underlying uncertainty that motivated the original Pass-1 Warning. This is not a new or distinct gap — it is the same one, now reduced to its irreducible core (a single engine-dispatch-order fact that only a dedicated fixture test, mixing 1m+1s `BarType`s with a constructed tied-boundary scenario, can settle) rather than a measurement-completeness defect that static review can fix. Recommend adding that fixture test at some point (non-blocking, nice-to-have follow-up, shared with the sibling study's own identical open recommendation) — but it does not need to happen before Phase 1, given the "measurement + disclosure" bar was already the agreed resolution path and all three sub-scenarios are now measured to the fullest extent achievable without that fixture. A near-zero `pre_align_race_flags` (and `pre_stop_race_flags`, `post_stop_race_flags`) count in the Phase 1 output should be read as "no candidate trades detected under the standard dispatch assumption," which is adequate disclosure, not as an engine-level proof of zero risk.

## Clean checks (Pass 4)

- `mae_atr_at_align` never appears in any `if`/comparison/order-construction expression in `strategy.py` (grep-confirmed, single write site, single read site in `reconcile.py`).
- Trade-dict initialization (`strategy.py:304`) correctly pre-seeds `mae_atr_at_align: None` so non-aligned trades produce a clean `NaN` in `trades.parquet` rather than a missing column/KeyError.
- `reconcile.py`'s three race checks (`post_race`, `pre_race`, `pre_align_race`) are mutually exclusive by construction (`aligned` vs `~aligned`, and distinct `exit_reason` gates for the first two), so their counts/PnL can be safely summed for a total "candidate race trades" figure if wanted, without double-counting.

## Final status

- **CRITICAL:** 0. The cross-file identity/parity gate (`flip_parity`) is correctly implemented and verified across Pass 2/3.
- **WARNING:** 0. All three race sub-scenarios (post-stop/opposing-flip, pre-stop/timeout, pre-stop/successful-alignment) are now measured via a consistent, non-causal, intrabar-excursion-based diagnostic that reports count and PnL rather than silently ignoring the risk. The remaining uncertainty (exact same-`ts_init` 1m-vs-1s dispatch order, for the single tied bar) is carried forward as a **Note** — a known, disclosed, non-blocking limitation of what static analysis and post-hoc measurement (short of a dedicated engine fixture test) can settle, consistent with the already-agreed resolution strategy for this finding.
- No new findings introduced by this pass.

*Audit complete (Pass 4). Findings reflect read-only static analysis. Dynamic/runtime behavior remains unverified as of this writing — the coordinator reports Phase 1 execution is proceeding concurrently with this pass.*

**Status:** **PASS**
**Findings:** **0 CRITICAL, 0 WARNING**
