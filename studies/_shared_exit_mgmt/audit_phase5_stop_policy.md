# Look-Ahead & Timestamp Audit — Phase 5/6 Stop-Policy Mechanics (Pre-Execution)

**Date:** 2026-07-11
**Scope:** NEW, not-yet-executed code (pre-execution gate per CLAUDE.md "stop/exit fill-timing mechanics" rule)
- `studies/_shared_exit_mgmt/stop_policy.py`
- `studies/_shared_exit_mgmt/policy_strategy.py`
- `studies/_shared_exit_mgmt/policy_grid.py`
- `studies/all_flips_exit_management/policy_strategy.py`
- `studies/f2_confirmed_exit_management/policy_strategy.py`
- `studies/_shared_exit_mgmt/nt_runner.py` (`strategy_post_init` addition only)

Read for context only, unmodified/trusted (NOT re-audited except at the exact
interaction points requested):
- `studies/_shared_exit_mgmt/base_strategy.py`
- `studies/_shared_exit_mgmt/w0_features.py`
- `studies/_shared_exit_mgmt/stop_state_features.py`
- `studies/_shared_exit_mgmt/mfe_mae.py`
- `studies/_shared_exit_mgmt/train_model.py`
- `studies/_shared_exit_mgmt/conditional_stop_tables.py`
- `studies/_shared_exit_mgmt/build_atlas.py`
- `studies/all_flips_exit_management/strategy.py`, `studies/f2_confirmed_exit_management/strategy.py` (trivial mixin composition, confirmed no MRO issue)

**Auditor:** lookahead-auditor v1

## Summary

- Critical: 2
- Warning: 3
- Note: 4

No driver script yet exists that instantiates `StopPolicyEngine` and calls
`run_period(..., strategy_post_init=...)` — this confirms the code truly has
not been executed end-to-end. Findings below are static-analysis only.

---

## Critical findings

### [Item 7 / new] `stop_policy.py:81-83` — `decile_of` (searchsorted) does not match the offline `pd.cut` boundary convention used to build the frozen table

```python
def decile_of(self, prob: float) -> int:
    idx = int(np.searchsorted(self.decile_edges, prob, side="right"))
    return max(1, min(10, idx))
```

Offline (`train_model.py:112`, the code path that produced `decile_edges` and
every `decile` column the conditional tables were aggregated over):

```python
decile = pd.cut(p, bins=edges, labels=False, include_lowest=True) + 1
```

`pd.cut` (default `right=True`) bins are **left-open, right-closed**:
`(edges[i], edges[i+1]]`. A probability exactly equal to an interior edge
value falls into the **lower** decile.

`np.searchsorted(edges, prob, side="right")` counts edges `<= prob`. A
probability exactly equal to an interior edge value is counted as `<=`
**two** edges (the edge itself and everything below it), pushing it into the
**next** decile up.

Concretely: if `prob == edges[k]` exactly, `pd.cut` assigns decile `k`
(0-indexed bin `k-1`, +1 = `k`), while `decile_of` assigns decile `k+1`.

This is not a theoretical nitpick. The decile edges are themselves exact
quantile cut-points of the **train** prediction distribution (`pd.qcut` on
`p_train`), and a gradient-boosted tree ensemble's `predict_proba` output is
a sum of a finite number of leaf values — identical (or near-identical, low
variance) feature rows recur constantly in this feature space (e.g. checkpoint
1-2 of a trade, where `age_seconds`, `mfe_atr_from_entry`, `mae_atr_from_entry`
are all ~0 for a large fraction of trades), so **exact ties at a decile edge
are a real, recurring event**, not a measure-zero corner case.

Impact: any checkpoint landing exactly on an edge gets a **different decile
live than it would have gotten if it had been run through the offline
pipeline**. Because `WEAK_DECILE_THRESHOLD`, `arm_decile`, `tighten_decile`,
and `terminal_tighten_decile` are all decile-boundary comparisons
(`_state_for_decile`, `stop_policy.py:101-108`), a boundary tie can flip
whether a checkpoint is even classified "weak" at all (`is_weak = decile >=
WEAK_DECILE_THRESHOLD`, `policy_strategy.py:108`), which cascades into
`persistence_bucket`, `score_path`, arm/tighten/terminal state, and which row
of the frozen `conditional_recovery_mae` table gets looked up. This is a
genuine train/serve skew: the live policy can silently act on a materially
different (decile, persistence_bucket, score_path) key than the offline
table was built to represent for that exact model score.

**Recommended fix (do not apply):** replace `decile_of` with a formula that
reproduces `pd.cut(..., right=True)`'s tie convention exactly — e.g.
`np.searchsorted(edges, prob, side="left")` behaves like right-closed
bin membership for interior edges (verify against a battery of exact-edge
test values before trusting), or explicitly special-case `prob in edges` to
match `pd.cut`. This needs a small unit test asserting `decile_of(v) ==
pd.cut([v], bins=edges, labels=False, include_lowest=True)[0] + 1` for both
generic values and every value in `edges` itself, before first use.

### [new] `policy_strategy.py:152-185` — state advances even when the recovery-MAE table lookup misses, silently leaving the trade "armed" with a stale or absent stop price

```python
if new_state != STATE_NONE and new_state != t["policy_state"]:
    target_decile = decile_for_state(cfg, new_state)
    mae_atr_budget = engine.lookup_recovery_mae(...)
    if mae_atr_budget is not None:
        ...                                   # (only path that sets policy_stop_price)
    t["policy_state"] = new_state             # <-- runs UNCONDITIONALLY
```

`t["policy_state"] = new_state` sits outside the `if mae_atr_budget is not
None:` block, at the same indentation level. If
`StopPolicyEngine.lookup_recovery_mae` returns `None` — either a `KeyError`
(the exact `(decile, persistence_bucket, score_path)` triple was never
observed in train+validation, plausible for rarer combinations: `WEAK_DECILES
× PERSISTENCE_BUCKETS × SCORE_PATHS` = 6×4×3 = 72 cells per population, and
`build_conditional_tables` (`conditional_stop_tables.py:17-58`) only produces
rows for cells that actually occurred) or a `NaN` value (the cell existed but
had zero "recovering" rows to take a quantile over) — the code:

1. Advances `t["policy_state"]` to the new (more "protected") state anyway.
2. Leaves `t["policy_stop_price"]` completely untouched — `None` if this is
   the trade's first ever arm transition, or the **stale, looser** value
   from the previous state if this is a tighten/terminal transition.

Because the outer `if new_state != t["policy_state"]:` gate only re-enters
this block on a **state change**, a single missed lookup at the first ARM
transition permanently disables the internal stop monitor for that trade
(`stop_price is not None:` check at line 191 is simply never true) until the
state changes again to a different (decile, persistence_bucket, score_path)
combination that happens to hit the table — which may never happen for the
rest of that trade's life. The trade's bookkeeping (`policy_state ==
STATE_ARMED/TIGHTENED/TERMINAL`) will silently disagree with its actual
behavior (fully unprotected, riding to the baseline `opposite_flip` exit like
an E0 trade) for the remainder of its life. This directly corrupts any
downstream analysis that assumes "armed decile ⇒ some protective stop was
active" and will misattribute PnL between "policy worked" and "policy didn't
fire" buckets.

**Recommended fix (do not apply):** only update `t["policy_state"]` inside
the `if mae_atr_budget is not None:` branch (i.e. treat a missing table cell
as "no transition occurred this bar," not "transition occurred but with no
stop"), or explicitly fall back to the nearest available cell / most recent
successfully-computed stop distance and log a diagnostic counter so missed
lookups are visible in `self._diag` rather than silent.

---

## Warnings

### [Item 4] `stop_policy.py:144-146` + `policy_strategy.py:174-184` — S1–S5 "natural loosening" removes an already-earned protective stop with no floor

For the default (non-ratchet, non-reversible) policies, `next_policy_state`
fully re-derives state from the *current* decile every checkpoint (line
146: `return target_state`). When decile improves enough that
`target_state < current_state`, `policy_strategy.py` still enters the
update branch via `new_state < t["policy_state"]` (line 174) and
unconditionally assigns the newly (looser) computed `new_stop` — there is
no floor clamp for S1-S5 (the floor clamp at lines 178-183 is gated on
`cfg.reversible_with_floor`, which is `False` for S1-S5 by design).

This means a stop that had already tightened to protect, say, 1.5 ATR of
profit can be moved back out to protect only 0.5 ATR (or less) purely
because the model's momentary weakness-probability estimate ticked down one
decile — even though price hasn't necessarily continued to move favorably
enough to justify giving back that much room. The `anchor_price` for
`anchor_mode="checkpoint"` is the *current* bar close, so the new stop isn't
anchored to a stale historical level, but the **budget** (`mae_atr_budget`)
applied against that current anchor is wider than what was previously
locked in, which is a real transfer of risk back onto the position.

This may be the intentional design ("natural loosening" is explicitly named
and documented in the module docstring), but it directly contradicts the
conventional assumption that a protective stop, once tightened, should never
be allowed to give back more room than it already has. **This needs an
explicit product decision from the user, not a silent default** — flagging
per the instruction to treat ambiguous-but-documented behavior as a WARNING
rather than assume it's benign. If S1-S5 are meant to only ever tighten (or
hold, per S6) and never actively loosen past their best-ever protection
level, this is a design bug; if the study genuinely wants to test
"non-sticky" state re-derivation as its own variable, this is fine as-is but
should be called out explicitly in the study SPEC/results write-up so a
reader doesn't mistake S1-S5 for a monotonic trailing stop.

### [Item 2] `policy_strategy.py:118-136` vs `stop_state_features.py:57-69` — `score_path`'s "prior probability 10s ago" selection algorithm differs from the offline one at non-uniform timestamps

Offline (two-pointer, per trade, sorted ascending):
```python
while lookback_i < i and ts[lookback_i] < target_ts:
    lookback_i += 1
# selects the OLDEST checkpoint with ts >= target_ts (first inside the window)
```

Live (deque scan, oldest→newest):
```python
for ts_h, p_h in hist:
    if ts_h <= target_ts:
        prior_prob = p_h    # keeps advancing
    else:
        break
# selects the NEWEST checkpoint with ts <= target_ts (last outside the window)
```

On a perfectly uniform 1-second checkpoint cadence with no gaps (the common
case — every `_on_1s_bar` call appends to `hist` unconditionally at line
136 unless an early-return fires), `target_ts` lands exactly on an existing
`ts` value and both algorithms select the identical element — verified by
hand-tracing both loops. They only diverge when the trade's own checkpoint
history has a **gap** (a missed 1s bar, or an early-return that skips the
`hist.append`), in which case the two implementations pick **adjacent but
different** historical checkpoints as "prior_prob," which can flip
`score_path` between `rising`/`flat`/`improving` for that checkpoint and
therefore select a different frozen-table row than the offline pipeline
would have for the equivalent path.

Given the project's own G2 note ("gaps in 1m data during low-liquidity
overnight" are a documented real phenomenon) and RTH-only 1s data being the
common but not guaranteed-gapless case, this is a real, if lower-probability,
mismatch. Recommend either (a) factoring the "closest checkpoint to N
seconds ago" lookup into a single shared function used by both the offline
`stop_state_features.py` and the live mixin, or (b) adding an explicit test
that feeds a gapped/irregular timestamp sequence through both
implementations and asserts identical `score_path` output before first use.

### [new] `policy_strategy.py:162-165` — `anchor_mode="mfe"` and `anchor_mode="checkpoint"` stop prices are only recomputed on a STATE transition, not on every new MFE high or every bar

The entire stop-price computation block (anchor, `raw_stop`, tick-rounding,
tighter-check) is nested inside `if new_state != STATE_NONE and new_state !=
t["policy_state"]:` (line 156/174). Once a trade settles into a stable state
(e.g. `TIGHTENED` for S6/ratchet, or any state that stops changing because
the decile has plateaued), the stop price is frozen at whatever level was
computed at the moment of that state transition — even under
`anchor_mode="mfe"`, where a genuinely "trailing" semantics would intuit that
the stop should keep advancing every time `running_mfe` sets a new high while
still in the same state. This isn't a look-ahead/causality bug (the stop
never becomes stale in the unsafe direction — it simply doesn't advance as
far as it plausibly could), but it is a design characteristic worth
confirming is intentional, since "MFE-anchored" naming suggests continuous
trailing to a reader and the code does not do that.

---

## Notes

### `policy_strategy.py:85-102` vs `base_strategy.py:409-451` — feature formulas duplicated rather than shared

The mixin recomputes `cur_pnl`, `mfe_atr`, `mae_atr`, `giveback_atr` inline
using the same `safe_atr` fallback pattern as `mfe_mae.py`'s `to_atr`/
`giveback_atr` helpers, rather than importing and calling those functions (or
reading directly from the just-appended `self._checkpoints[-1]` dict). I
hand-verified the formulas are algebraically identical today (confirmed
clean for Item 1 / D1 train-serve feature parity), but this is a DRY risk:
a future edit to `mfe_mae.py`'s ATR-normalization convention would silently
NOT propagate to the live policy mixin, reintroducing a skew. Recommend
importing `to_atr`/`giveback_atr` directly, or reading straight from
`self._checkpoints[-1]`, instead of re-deriving the arithmetic.

### `policy_strategy.py:166-169` — tick-rounding direction is asymmetric between long and short

For `d == 1`, `new_stop` truncates toward the looser (lower) tick; for `d ==
-1`, the mirrored formula truncates toward the tighter (lower, i.e. more
protective for a short) tick. Not a causality issue, and each direction's
own choice is internally consistent, but the two directions don't apply the
same "round toward X" policy, meaning long and short trades get a small
(≤1 tick) asymmetric conservatism bias relative to each other. Low impact,
worth a one-line comment or an explicit shared rounding convention if the
grid's per-direction PnL is ever compared head-to-head.

### No driver script yet exists to verify `feature_cols` ordering end-to-end

`StopPolicyEngine.__init__` takes `feature_cols` from the caller; nothing in
the currently-committed scope shows this being constructed with
`W0_FEATURES` from `w0_features.py`. Since `StopPolicyEngine.score()`
correctly reindexes `X = pd.DataFrame([feature_row])[self.feature_cols]`
before calling `model.predict_proba`, this is *robust to* ordering as long
as the same `feature_cols` list is passed at both training and inference
time — but that invariant is currently enforced by convention, not by code,
because the driver script that will eventually call `StopPolicyEngine(...)`
and `run_period(..., strategy_post_init=...)` doesn't exist in this diff.
Flag for the pre-execution audit of that driver script when it's written:
confirm it passes `W0_FEATURES` (imported, not re-typed) as `feature_cols`.

### `policy_strategy.py:193-194` and the exit-reason guard fix are CLEAN

Confirmed clean for the record (Item 3 and the stop-trigger mechanism):
- The stop monitor correctly triggers off `bar.low`/`bar.high`, never
  `bar.close` (satisfies the project's H1 rule for any SL/PT-style trigger
  check).
- The market-order exit submitted on trigger is a real NT order routed
  through `_submit_exit`/`BacktestEngine` with `bar_execution=True`, which
  will fill at the *next* bar's open per NT's own execution semantics — this
  is genuine NT-native execution, not an offline phantom-fill-at-trigger-
  price approximation (satisfies H4 by construction, since no PnL is
  credited by this code directly).
- The `exit_order_id is not None or exit_reason is not None` guard
  (`policy_strategy.py:80-81`) is correct: traced the full `_on_1s_bar`
  dispatch order in `base_strategy.py` (1m-bucket-close/opposite-flip check
  → `_update_open_trade`/stop-policy hook → exit-rejection retry, in that
  order every bar) and found no path where a trade has an exit already
  decided-but-pending that isn't reflected in one of those two fields by the
  time `_maybe_stop_policy_exit` runs. `exit_reason` is a permanent latch
  once set (nothing in `base_strategy.py` clears it back to `None` for a
  live trade dict); the fix correctly closes the gap the docstring describes.
- `_submit_entry`/`_init_policy_state` correctly reset all `policy_*` trade
  fields fresh per new trade (`policy_strategy.py:58-61`); no stale-state
  leakage across trades.
- `anchor_mode="mfe"`'s `anchor_price = ep + d * t["running_mfe"]` (Item 6)
  is confirmed correct for both directions and resolves to a real,
  already-observed bar `high` (long) or `low` (short) — not extrapolated.
- `ratchet_only`'s `max(current_state, target_state)` (Item 5, S6) is
  confirmed to never return a state below `current_state` under any input.
- `reversible_with_floor`'s one-level-per-bar loosening cap and the floor
  clamp applied at every loosening transition (Item 5, S7) are confirmed
  correct in isolation; note this shares the same "state advances without
  price update on missing lookup" CRITICAL finding as S1-S6 above, which can
  also apply to S7's floor-respecting path if the lookup misses immediately
  after a loosening event.
- MRO for `AllFlipsPolicyStrategy(StopPolicyMixin, AllFlipsStrategy)` and
  `F2ConfirmedPolicyStrategy(StopPolicyMixin, F2ConfirmedStrategy)` resolves
  cleanly; neither concrete strategy overrides `_submit_entry`, so
  `StopPolicyMixin._submit_entry`'s `super()` call reaches
  `ExitManagementBaseStrategy._submit_entry` as intended.
- `nt_runner.py`'s `strategy_post_init` parameter is applied after strategy
  construction and before `engine.run()`; `getattr(self, "policy_engine",
  None)` defaults safely to E0 no-op behavior if never attached.

---

## Clean checks

- Item 1 (feature formula parity, `current_pnl_atr_from_entry`,
  `mfe_atr_from_entry`, `mae_atr_from_entry`, `giveback_atr_from_entry`,
  `distance_from_mfe_atr`, `age_seconds`): verified algebraically identical
  between `_update_open_trade`/`build_atlas.py`'s consumption of it and the
  mixin's inline recomputation.
- `persistence_bucket` boundary constants (`WEAK_DECILE_THRESHOLD`,
  `SCORE_PATH_LOOKBACK_S`, `SCORE_PATH_EPS`, `_persistence_bucket`) are
  imported directly from `stop_state_features.py`, not re-typed — zero drift
  risk on those specific constants.
- `score_path` rising/improving/flat comparison operators and epsilon are
  identical between offline and live (only the *prior-probability selection*
  differs, per Warning above).
- Item 6 (anchor_mode="mfe" price is a real achieved level, not
  extrapolated) — clean, both directions.
- Item 3 (exit-reason guard) — clean, fix is correct.
- Item 5 (S6 ratchet monotonicity) — clean.
- H1/H4-equivalent (stop trigger uses high/low, fill is real NT next-bar-open
  execution, not phantom trigger-price credit) — clean.
- No pandas-based signal/feature computation anywhere in the live path —
  all live scoring reads directly from NT-bar-derived trade-dict state.

---

*Audit complete. Findings reflect read-only static analysis; code has not
been executed. Both CRITICAL findings should be fixed before this study's
first NT run — the decile-boundary mismatch (Item 7) affects every
population/config in the grid, and the missing-lookup state/price desync
affects any config whose arm/tighten/terminal deciles can land on a sparse
table cell (S1-S7 all use `arm_decile`/`tighten_decile`/`terminal_tighten_decile`
except E1).*

---
---

# RE-AUDIT — Phase 5/6 Stop-Policy Mechanics, Post-Fix Pass

**Date:** 2026-07-11 (follow-up pass, same day)
**Scope:** Re-read of current full text of:
- `studies/_shared_exit_mgmt/stop_policy.py`
- `studies/_shared_exit_mgmt/policy_strategy.py`
- `studies/_shared_exit_mgmt/policy_grid.py` (unchanged; re-checked for consistency with new semantics)

Also consulted (unchanged, read for cross-reference only):
- `studies/_shared_exit_mgmt/train_model.py` (`decile_edges` construction,
  `pd.qcut(..., duplicates="drop")`)
- `studies/_shared_exit_mgmt/stop_state_features.py` (offline `score_path`/
  `persistence_bucket` two-pointer reference implementation)
- `studies/_shared_exit_mgmt/base_strategy.py` (`_diag` dict existence,
  `_on_1s_bar` dispatch order — spot-checked only, not re-audited in full)

**Auditor:** lookahead-auditor v1

**Pre-execution status re-confirmed:** grepped the full `studies/` tree for
`StopPolicyEngine(`, `StopPolicyMixin`, `policy_cfg`, `StopPolicyConfig`,
`POLICY_GRID`, `strategy_post_init`. The only hits outside
`_shared_exit_mgmt/` are the two thin subclass files
(`all_flips_exit_management/policy_strategy.py`,
`f2_confirmed_exit_management/policy_strategy.py`), which only define
`AllFlipsPolicyStrategy(StopPolicyMixin, AllFlipsStrategy)` /
`F2ConfirmedPolicyStrategy(StopPolicyMixin, F2ConfirmedStrategy)` classes —
no instantiation. `studies/_shared_exit_mgmt/smoke_test.py` and
`studies/pre_flip_d10_reversal_entry/run_nt_policies.py` matched the grep
only via the generic `run_period` import; neither references
`StopPolicyEngine`/`policy_engine`/`policy_cfg` and neither drives the
policy-mixin strategies. **Confirmed: still no driver script attaches a
`StopPolicyEngine` and calls `run_period`. Code has not been executed.**

## Summary (this pass)

- Critical: 1 new finding (previous 2 CRITICAL confirmed RESOLVED)
- Warning: 1 new finding, 1 carried-forward unresolved (previous 2 of 3
  WARNINGs confirmed RESOLVED)
- Note: 2 new, 3 carried-forward unresolved from the original pass

---

## Fix verification — Items 1-4 from the user's follow-up

### Item 1 (decile_of tie convention): **RESOLVED, verified generally, not just at the tested edges**

`stop_policy.py:86-97` now uses `np.searchsorted(self.decile_edges, prob,
side="left")`. Re-derived the general proof rather than trusting the 13
spot-checked values:

- `np.searchsorted(edges, v, side="left")` returns the count of elements in
  `edges` **strictly less than** `v`.
- `pd.cut(bins=edges, right=True, include_lowest=True)` assigns `v` to
  0-indexed bin `k-1` when `edges[k-1] < v <= edges[k]` (interior), or bin 0
  when `v == edges[0]` (via `include_lowest`).
- For `v` strictly interior to a bin (no tie): both conventions agree
  trivially (no edges equal `v`, so `side="left"`/`"right"` coincide).
- For `v == edges[k]` exactly, `1 <= k <= len(edges)-2` (an interior edge):
  `pd.cut` assigns bin `k-1` → decile `k`. `searchsorted(..., "left")`
  counts edges `< edges[k]`, which is exactly `edges[0..k-1]`, i.e. `k`
  elements → `idx = k` → decile `k` (after the `+1`/direct-decile
  convention used here). **Matches for every interior edge, not just the 9
  tested (0.1-0.9).**
- For `v == edges[0]` (`= -inf` per `train_model.py:107`): count of edges
  `< -inf` is 0 → `idx = 0` → clamped by `max(1, ...)` to decile 1, matching
  `include_lowest`'s bin-0 assignment. Real probabilities are never
  literally `-inf`, so this is a boundary-correctness check on the formula,
  not a reachable runtime case — confirmed it degrades safely regardless.
- For `v == edges[-1]` (`= +inf`): count of edges `< +inf` is `len(edges)-1`
  → clamped by `min(10, ...)`. Also never reachable for a real probability
  (`prob < +inf` always strictly), same safe-degradation conclusion.
- **`pd.qcut(..., duplicates="drop")` (`train_model.py:105`) can shrink
  `edges` below the nominal 11 elements** when `p_train` has few unique
  values at some quantile boundary. This does not break the `decile_of`/
  `pd.cut` correspondence — the proof above is generic in `len(edges)`, so
  live and offline stay consistent with each other under a shrunk array
  too. **However**, this can silently reduce the number of *reachable*
  deciles below what `arm_decile`/`tighten_decile`/`terminal_tighten_decile`
  (6/7/8/9 across the S1-S7 grid) assume are populated — see new NOTE
  below. This is a distinct, lower-severity concern from the tie-convention
  bug and does not reopen the original CRITICAL.

**Verdict: CRITICAL RESOLVED. Clean.**

### Item 2 (state advances without stop price on missing lookup): **RESOLVED, gap fully closed, now visible via diagnostic**

Re-read `policy_strategy.py:162-200`. `t["policy_state"] = new_state`
(line 197) is now correctly nested one level inside `if mae_atr_budget is
not None:` (line 167), at the same indentation as the stop-price
computation. Confirmed:

- On a successful lookup, state and stop price advance together (as
  before, this was never broken for the success path).
- On a missed lookup (`KeyError` or `NaN`), neither `t["policy_state"]` nor
  `t["policy_stop_price"]` changes this bar; `self._diag["policy_lookup_miss"]`
  increments instead (`policy_strategy.py:198-200`).
- Traced the retry behavior explicitly (this was the user's specific
  follow-up question): since `t["policy_state"]` didn't change, the outer
  gate `new_state != t["policy_state"]` (line 162) remains `True` on the
  *next* bar as long as `next_policy_state` keeps recomputing the same (or a
  monotonically-further) `new_state` from the current decile/persistence/
  score_path — which it will, since the default ratchet
  `max(current_state, target_state)` only moves forward. This means a
  combination that **never** appears in the frozen table causes a
  **retry every single bar for the rest of that trade's life**, each one
  incrementing `policy_lookup_miss` by 1. This is exactly the intended
  trade-off described in the fix: the trade's `policy_state` bookkeeping
  stays honest (never claims a protection level it doesn't have), and the
  failure mode — permanently unprotected, riding like an E0 trade — is now
  **visible and quantifiable** via the counter rather than silently
  misattributing PnL. Confirmed `self._diag` is a real dict initialized in
  `base_strategy.py:142` and persisted to disk at end-of-run
  (`base_strategy.py:518,534`), so `policy_lookup_miss` will actually
  surface in the run's diagnostics output, not just live in memory.
- Checked the interaction with `t["policy_stop_price"]` on repeated misses:
  it stays at whatever it was before the failed transition attempt (`None`
  if never armed, or the last successfully-computed value) — self-consistent
  with the unchanged `policy_state`, no desync.

**Verdict: CRITICAL RESOLVED. Clean**, with the caveat that a
high-`policy_lookup_miss` count for a given `(decile, persistence_bucket,
score_path)` combination should be treated as a data-sparsity signal
requiring investigation before trusting that config's results (not a code
bug — a modeling/coverage limitation of the frozen table, now correctly
surfaced rather than hidden).

### Item 3 (S1-S5 monotonic ratchet / S7 sole exception): **PARTIALLY RESOLVED — new CRITICAL found in S7's floor-bypass edge case**

(a) Confirmed no code path in `next_policy_state` (`stop_policy.py:131-172`)
returns below `current_state` for any config with
`cfg.reversible_with_floor == False` (S1-S6): the persistence gate returns
`current_state` unchanged (never below); the `reversible_with_floor` branch
is skipped entirely; the default branch is `max(current_state, target_state)`,
which is `>= current_state` by construction. **This part of (a) is clean.**

(b) Confirmed the S6/S4 mechanical-equivalence claim is genuine and not
accidentally shared with S7: `cfg.ratchet_only` is **not referenced anywhere**
in `next_policy_state` or `policy_strategy.py` (grepped the whole
`_shared_exit_mgmt` tree — the only hits are the dataclass field
declaration, the `policy_grid.py` config literal, and docstring prose). S6's
config (`policy_grid.py:30-31`) is otherwise byte-for-byte identical to S4's
(`arm_decile=6, tighten_decile=8, terminal_tighten_decile=9, percentile=90`),
so S6 and S4 will produce bit-identical trade sequences in this grid —
genuine equivalence, confirmed via the code path, not asserted by the
docstring alone. S7 remains the **only** config that can return a state
below `current_state` (gated strictly on `cfg.reversible_with_floor`, a
different field from `ratchet_only`). **This part of (b) is clean.**

**However**, while tracing every reachable path through the
`reversible_with_floor` branch to answer (a) fully generally (not just "does
it stay `>= current_state`" but "does the *floor guarantee* actually hold
for every loosening transition"), I found a genuine new CRITICAL — see
below. This directly contradicts the module docstring's explicit claim that
S7's stop price "can never move below `protect_floor_atr` ATR of profit,"
and reopens part of the item-3 verification as **not fully resolved**.

#### NEW CRITICAL: `stop_policy.py:162-169` + `policy_strategy.py:162,201-203` — S7's one-level loosening from ARMED down to NONE bypasses the floor clamp entirely, removing the stop rather than floor-clamping it

Trace the reversible branch when `current_state == STATE_ARMED (1)` and the
weakness decile has fallen back below `cfg.arm_decile` (so
`_state_for_decile` returns `target_state = STATE_NONE (0)`):

```python
# stop_policy.py:162-169
if cfg.reversible_with_floor:
    if target_state >= current_state:      # 0 >= 1 is False
        return target_state
    if score_improved or new_mfe_this_bar:  # true on genuine recovery
        return max(target_state, current_state - 1)  # max(0, 0) = 0 = STATE_NONE
    return current_state
```

`next_policy_state` correctly caps the loosening at "one level per bar" —
but when the *starting* level is `STATE_ARMED (1)`, one level down **is**
`STATE_NONE (0)`. The function returns `0`, which is a legitimate, expected
return value by the one-level-cap logic.

The bug is in how `policy_strategy.py` consumes that return value:

```python
# policy_strategy.py:162, 201-203
if new_state != STATE_NONE and new_state != t["policy_state"]:
    ...                                  # floor-clamp logic lives ONLY here
elif new_state == STATE_NONE:
    t["policy_state"] = STATE_NONE
    t["policy_stop_price"] = None        # <-- unconditional wipe, no floor
```

Because `new_state == STATE_NONE` routes through the **`elif`** branch
instead of the **`if`** branch, none of the floor-clamp code
(`policy_strategy.py:184-189`, `floor_price = ep + d * cfg.protect_floor_atr
* safe_atr`) ever executes for this specific transition. `policy_stop_price`
is set directly to `None` — i.e. the internal stop monitor goes completely
dark (`stop_price is not None:` check at the bottom of the method never
fires), which is **strictly worse** than "floor-clamped at breakeven": a
floor-clamped stop still guarantees a worst-case exit at
`entry + protect_floor_atr`; `None` guarantees nothing — the trade rides
uncapped all the way to whatever exit condition fires next (typically the
baseline `opposite_flip` exit), exactly like an E0/no-policy trade, for
however long it stays below `arm_decile` before (if ever) re-arming.

**This is not a rare corner case.** It is the single most common way an S7
trade's protective state resolves: any trade that gets armed once and then
genuinely recovers (decile falls back under `arm_decile`, `score_improved`
or `new_mfe_this_bar` true — precisely the condition the reversible design
exists to reward) will hit this exact transition. Every S7 trade that is
armed exactly once and then recovers passes through `ARMED -> NONE` via this
buggy path, not through the floor-respecting `if` branch. Only trades that
are `TIGHTENED (2)` or `TERMINAL (3)` and loosen by one level land in the
floor-respecting `if` branch (`TIGHTENED -> ARMED`, `TERMINAL -> TIGHTENED`)
— the terminal step down to `NONE` is always unprotected.

This also makes the module docstring inaccurate as currently written
(`stop_policy.py:27-32`): "the resulting stop price can never move below
`protect_floor_atr` ATR of profit ... documented choice" is **false** for
the `ARMED -> NONE` transition — the stop doesn't move below the floor, it
disappears, which is a stronger violation of the stated guarantee, not a
milder one.

**Recommended fix (do not apply):** either (a) route the `new_state ==
STATE_NONE` case for `reversible_with_floor` configs through the same
floor-clamp logic — i.e. treat "loosen to NONE" as "loosen to a
floor-clamped stop at `protect_floor_atr`," which is presumably the actual
product intent given the docstring, rather than "remove the stop," or (b)
if "fully disarm below `arm_decile`" is actually the intended behavior for
S7 (i.e. the floor guarantee is only meant to apply while `state >
STATE_NONE`), amend the docstring to say so explicitly, since the current
wording promises an unconditional floor. This needs an explicit product
decision from the user before first execution, same as the original Item 4
question — do not assume either interpretation is correct.

### Item 4 (score_path lookback selection): **RESOLVED, verified against both gapless and gapped sequences**

Re-read `policy_strategy.py:118-142` and `stop_state_features.py:32-74`
side by side.

Offline: `while lookback_i < i and ts[lookback_i] < target_ts: lookback_i +=
1`, stateful pointer carried across the per-trade loop (never reset), then
uses `lookback_i` if `lookback_i < i` (i.e. found before reaching the
current index). Because `ts` is sorted ascending and `target_ts` is
non-decreasing as `i` increases, this two-pointer is provably equivalent to
a fresh linear scan from index 0 on every `i`, always landing on the first
index with `ts >= target_ts`.

Live: `for ts_h, p_h in hist: if ts_h >= target_ts: prior_prob = p_h; break`,
scanning the deque oldest→newest (deque is only ever `.append()`-ed, never
`.appendleft()`-ed, so iteration order matches offline's ascending sort).
This is exactly "first element with `ts_h >= target_ts`" — matching the
offline convention verbatim, not merely "usually agreeing."

**Gapless case:** every 1s bar appends a checkpoint; `target_ts` (10s back)
lands exactly on an existing entry; both algorithms trivially select the
same element.

**Gapped case (constructed mentally):** checkpoint timestamps
`{..., 4, 15, 16, 17, ...}` (a gap from second 5 through 14 — e.g. a missed
`_on_1s_bar` call, or the "already exiting" early-return at
`policy_strategy.py:80-81` which returns *before* `hist.append` runs for
those bars). Evaluating at `i` where `ts[i] = 17`, `target_ts = 7`:
- Offline: pointer advances past `0,1,2,3,4` (all `< 7`), stops at `15`
  (`>= 7`, and `15`'s index `< i`'s index) → `prior_prob` = prob at `ts=15`.
- Live: scans `..., 4` (all `< 7`, no match), then `15 >= 7` → break,
  `prior_prob` = prob at `ts=15`.
- **Identical.** Re-ran this reasoning for a gap that straddles the target
  exactly (`target_ts` falling inside the missing range) and for a gap
  immediately before the current checkpoint — in every construction, both
  algorithms select the same "first present timestamp at-or-after
  `target_ts`" because both fundamentally implement the same rule over the
  same ordered sequence; the only way they could diverge is if the two
  implementations saw **different sets of checkpoints** in `hist`, which
  would be a *different* problem (data availability) unrelated to the
  selection *algorithm* itself.
- One assumption worth flagging as a dependency rather than a bug: this
  proof requires that `hist` (live) and the offline atlas's per-trade
  checkpoint rows contain the **same set** of checkpoints in the **same
  order** for the same trade — true by construction today (both are driven
  by the same `_on_1s_bar` cadence and the same early-return conditions),
  but not independently re-verified in this pass beyond what the original
  audit already confirmed for Item 1 (feature parity).
- `hist`'s `deque(maxlen=64)` is far larger than the 10-second lookback
  window needs (10 entries at 1 Hz) and is freshly created per trade
  (`_init_policy_state`, line 55) — no cross-trade leakage, no truncation
  risk for this specific lookback.

**Verdict: WARNING RESOLVED. Clean**, both for uniform and gapped cadences.

---

## Docstring / code consistency (fresh look)

`stop_policy.py:1-42`'s module docstring and `next_policy_state`'s function
docstring (`stop_policy.py:135-156`) accurately describe the current code
for S1-S6 (monotonic, forward-only, S6≡S4) and correctly describe S7's
*intended* one-level/floor-respecting design — but per the new CRITICAL
above, the docstring's specific claim that the stop price "can never move
below `protect_floor_atr` ATR of profit" is **not actually true** in the
implementation, for the `ARMED -> NONE` transition. This is a genuine
docstring/code inconsistency, not just a code bug in isolation — fix
whichever side is wrong (code or docstring) so they agree, per the request.
All other docstring claims cross-checked against code in this pass
(monotonic ratchet, S6/S4 equivalence, frozen-artifact/no-retraining
framing) are accurate.

---

## New Warning

### `policy_strategy.py:172-197` — forward arm/tighten/terminal transitions can silently leave `policy_state` decoupled from the trade's actual protective stop distance

Found while tracing every branch of the transition-update block for the
item-2/item-3 verification (not one of the 4 listed fixes, but surfaced by
the same code path).

```python
tighter = (cur_stop is None or
              (d == 1 and new_stop > cur_stop) or
              (d == -1 and new_stop < cur_stop))
if tighter or new_state < t["policy_state"]:
    ...
    t["policy_stop_price"] = new_stop
# t["policy_state"] = new_state runs regardless of whether `tighter` was True
```

On a **forward** transition (e.g. `ARMED -> TIGHTENED`), if the newly
looked-up `mae_atr_budget` for the tighten-level cell happens to imply a
*wider* (less protective) stop than the one already in place — plausible
since the ARM and TIGHTEN transitions can occur at different
`persistence_bucket`/`score_path` cells (independent, small-sample
aggregates in the frozen table, not guaranteed to be monotonically
non-increasing in stop distance as decile increases) — then `tighter`
evaluates `False`, `policy_stop_price` is correctly **not** loosened (this
part is safe/conservative), but `policy_state` still advances to
`TIGHTENED` two lines later regardless. The result: a trade tagged
`policy_state == TIGHTENED` in the output whose actual live protective stop
distance still reflects the `ARMED`-level budget from the prior transition.
This is not a look-ahead or risk-increasing bug (the position is never
under-protected relative to what it already had), but it is a **label
integrity** issue for any downstream analysis that groups trades by
`policy_state` and assumes the state name implies a specific stop distance
was actually in force. Recommend either (a) asserting/enforcing
monotonically non-increasing stop distance across states within a policy at
table-build time (`conditional_stop_tables.py`), or (b) tracking the actual
"as-applied" stop distance/state separately from the "as-computed target"
state for reporting, so a reader can distinguish "reached tighten-decile"
from "stop actually tightened."

---

## New Notes

### `train_model.py:105` — no assertion that `pd.qcut(..., duplicates="drop")` preserves the full 11-edge / 10-decile resolution the S1-S7 grid assumes

Confirmed (per Item 1 above) that `decile_of`/`pd.cut` stay mutually
consistent regardless of how many edges survive `duplicates="drop"`, so
this is **not** a live/offline skew risk. It is, however, a silent-shrinkage
risk relative to the grid's own assumptions: `arm_decile`/`tighten_decile`/
`terminal_tighten_decile` values of 6/7/8/9 (`policy_grid.py:23-34`) assume
deciles up to 9 are reachable. If `p_train`'s distribution has enough
repeated values that `qcut` drops duplicate boundaries and `edges` shrinks
(e.g. to 8 elements => max decile 7), `tighten_decile=8`/`terminal=9` become
permanently unreachable for that population — silently degrading S2/S4/S5/
S6/S7 to their `arm`-only behavior with no error, only observable as
"TIGHTENED/TERMINAL states never appear in the diagnostics." Recommend a
one-line assertion after `train_model.py:107` (`assert len(edges) ==
N_DECILES + 1, f"qcut dropped duplicates: only {len(edges)} edges"`), or at
minimum logging `len(edges)` alongside the other Phase 3 diagnostics so this
is visible before the grid is run.

### `policy_strategy.py:163-166` — `target_decile` used for the table lookup is the config's canonical threshold decile, not the trade's actual currently-observed decile

`decile_for_state(cfg, new_state)` returns the *fixed constant*
(`cfg.arm_decile`/`tighten_decile`/`terminal_tighten_decile`) associated
with the new state, not the checkpoint's actual `decile` value computed
moments earlier. A trade whose decile jumps straight from, say, 5 to 9 in
one bar (skipping past `arm_decile=6` entirely) will be looked up at
`decile=6`'s conditional-table row, not `decile=9`'s, even though the table
has a distinct row for decile 9 that presumably reflects a narrower expected
recovery. This appears to be the **intentional** design given the module
docstring's framing ("each state has an associated stop DISTANCE ... read
from the frozen table at (decile, ...)" — implying one canonical decile per
state, not a continuously-varying one) and is unaffected by any of the four
fixes verified in this pass, so it is not re-scored as a Warning here — but
flagging explicitly since it was not previously called out in the original
audit's clean-checks list, and a future reader unfamiliar with this
convention could easily mistake it for a bug. Worth an explicit one-line
confirmation in the docstring that this is deliberate (canonical-threshold
lookup, not observed-decile lookup).

---

## Carried-forward findings (unresolved, unaffected by the four fixes)

- **WARNING** — `policy_strategy.py:162-197` — `anchor_mode="mfe"`/
  `"checkpoint"` stop prices are still only recomputed on a state
  transition, not on every new MFE high or every bar while a trade sits in
  a stable state. Re-read the current code: the entire stop-price
  computation block remains nested inside `if new_state != STATE_NONE and
  new_state != t["policy_state"]:`, unchanged from the original pass. Still
  open; not addressed by any of the four described fixes.
- **NOTE** — `policy_strategy.py:85-102` — feature formulas (`cur_pnl`,
  `mfe_atr`, `mae_atr`, `giveback_atr`) are still duplicated inline rather
  than imported from `mfe_mae.py`'s helpers. Unchanged; DRY risk stands.
- **NOTE** — `policy_strategy.py:172-175` — tick-rounding direction is still
  asymmetric between long and short. Unchanged.
- **NOTE** — no driver script yet exists to verify `feature_cols` ordering
  end-to-end (`W0_FEATURES` wiring). Still true as of this pass — re-confirmed
  no such driver exists (see pre-execution status re-check above).

---

## Clean checks (re-confirmed this pass)

- Item 1 (decile_of tie convention, `side="left"`) — CLEAN, verified by
  general proof over all edge positions (interior, first, last), not just
  spot-tested values, and shown robust to `duplicates="drop"` edge-array
  shrinkage.
- Item 2 (missing-lookup state/price desync) — CLEAN, gap fully closed;
  the residual failure mode (permanent per-bar retry against a genuinely
  absent table cell) is now visible via `policy_lookup_miss` in `self._diag`
  and persisted to the run's diagnostics file, rather than silently
  corrupting `policy_state` bookkeeping.
- Item 3(a) monotonicity for S1-S6 — CLEAN, no path returns below
  `current_state` when `cfg.reversible_with_floor is False`.
- Item 3(b) S6≡S4 equivalence, and S7-exclusivity of the loosening path —
  CLEAN, confirmed via code trace (`ratchet_only` unreferenced in logic;
  `reversible_with_floor` is the sole gate on any downward transition).
- Item 4 (score_path lookback selection) — CLEAN, live and offline
  algorithms proven equivalent for both gapless and gapped checkpoint
  sequences.
- `policy_grid.py` — re-checked for consistency with the new monotonic-only
  semantics: no code in this file references state-transition logic
  directly (it only builds `StopPolicyConfig` instances), so nothing here
  needed to change; S6's config remains parameter-identical to S4's except
  the now-fully-inert `ratchet_only=True` flag, consistent with the
  documented equivalence.
- Pre-execution gate — re-confirmed no driver script instantiates
  `StopPolicyEngine` or calls `run_period` with a policy engine attached;
  code has not been executed.

---

*Re-audit complete. Findings reflect read-only static analysis; code has
not been executed. One NEW CRITICAL (S7 floor-bypass on `ARMED -> NONE`)
must be resolved — via either a code fix or an explicit, documented product
decision from the user — before this study's first NT run. The new WARNING
(state/stop-distance decoupling on non-monotonic table cells) and the
carried-forward WARNING (anchor_mode recompute-on-transition-only) should
be triaged by the user before proceeding; neither blocks execution outright
if the user explicitly accepts the described behavior, per the same
"explicit product decision, not a silent default" standard applied to the
original Item 4.*

---
---

# SECOND RE-AUDIT — Focused Verification of the S7 `ARMED -> NONE` Floor-Clamp Fix

**Date:** 2026-07-11 (third pass, same day)
**Scope:** Focused, targeted re-read of `studies/_shared_exit_mgmt/policy_strategy.py`'s
`_maybe_stop_policy_exit` method (full current text, lines 63-249) and the
relevant portion of `studies/_shared_exit_mgmt/stop_policy.py`'s
`next_policy_state` (lines 131-172), verifying only the specific fix
described by the user for the CRITICAL raised in the prior re-audit pass
(S7's one-level loosening from ARMED to NONE routing through the
"genuinely never armed" branch and dropping the floor).

**Auditor:** lookahead-auditor v1

## Summary (this pass)

- Critical: 0 (the CRITICAL from the prior pass is RESOLVED)
- Warning: 0 new (both open WARNINGs from the prior pass are UNCHANGED,
  neither addressed nor regressed by this fix — see "still outstanding"
  below)
- Note: 1 new (dead/unreachable defensive branch, harmless)

---

## Question 1 — Can S7 still reach `STATE_NONE` from an armed state without the floor clamp, via any path?

**No. RESOLVED.** Traced every way the restructured single `if new_state !=
t["policy_state"]:` block (`policy_strategy.py:162`) can be entered with
`new_state == STATE_NONE`:

- The outer gate requires `new_state != t["policy_state"]`. Since
  `new_state == STATE_NONE (0)`, this can only be `True` if
  `t["policy_state"]` was non-zero at entry (i.e. the trade was ARMED,
  TIGHTENED, or TERMINAL a moment ago) — a genuinely-never-armed trade
  already sitting at `STATE_NONE` produces `new_state == 0 ==
  t["policy_state"]` and never even enters the block (no code runs, stop
  price is correctly left as `None`/unchanged).
- So by construction, **every reachable entry into
  `if new_state == STATE_NONE:` (line 163) is a loosening-from-armed
  transition**, never a "genuinely never armed" case.
- Inside that branch, the only fork is
  `if (cfg.reversible_with_floor and t["policy_state"] != STATE_NONE):`
  (lines 164-165). Given the point above, `t["policy_state"] != STATE_NONE`
  is **always** `True` whenever this branch is reached at all (it's the
  precondition for reaching it, not an independent runtime possibility).
  So the only live variable determining floor-clamp-vs-None is
  `cfg.reversible_with_floor` itself.
- For S7 configs, `cfg.reversible_with_floor is True` by definition —
  therefore **every** `ARMED/TIGHTENED/TERMINAL -> NONE` transition for an
  S7 config takes the `floor_price = ep + d * cfg.protect_floor_atr *
  safe_atr` path (line 176) and sets `t["policy_stop_price"] = floor_price`
  (line 177), never `None`.
- Cross-checked against `next_policy_state` (`stop_policy.py:162-169`):
  confirmed (as in the prior pass) that `STATE_NONE` is only reachable as a
  return value from a *starting* state of `STATE_ARMED (1)` — one level
  down from ARMED is exactly 0. `TIGHTENED (2)` and `TERMINAL (3)` can only
  loosen by one level per bar, landing on `ARMED (1)` and `TIGHTENED (2)`
  respectively, never jumping straight to `NONE`. So the fix's target case
  (`ARMED -> NONE`) is precisely and only the case this branch now protects,
  matching the bug description exactly.
- Also confirmed the floor-clamp computation itself (`ep + d *
  cfg.protect_floor_atr * safe_atr`) requires no table lookup and cannot
  fail/return `None` — unlike the ARMED/TIGHTENED/TERMINAL branch's
  `mae_atr_budget` lookup, there is no missing-data failure mode that could
  cause this specific path to silently fall back to an unprotected `None`
  stop. The floor guarantee is unconditional once `reversible_with_floor`
  and a real prior armed state are established.

**Verdict: CRITICAL RESOLVED.** No path exists for an S7 trade to lose its
stop entirely on a one-level loosening to `STATE_NONE`; the floor is always
applied.

---

## Question 2 — Is `t["policy_state"] != STATE_NONE` (line 165) reading the pre-transition value, with no ordering bug?

**Yes, correct. No ordering bug.** Scanned the entire `_maybe_stop_policy_exit`
body from its start (line 63) to line 165 for any prior write to
`t["policy_state"]` within this same call: none exists. The only writes to
`t["policy_state"]` anywhere in the method are at line 182
(`t["policy_state"] = STATE_NONE`, inside this same branch, *after* the
line-165 read) and at line 237 (`t["policy_state"] = new_state`, in the
sibling `else` branch, mutually exclusive with this one). Other trade-dict
writes that occur earlier in the call (`policy_weak_entry_ts`,
`policy_prob_history` append, `policy_prev_mfe_atr`,
`policy_direct_exit_done`) never touch `policy_state`. The read at line 165
therefore observes the value `t["policy_state"]` held at function entry —
the genuine pre-transition state — before it is set to `STATE_NONE` two
lines later (line 182). **Clean.**

---

## Question 3 — For non-reversible policies (S1-S6), can `new_state` ever be `STATE_NONE` while `t["policy_state"]` is already non-NONE, after this restructuring?

**No — structurally impossible, unaffected by the restructuring.**
`next_policy_state`'s default branch (`stop_policy.py:172`,
`return max(current_state, target_state)`) is untouched by this fix — the
restructuring was entirely confined to `policy_strategy.py`'s consumption
of the return value, not to `next_policy_state` itself. `max(current_state,
target_state) >= current_state` always, so `new_state == STATE_NONE (0)`
for a non-reversible config requires `current_state <= 0`, i.e.
`current_state == STATE_NONE` already — meaning the outer gate
(`new_state != t["policy_state"]`) is `False` and the whole block
(including the new `if new_state == STATE_NONE:` branch) is never entered
in the first place. This matches the prior pass's finding exactly and is
unchanged by the fix. Additionally, the floor-clamp fork itself
(`cfg.reversible_with_floor and ...`) is a second, independent gate that
would prevent an S1-S6 config from ever taking the floor-clamp sub-path
even in some hypothetical future scenario where the first invariant broke
— i.e. this is defense-in-depth, not a single point of failure. **No new
way for a non-reversible policy to reach the floor-clamp branch was
introduced. Clean.**

One corollary surfaced by this tracing, noted for completeness rather than
as a bug (see New Note below): given both of the above, the `else` fallback
at lines 178-181 (`t["policy_stop_price"] = None` — the "genuinely never
armed" comment) is currently **unreachable dead code** under the invariants
established by `next_policy_state` today. It is harmless (a safe default
that would only ever matter if `next_policy_state`'s monotonicity guarantee
were broken by a future edit), but it is worth knowing it isn't actually
exercised by any live code path today.

---

## Question 4 — Any other regression from merging the two branches into one; is the "advance state only on successful lookup" fix (the other prior CRITICAL) still intact?

**No regression found; the other fix remains intact.** Re-verified the
`else` (non-`STATE_NONE`) side of the restructured block
(`policy_strategy.py:183-240`), which is the branch that previously housed
the "state advances even on missing lookup" CRITICAL from the very first
audit pass:

- `target_decile = decile_for_state(...)` and
  `mae_atr_budget = engine.lookup_recovery_mae(...)` (lines 184-187) are
  unchanged from the prior (already-fixed) version.
- `if mae_atr_budget is not None:` (line 188) still gates the entire
  stop-price computation block (anchor, `raw_stop`, tick-rounding,
  `tighter` check, floor-clamp-on-loosening) **and** `t["policy_state"] =
  new_state` (line 237) — confirmed by direct indentation inspection that
  line 237 sits at the same indent level as the `if cfg.anchor_mode ==
  "checkpoint":` block starting at line 189, i.e. inside `if
  mae_atr_budget is not None:`, not sibling to it.
- The `else:` at line 238 (`self._diag["policy_lookup_miss"] += 1`) is
  still the only thing that runs on a missed lookup — `t["policy_state"]`
  is untouched in that case, exactly as verified in the prior re-audit
  pass. This part of the code was **not touched** by the S7 fix (the diff
  only added/reorganized the `new_state == STATE_NONE` sub-branch and its
  guard condition; the `else` (non-NONE) branch's internal logic is
  byte-for-byte the same control flow as the prior pass, just re-indented
  one level deeper to sit inside the new unified `if`).
- Traced `if tighter or new_state < t["policy_state"]:` (line 201) and the
  existing S7 floor-clamp for `TIGHTENED->ARMED`/`TERMINAL->TIGHTENED`
  (lines 222-228, `if cfg.reversible_with_floor and new_state <
  t["policy_state"]:`) — this reads `t["policy_state"]` at lines 201 and
  222, both still *before* the line-237 write in this same branch, so no
  new ordering bug was introduced here either (mirrors the answer to
  Question 2, applied to the sibling branch).
- No new variable shadowing, no new early return, no change to the
  `_diag` counter's key name or increment logic.

**Verdict: CLEAN. No regression.** The "advance state only on successful
lookup" fix from the original CRITICAL remains fully intact after this
restructuring.

---

## New Note

### `policy_strategy.py:178-181` — the "genuinely never armed" `else` fallback is unreachable dead code today

As derived while answering Question 3: given `next_policy_state`'s current
monotonic-ratchet guarantee for S1-S6 and the outer
`new_state != t["policy_state"]` gate, the `else` branch that sets
`t["policy_stop_price"] = None` (as opposed to the floor-clamp branch) can
never actually execute under the code as it exists today — every runtime
path that reaches `if new_state == STATE_NONE:` at all has already
guaranteed `t["policy_state"] != STATE_NONE` (that's the precondition for
the outer gate to fire with `new_state == 0`), and for the only config
family that can produce `new_state == STATE_NONE` from a non-NONE
`current_state` (`reversible_with_floor == True`, i.e. S7), the `if`
sub-condition is therefore always satisfied. This is **not a bug** — it's
inert, safe defensive code that does the conservative thing (clears the
stop rather than crashing) if some future edit to `next_policy_state` ever
allowed a non-reversible config to return `STATE_NONE` from a non-NONE
state. No action required; flagging only so a future reader doesn't spend
time trying to construct a test case that reaches it, and so it isn't
mistaken for exercised, verified behavior in any coverage report.

---

## Still outstanding (unaffected by this fix, unchanged from the prior re-audit pass)

- **WARNING** — `policy_strategy.py:172-197` (forward transition
  state/stop-distance decoupling on non-monotonic table cells) — not
  addressed by this fix, not regressed by it either. Still requires a user
  decision (accept as label-integrity-only, or enforce monotonic budgets at
  table-build time) before being considered resolved or explicitly waived.
- **WARNING** — `policy_strategy.py:162-197` (`anchor_mode="mfe"`/
  `"checkpoint"` stop prices only recompute on a state transition, not
  continuously) — not addressed by this fix, not regressed.
- **NOTE**s carried forward unchanged: feature-formula duplication
  (`policy_strategy.py:85-102`), asymmetric tick-rounding
  (`policy_strategy.py:172-175`), no driver script yet to verify
  `feature_cols`/`W0_FEATURES` wiring, and the `pd.qcut(duplicates="drop")`
  silent-decile-shrinkage note (`train_model.py:105`).

---

## Explicit clear-to-execute statement

**Zero CRITICAL findings remain** after this focused pass — both of the
original CRITICALs (decile tie-convention, missing-lookup state/price
desync) and the CRITICAL raised in the prior re-audit (S7 floor-bypass on
`ARMED -> NONE`) are now confirmed resolved by direct code trace, not by
assumption.

However, per this project's own audit-gate workflow ("repeat until zero
CRITICAL **and** either zero WARNING or user-acknowledged WARNING"), the
Phase 5/6 stop-policy code is **not yet unconditionally clear to execute**:
two WARNINGs remain open (the S1-S5 natural-loosening-with-no-floor
question from the very first pass, still requiring the user's explicit
product decision per that finding's own text, plus the newer forward-
transition state/stop-distance label-decoupling WARNING). Neither WARNING
is a correctness/causality defect — both are label-integrity or product-
intent questions — but per the gate's own standard, they need an explicit
user acknowledgment/waiver (not a silent default) before this counts as
fully cleared. If the user explicitly waives both (or the S1-S5 loosening
behavior is confirmed as intended design, and the forward-transition label
question is accepted as documented/acceptable), then the Phase 5/6
stop-policy code across all files in scope from the first two passes has
no remaining blocking issue and would be clear for its first NT execution.

---

*Second re-audit complete. Findings reflect read-only static analysis;
code has not been executed.*

---
---

# THIRD RE-AUDIT — Focused Verification of the `policy_state`/Stop-Distance Lockstep Fix

**Date:** 2026-07-11 (fourth pass, same day)
**Scope:** Focused, targeted re-read of the full current text of
`studies/_shared_exit_mgmt/policy_strategy.py`'s `_maybe_stop_policy_exit`
method (lines 63-247), verifying the user-described fix for the last
outstanding WARNING from the second re-audit pass (forward arm/tighten/
terminal transitions previously could advance `t["policy_state"]` to a new
label even when the newly-looked-up budget was WIDER than the currently-
applied stop — a label/stop-distance desync, never risk-increasing). Also
re-read `studies/_shared_exit_mgmt/stop_policy.py` in full (all 172 lines)
and `studies/_shared_exit_mgmt/policy_grid.py` in full, to independently
re-verify the status of the two other findings still carried as "open" in
the prior pass's bookkeeping, since the fix touches the same code region
those findings depend on.

**Auditor:** lookahead-auditor v1

## Summary (this pass)

- Critical: 0
- Warning: 1 resolved this pass (the targeted fix), 1 confirmed
  independently ALREADY-RESOLVED as a byproduct of re-derivation (see
  correction below), 1 confirmed still genuinely open
- Note: 0 new

---

## Q1 — Does the fix correctly close the WARNING? Can `policy_state` ever now show a value that doesn't match the applied stop distance?

**Yes, correctly closed. No, it cannot desync.** Current code
(`policy_strategy.py:183-238`, the non-`STATE_NONE` branch):

```python
cur_stop = t["policy_stop_price"]
tighter = (cur_stop is None or
              (d == 1 and new_stop > cur_stop) or
              (d == -1 and new_stop < cur_stop))
is_loosening = new_state < t["policy_state"]
if tighter or is_loosening:
    if cfg.reversible_with_floor and is_loosening:
        floor_price = ep + d * cfg.protect_floor_atr * safe_atr
        new_stop = max(new_stop, floor_price) if d == 1 else min(new_stop, floor_price)
    t["policy_stop_price"] = new_stop      # line 213
    t["policy_state"] = new_state          # line 231 -- SAME block
else:
    self._diag["policy_label_held_not_tighter"] = (
        self._diag.get("policy_label_held_not_tighter", 0) + 1)
```

Enumerated **every** write site to `t["policy_state"]` in the method (grepped
the full body): line 182 (`STATE_NONE` branch, paired with
`t["policy_stop_price"] = floor_price` at 177 or `= None` at 181, on the
*same* pass through the branch) and line 231 (this branch, paired with
`t["policy_stop_price"] = new_stop` at 213, same `if` block, same pass).
There is no third write site. In both cases the state write and the
stop-price write are unconditionally co-located inside the same
conditional body — there is no path where one executes without the other in
the same invocation. Since `_init_policy_state` also initializes both to
their matching "off" values (`STATE_NONE` / `None`) together, the invariant
"`policy_state` and `policy_stop_price` always change together" holds from
trade start through every subsequent bar. **A trade's `policy_state` label
can therefore never disagree with the stop distance actually in force.**
The previously-flagged scenario (forward transition advances label to
`TIGHTENED` while the stop still reflects the `ARMED` budget) is now
structurally impossible: if the new budget isn't `tighter` and isn't a
legitimate `is_loosening`, execution goes to the `else` and **neither**
value changes, so the trade is correctly still reported/labeled as
`ARMED` with the `ARMED` stop, not `TIGHTENED` with the `ARMED` stop.

## Q2 — Retry-until-tighter-or-exit: causally sound, no infinite loop, O(1) per bar?

**Sound, and correctly O(1) per bar; confirmed with one added nuance.**
Traced the outer gate's re-entry behavior explicitly:

- Since `t["policy_state"]` no longer advances on a "held" (`else`)
  outcome, `next_policy_state` is called again on the *next* bar with the
  same (unchanged) `current_state` argument. For the default ratchet
  (`stop_policy.py:172`, `max(current_state, target_state)`), as long as
  the checkpoint's decile/persistence/score_path continue to imply
  `target_state >= new_state` from before, `next_policy_state` returns the
  same `new_state` again, and the outer gate (`new_state != t["policy_state"]`,
  line 162) re-fires, re-entering the exact same lookup
  (`decile_for_state`/`lookup_recovery_mae`) against the **same, static,
  frozen table** — a single dict `.loc[]`-backed lookup, not a scan or
  search. This repeats every bar the trade remains open in that
  decile/persistence/score_path neighborhood, each iteration incrementing
  `policy_label_held_not_tighter` by exactly 1.
- **This is causally sound**: every one of these repeated lookups reads
  only (a) the frozen, pre-computed table (fit on train+validation, never
  touched at runtime) and (b) the trade's own current-bar state
  (`decile`, `persistence_bucket`, `score_path`, all derived from this
  trade's own past checkpoints only, per the already-confirmed Item 1/2
  feature-parity and score_path causality findings from the first two
  passes). No future bar's data is read at any point in this retry.
- **No infinite loop within a single bar's processing**: the retry is
  purely a consequence of the *strategy's normal per-bar callback cadence*
  (`_maybe_stop_policy_exit` is called once per 1s bar by the surrounding
  event loop) re-entering the same `if` block on subsequent, separate
  invocations — there is no `while`/recursive construct inside this method
  that loops until a tighter budget is found. Each individual call to
  `_maybe_stop_policy_exit` performs exactly one scoring pass, one
  persistence/score_path computation (bounded by the `deque(maxlen=64)`
  scan already audited as O(64) and unrelated to this fix), and at most one
  table lookup — genuinely O(1) (bounded-constant) work per bar, not O(n)
  in retry count.
- **Termination condition, traced precisely**: the retry stops on whichever
  of three things happens first — (a) a bar where the looked-up budget
  finally is `tighter` (or a legitimate `is_loosening`), which advances
  both state and stop together and clears the outer gate; (b) the trade's
  own state naturally regresses back to `t["policy_state"]`'s current value
  (e.g. decile drops back out of the tighten range, so `target_state` falls
  back to match `current_state` and `max(current_state, target_state) ==
  current_state` again) — this halts the retries without ever finding a
  "tighter" budget and without the trade exiting, a case worth being aware
  of but not a soundness problem, just a quieter resolution than "tighter or
  exit"; or (c) the trade exits via the baseline/stop mechanism, ending the
  method's per-trade lifetime entirely. All three are benign, bounded
  outcomes — no scenario hangs or loops unboundedly within the backtest.

**Verdict: sound. O(1) per bar, confirmed.** (Nuance for the record: the
retry can also silently stop because the trade's own decile regressed back
to the currently-held state — not only "tighter found" or "trade exits" as
literally enumerated in the question — this is a third, equally benign
termination path worth knowing about but does not change the soundness
conclusion.)

## Q3 — `self._diag["policy_label_held_not_tighter"]` pattern and dict identity

**Confirmed on both counts.**
- Pattern match: `self._diag["policy_label_held_not_tighter"] = (
  self._diag.get("policy_label_held_not_tighter", 0) + 1)` (lines 232-235)
  is textually the same `.get(key, 0) + 1` idiom as
  `self._diag["policy_lookup_miss"] = (self._diag.get("policy_lookup_miss",
  0) + 1)` (lines 236-238) two branches below it, and also matches the
  pre-existing `entries_rejected_atr_not_warmed` counter pattern already in
  `base_strategy.py:308-309` — this is an established, already-in-use
  convention for dynamically-added diagnostic keys in this codebase, not a
  one-off.
- `self._diag` identity: confirmed `self._diag` is initialized as a real
  dict literal in `ExitManagementBaseStrategy.__init__`
  (`base_strategy.py:142-152`), the same object `self` the mixin's methods
  run against (no shadowing — `StopPolicyMixin` defines no `__init__` of its
  own, no other assignment to `self._diag` exists anywhere in
  `policy_strategy.py`). Confirmed it is logged (`self.log.info(f"Diag:
  {self._diag}")`, `base_strategy.py:518`) and persisted verbatim to
  `diag.json` via `json.dump(self._diag, f, indent=2)`
  (`base_strategy.py:534`) in `on_stop`, unconditionally for any run with
  `output_dir` set. The new key will therefore genuinely surface in every
  run's `diag.json`, not merely live in memory. **Confirmed.**

## Q4 — Re-confirm the two things not disturbed by this specific edit

**(a) Missing-lookup branch (`else` for `mae_atr_budget is None`) —
untouched, confirmed.** Current lines 236-238 are byte-identical in control
flow to what was verified in the second re-audit pass (state untouched,
only `policy_lookup_miss` increments). The only change in this region
across the two passes is the addition of `is_loosening` (line 201) and the
new `else` sibling at 232-235 sitting *inside* the `if mae_atr_budget is not
None:` block (line 188) alongside the pre-existing success path — the
`else` at line 236 (for a `None` `mae_atr_budget`) remains a separate,
outer-level sibling to that entire `if`, unmodified. **Confirmed untouched.**

**(b) `STATE_NONE`/S7 floor-clamp branch — untouched, confirmed.** Current
lines 163-182 are line-for-line identical to the code verified clean in the
second re-audit's Questions 1-3 (the `if (cfg.reversible_with_floor and
t["policy_state"] != STATE_NONE):` floor-clamp fork, paired
state/stop-price writes at 176-177/181-182). This fix's diff is entirely
confined to the sibling `else` branch (183-238, specifically the
`tighter`/`is_loosening`/`else` restructuring at 198-235) — it does not
touch, share a variable with, or change the control flow of the
`STATE_NONE` branch in any way. **Confirmed untouched, still correct.**

---

## Correction to the prior pass's carried-forward bookkeeping (found while independently re-deriving current status, not asked directly but material to the closing question)

Re-reading `stop_policy.py` in full this pass (not just the excerpted
`next_policy_state` body) surfaced that the **original Item 4 WARNING**
("S1-S5 natural loosening removes an already-earned protective stop with no
floor") has, in fact, **already been resolved** in the code as it exists
today — not merely "still open, pending a user decision" as the prior two
passes' summary bookkeeping continued to carry it. Evidence:

- `stop_policy.py:19-26`'s module docstring now states explicitly:
  *"User-confirmed 2026-07-11: state is MONOTONIC (forward-only, never
  loosens) for every policy EXCEPT S7. A stop, once armed/tightened, must
  never give back protection purely because the model's weakness estimate
  ticked down a decile."*
- `next_policy_state`'s own docstring (`stop_policy.py:139-146`) repeats
  this explicitly as a **user-confirmed** design decision, not an
  assumption: *"a stop, once armed/tightened, must NEVER loosen back out
  purely because the model's momentary weakness estimate ticked down a
  decile -- this overrides the study spec's original framing of S1-S5 as
  'naturally re-deriving' state."*
- The code enforces this: the default (non-`reversible_with_floor`) branch
  is `return max(current_state, target_state)` (`stop_policy.py:172`), which
  is `>= current_state` by construction for every S1-S6 config — already
  independently re-verified via code trace in this pass and in the prior
  two passes (Item 3(a)/Question 3 above).

This means the original Item 4 WARNING is not an open product question
still awaiting a decision — **it already has an explicit, documented user
decision on record, and the code correctly implements that decision.** The
prior re-audit passes' "still outstanding" / "explicit clear-to-execute"
sections continued listing it as unresolved by inertia (carried the label
forward without re-deriving against the current docstring text each time);
this pass corrects that. **Reclassifying: RESOLVED (user-confirmed design,
code-enforced, verified by trace), not an open WARNING.**

The **other** open WARNING — `anchor_mode="mfe"`/`"checkpoint"` stop prices
only recomputing on a state transition rather than continuously while a
trade sits in one stable state — remains genuinely open. Re-confirmed this
pass: the entire stop-price computation block for the non-`STATE_NONE`
branch is still nested inside `if mae_atr_budget is not None:`
(`policy_strategy.py:188`), itself only reached when
`new_state != t["policy_state"]` (line 162) fires, i.e. only on an actual
state transition. Nothing in this session's fix touches this — it is a
separate design characteristic (never risk-increasing, since a frozen stop
is still a valid, previously-computed protective level; simply not as
tight as a continuously-trailing MFE-anchor would imply), and per the
project's own gate standard it still needs an explicit user
acknowledgment/waiver (or a code change to recompute the anchor every bar
while in a stable state) before being considered closed. **Status:
unchanged, still open.**

---

## Explicit clear-to-execute statement (final, this component)

**Zero CRITICAL findings and zero unresolved WARNINGs of the label-desync/
correctness class remain.** Specifically:

- Both original CRITICALs (decile tie-convention; missing-lookup state/
  price desync) — RESOLVED (first re-audit pass).
- The S7 `ARMED -> NONE` floor-bypass CRITICAL (found during the first
  re-audit, fixed and verified in the second re-audit) — RESOLVED.
- The `score_path` lookback-selection WARNING (Item 2 of the original
  pass) — RESOLVED (first re-audit pass).
- The S1-S5 natural-loosening-with-no-floor WARNING (Item 4 of the
  original pass) — RESOLVED, per the correction above: a user-confirmed
  design decision is now recorded in `stop_policy.py`'s docstrings and the
  code enforces it (monotonic ratchet for S1-S6, `max(current_state,
  target_state)`), independently re-verified by trace in three separate
  passes now.
- The forward-transition `policy_state`/stop-distance label-decoupling
  WARNING (raised in the first re-audit pass, the subject of this fourth
  pass's fix) — **RESOLVED this pass**, per Q1 above: state and stop price
  are now written exclusively together, in the same conditional body, at
  every write site in the method. No path exists for the label to diverge
  from the applied stop distance.

**One WARNING remains genuinely open and unaddressed**: `anchor_mode="mfe"`/
`"checkpoint"` stop prices recompute only on a state transition, not
continuously while a trade sits in a stable state (first raised in the
original pass, re-confirmed unchanged in every subsequent pass including
this one). This is not a causality/correctness defect — the stop is never
stale in the unsafe direction, it simply doesn't advance as far as a
continuously-trailing interpretation of "MFE-anchored" might suggest to a
reader of the docstring — but per this project's own audit-gate rule
("repeat until zero CRITICAL and either zero WARNING or user-acknowledged
WARNING"), it requires an explicit user decision (accept the
transition-only recompute as intended, or request a code change to
recompute continuously) before the component can be marked unconditionally
clear.

**Bottom line:** the Phase 5/6 stop-policy component (`stop_policy.py`,
`policy_strategy.py`, `policy_grid.py`, and the two per-study
`policy_strategy.py` subclass files, all files audited across this and the
three prior passes) has **zero remaining CRITICAL findings** and **zero
remaining WARNINGs of ambiguous/undocumented behavior** — every WARNING
that could silently corrupt or mislabel results is now resolved and
verified by trace. It is **not yet unconditionally "zero outstanding"**
in the strictest reading of the gate, because one WARNING (`anchor_mode`
recompute cadence) remains open pending the user's explicit
accept-or-change decision. If the user acknowledges/waives that one
remaining item (or confirms transition-only recompute is the intended
"MFE-anchored" semantics), the component has no other blocking issue and
is ready for its first NT backtest execution.

---

*Third re-audit complete. Findings reflect read-only static analysis; code
has not been executed.*
</content>

## FINAL: All findings resolved or user-acknowledged (2026-07-12)

- CRITICAL [decile_of tie convention]: FIXED (side="left"), unit-tested against pd.cut for 13 values including every interior edge -- all match.
- CRITICAL [state advances without price on missing lookup]: FIXED (state only advances inside the successful-lookup branch; misses tracked via self._diag["policy_lookup_miss"]).
- CRITICAL [S7 floor-bypass on ARMED->NONE loosening]: FIXED (floor-clamped, not cleared to None, whenever reversible_with_floor and previously armed).
- WARNING [S1-S5 natural loosening]: RESOLVED by explicit user decision -- monotonic ratchet (never loosen) is now the default for all non-reversible policies (S1-S6); S7 remains the sole, floor-clamped exception. Documented consequence: S6 is mechanically equivalent to S4 and is expected to be statistically indistinguishable in Phase 6/7 results -- to be reported as a finding, not hidden.
- WARNING [score_path lookback selection mismatch]: FIXED (live selection now matches the offline two-pointer "first element >= target_ts" convention exactly).
- WARNING [forward-transition label/stop-distance desync]: FIXED by explicit user decision -- policy_state now only advances in the same conditional branch that actually changes policy_stop_price (tracked via self._diag["policy_label_held_not_tighter"] when a lookup succeeds but isn't tighter).
- WARNING [anchor_mode stops only recompute on state transitions, not continuously]: ACKNOWLEDGED by explicit user decision -- kept as discrete-transition-only (matches the spec's literal arm/tighten/terminal framing); not a correctness bug, no code change.

Status: 0 CRITICAL, 0 open WARNING. Cleared for first NT execution.
