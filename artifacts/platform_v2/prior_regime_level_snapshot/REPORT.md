# Chore `prior_regime_level_snapshot` — `tracker.regime.prior_level_snapshot`

Requested by `studies/nq_mtf_regime_structural_geometry_atlas` (`CAPABILITY_REQUEST_prior_regime_level_snapshot.md`).
Base: `main` @ `d83be2fd`. Branch `chore/prior_regime_level_snapshot`.

**Status: PRIOR_REGIME_LEVEL_SNAPSHOT = IMPLEMENTED_AND_CAUSAL.** The registry lists it as `verified`, and the
requesting `study.yaml` compiles UNCHANGED (3 trackers, 39 `prior_*` metadata columns).

## What was built

| file | role |
|---|---|
| `features/trackers/regime_prior_level_snapshot.py` | `RegimePriorLevelSnapshotBinding`; the docstring is the authoritative schema |
| `features/tests/test_regime_prior_level_snapshot.py` | 6 hand-derived unit cases + 9 end-to-end (compiler → HostCore → StreamMux) cases against a test-only oracle; also writes the parity artifact |
| `artifacts/parity/regime_prior_level_snapshot.json` | parity artifact: 0 mismatches over 14,400 + 13,565 instants × 3 timeframes, with and without gaps |
| `research_workflow/capabilities/proposals/tracker.regime.prior_level_snapshot.yaml` | proposal with the reset, null and gap policies |
| `research_workflow/capabilities_index.yaml` | seed entry, promoted (registry `content_sha256` 647835222d56…) |

Binding: `{tracker: regime.prior_level_snapshot, bars: <stream>, regime: <regime.dual_ema tracker>}`. There are no parameters.
The code has no timeframe logic, so any timeframe `regime.dual_ema` supports works. It was verified at 5m, 15m and 1h,
and at 5m bound to its own 5m stream.

### One causal truth: design

The binding owns one instance of the canonical `RegimeExcursionBinding` class. It feeds that instance exactly as a
sibling `regime.excursion` with the same `bars`/`regime` would be fed. On the regime's `changed` event it reads that
object BEFORE forwarding the reset. Every price and ratio in the snapshot is that object's own state or property;
there is no second extreme or ATR formula. The e2e test compares each snapshot, bit for bit, with the separately
bound sibling `excursion_<tf>` state immediately before its reset (>60 rotations).

The trade-off: at runtime it keeps a second instance of the accumulator (O(1) per source bar) instead of reading the
sibling tracker object. The alternative was a hook inside `RegimeExcursionBinding`. That would have edited
`features/trackers/host_bindings.py`, which is in the execution closure of every sealed V2 study. Freezing from
another tracker object would also have depended on subscriber ordering. The current design needs neither.

`GenericCompletedRegimeGeometryProvider._prior` was **compared, not consolidated.** It sits in sealed closures via
the regime-geometry adapter, so consolidating it would stale those studies. See "Overlap" below.

## Public schema (all fields readable via `features.metadata: {col: <tracker>.<field>}`)

Every snapshot field is null until the first regime completes. After that, the snapshot is replaced whole at each
`changed` of the same tracker, and nothing else writes it.

| field | definition |
|---|---|
| `dir` | direction of the COMPLETED regime (±1), never the successor's |
| `start_ns` | completed regime's `start_ns` (close ts of the bar that established it) |
| `end_ns` | close ts of the `<tf>` bar whose `changed` terminated it (= successor `start_ns`) |
| `start_price` | `regime.excursion.start_price` (= establishing bar OPEN, = `regime.dual_ema.start_price`) |
| `end_price` | canonical terminal price; see below |
| `end_price_ts` | `ts_init` of the source bar `end_price` is the close of; always `< end_ns` in practice, `<= end_ns` by contract |
| `transition_close` | close of the terminating `<tf>` bar (the `changed` payload `close_price`); a separate quantity |
| `frozen_atr` | completed regime's frozen ATR (`regime.excursion.frozen_atr`); null if not > 0 |
| `duration_s` | `(end_ns − start_ns)/1e9`; with no gaps this is `(bars+1)·tf` |
| `bars` | `regime.dual_ema.bars_in_regime` after the last `<tf>` bar the regime survived (the establishing bar counts 0) |
| `mfe_price` / `mae_price` | `highest_high`/`lowest_low` (dir +1) or the reverse (dir −1), raw |
| `mfe_atr` / `mae_atr` | bit-equal to `regime.excursion.mfe_atr/mae_atr` just before the reset; null when `frozen_atr` is null |
| `terminal_displacement_atr` | bit-equal to `regime.excursion.pnl_atr` just before the reset = `dir·(end_price − start_price)/frozen_atr` |
| `regime_seq` | the regime tracker's `changed_seq` that established the completed regime (provenance id) |
| `frozen_at_ns` | availability clock: the instant the snapshot became readable (= `end_ns`) |
| `rotation_seq` | monotone rotation count; 0 = no completed regime yet (never null) |

## End-price semantic (the decision)

**`end_price` = the close of the last source bar that the completed regime's own excursion accumulator observed.**
This is `regime.excursion.last_close` immediately before the reset, and `end_price_ts` is that bar's `ts_init`.

Why this price, from the platform contract:

1. The mux publishes a closed `<tf>` window *before* the source bar that closed it (`research_workflow/host/mux.py`
   `_apply`).
2. So the regime's `changed` fires, and the excursion resets, before the terminating window's last source bar is
   applied. That bar goes to the successor's accumulator. When `bars` and `regime` share one stream, the whole
   terminating bar goes to the successor.
3. This assignment is existing `regime.excursion` behaviour. It is declared here, not changed.

With this definition, `end_price` comes from the same bar set as `mfe_price`/`mae_price`. That gives two
invariants, both asserted on every completed regime in the tests:

- `mae_price ≤ end_price ≤ mfe_price`
- `−mae_atr ≤ terminal_displacement_atr ≤ mfe_atr`

Using `transition_close` would break both, because it prices a bar the successor owns.

Four prices are kept distinct and never substituted for each other:

| price | where it lives |
|---|---|
| last own close | `end_price`, at `end_price_ts` |
| terminating-bar close | `transition_close`, at `end_ns` |
| terminating-bar OPEN | the successor's `start_price` |
| next bar's open | not exposed |

For a 1m source under an HTF regime, `end_price_ts = end_ns − 60s` when there is no gap. After a source gap it can
be earlier (declared, not repaired).

Pre-existing, unchanged: the platform already carries two other "end close" meanings.

- `regime.dual_ema`'s `changed` payload `prior_end_close` = the flip-bar close, or the reference close.
- `GenericCompletedRegimeGeometryProvider` `end_close` = the close of the last `<tf>` bar before the flip.

The second one equals `end_price` exactly when the snapshot is bound to the regime's own stream (tested).

## Reset / gap / null policy

- **Reset:** rotation happens on the input regime's `changed` and on nothing else. `regime.dual_ema` has no
  session, day or gap reset and never returns to 0, so the snapshot persists across sessions, halts, weekends and
  gaps. The first `changed` (0 → ±1) rotates nothing.
- **Gap:** no gap logic of its own. A closed-window zero-volume fill bar is a regime bar and can terminate a regime.
  The parity run exercises 9 (5m) and 3 (15m) filled windows and a 2h closure (no fill).
- **Null:**
  - All snapshot fields are null before the first completed regime.
  - The ATR-denominated fields are null when the frozen ATR was not positive (regime established before ATR warmup).
    `regime.excursion` reports `0.0` there; this is an intentional difference: null, never a fabricated 0.
  - `end_price`, `end_price_ts` and `terminal_displacement_atr` are null if no source bar reached the completed
    regime's accumulator.

## Tests

`features/tests/test_regime_prior_level_snapshot.py` has 15 tests. All pass, in 18 s.

| # | invariant / request test | test |
|---|---|---|
| inv 1 | no prior before first completed regime | `test_no_prior_before_the_first_completed_regime`; e2e oracle (rotation_seq 0 → all null) |
| inv 2, req 7 | freeze at transition = accumulator before reset; ATR parity | `test_freeze_at_transition_…`, `test_snapshot_equals_the_sibling_canonical_excursion_…` |
| inv 3, req 1–2 | immutability, no current-regime contamination | `test_immutable_and_uncontaminated_…`; e2e: unchanged at every instant between rotations |
| inv 4, req 3 | successive replacement exactly once, whole | `test_successive_replacement_…`; e2e rotation_seq +1 per rotation |
| inv 5, req 6 | raw extreme / price parity vs independent oracle | `test_every_published_snapshot_equals_the_raw_tape_oracle_at_every_instant[gaps=F/T]` |
| inv 6 | ATR of the completed regime, not current/successor | unit + sibling test (mutant "successor ATR" → 8 failures) |
| inv 7 | direction of the completed regime | unit + sibling test (`now.dir == −snapshot.dir`) |
| inv 8, req 5 | timestamp/price boundary, availability clock | oracle rule `1m ts_init < H` belongs to the completed regime; snapshot visible from `T ≥ H`; >50 checkpoints inside a terminating HTF window read the older snapshot |
| inv 9, req 4 | multi-timeframe isolation | `test_timeframes_rotate_independently` |
| inv 10, req 8 | replay determinism | `test_replay_is_bit_identical` (repr-level sha256) |
| req 9 | gap/session + closed-window fill | gaps scenario (47-min in-day hole + 2h closure) |
| req 10 | later 1m-flip checkpoint reads via `features.metadata`, compiler + host path | `test_subsequent_1m_flip_checkpoints_…` (every field, ns precision) |
| non-regression | regime/excursion values unchanged when observed | `test_observing_the_snapshot_changes_no_existing_…` (identical frames, `check_exact`) |
| overlap | vs `GenericCompletedRegimeGeometryProvider._prior` | `test_overlap_with_the_completed_regime_geometry_provider` |

Mutation check: each of three mutants makes the suite fail.

| mutant | failures |
|---|---|
| end_price := transition_close | 9 |
| freeze after reset | 9 |
| successor ATR | 8 |

## Overlap with `GenericCompletedRegimeGeometryProvider`

The provider was fed exactly as `research_workflow/provider_host.py` feeds it: `on_completed_bar` per `regime_bar`.
With the snapshot bound to the same 5m stream (`bars: 5m`), every overlapping field is **identical**:

- direction
- start_ns / end_ns
- start_price
- ATR
- high/low ⇔ mfe/mae price
- end_close ⇔ end_price

With `bars: 1m` the extremes and end price differ, and only because the bar SET differs:

- the provider takes whole `<tf>` bars, including the full establishing bar, through the bar before the flip;
- the snapshot takes the 1m constituents from the establishing close up to the flip minus one source bar.

These are declared differences; neither implementation is blessed. One further case: the provider skips unwarmed
bars, so its first regime can start later.

## Intentional differences from the capability request

1. Three extra fields: `end_price_ts`, `transition_close` and `regime_seq`. They carry timestamp provenance and an
   explicitly separate transition price. `frozen_at_ns` and `rotation_seq` are implemented as requested.
2. The ATR-denominated fields are **null** when the frozen ATR is not positive. `regime.excursion` reports 0.0 in
   that case, so "bit-equal" holds only where the ATR is positive.
3. `bars` follows `regime.dual_ema.bars_in_regime`: the establishing bar counts 0, so the total `<tf>` bars = `bars + 1`.
4. The `end_price` choice: the request allowed `excursion.last_close` or `dual_ema.last_bar_close`. The first was
   chosen; the second is exposed separately as `transition_close`.

## Fingerprint / closure consequences

- New files only, plus a `capabilities_index.yaml` entry.
- `host_bindings.py`, `base.py`, the mux, the host and the compiler are **untouched**. Sealed manifests contain the
  tracker modules a plan imports, not the index or registry, so no sealed study is staled.
- The new module enters a closure only when a study binds `regime.prior_level_snapshot`. It imports
  `RegimeExcursionBinding` from `host_bindings.py`, which is already in every V2 closure.

## Known limitations

- The binding runs its own accumulator instance (same class). It cannot share the sibling tracker's object.
- `end_price_ts` can lag `end_ns` by more than one source bar after a source gap.
- The snapshot is only as causal as its regime tracker. It becomes visible exactly when the tracker's `dir` change
  does, and it inherits that tracker's stream visibility.
- There is no `seconds_since_update` or `age_s` epoch field. Snapshot age is `T − frozen_at_ns`, as same-row
  arithmetic.
