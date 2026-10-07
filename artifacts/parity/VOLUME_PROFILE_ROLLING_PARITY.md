# tracker.volume_profile.rolling — R0 parity and acceptance gates

Capability: `features/trackers/volume_profile_rolling.py` (kernel `VolumeProfileKernel` + binding
`VolumeProfileRollingBinding`); proposal `research_workflow/capabilities/proposals/tracker.volume_profile.rolling.yaml`.

## Oracle

The study-local R0 (never imported by the capability): `studies/nq_auction_map_1s/auction_map.py` (`vr` channel,
`open_minutes`, `a_series`, roll `reset_pos`), `studies/nq_poc_node_edge_rejection/poc_node.curve`,
`vp_v1.value_area` / `vp_v1.profile`, `studies/nq_vp120_edge_fade/vp120_profile.build`. Stored ledgers (read-only,
`_2022` / `_2023dev` only): `PROFILE_<block>.parquet` (120 open minutes, full window only),
`MP_VP6H_<block>.parquet` (360), `MP_VP24H_<block>.parquet` (1,380 open minutes = one 23 h Globex session; the
legacy "24H" label; parity horizon only — the scientific 24 h horizon is 1,440).

Input: the oracle's own tape cache (`CausalDataLoader` output of `NQ_1S_V2_GLOBEX`, ts = ts_init); sessions and
rolls from the catalog's hash-verified reference tables (`dataset_v2.load_reference_tables`). The kernel starts at
the oracle origin (`poc_node.prepare_block`: open of the second session before the block).

## Result (`volume_profile_rolling_r0_{2022,2023dev}.json`)

| block | horizon | oracle rows | joined | missing | POC diff | VAH/VAL diff minutes | = exact rational walk | pair tie | stop tie |
|---|---|---|---|---|---|---|---|---|---|
| 2022 | 120 | 353,630 | 353,630 | 0 | 0 | 8 | 8 | 7 | 1 |
| 2022 | 360 | 353,830 | 353,830 | 0 | 0 | 4 | 4 | 0 | 4 |
| 2022 | 1380 | 353,830 | 353,830 | 0 | 0 | 0 | — | — | — |
| 2023dev | 120 | 281,793 | 281,793 | 0 | 0 | 23 | 23 | 22 | 1 |
| 2023dev | 360 | 281,943 | 281,943 | 0 | 0 | 0 | — | — | — |
| 2023dev | 1380 | 281,943 | 281,943 | 0 | 0 | 0 | — | — | — |

A (smoothing scale) is bit-identical on every joined row; window low / high identical; HVN / LVN counts and HVN
centres identical on every 360 / 1380 row (the VP120 ledger stores no nodes); value-area fraction differs only on
the 35 tie minutes.

**Explained population divergence: `LEGACY_WARMUP_OUTPUT_DIVERGENCE` (not a parity failure).** The capability
publishes 280 timestamps per horizon at 360 and 1380 (2022: 160 = 4 rolls x 40; 2023dev: 120 = 3 rolls x 40) that the
legacy ledgers do not contain; 0 at 120. Every one is a roll-truncated minute roll+30 .. roll+69 (00:30-01:09 UTC on
each roll day, `window_minutes` 30-69, `window_complete` false). The legacy writer (`vp_v1.run_block`) skips a minute
while `vp_v1.atr_series` is NaN; that Wilder ATR(14) of 5-minute bars is re-seeded at every roll and first defined at
the 14th 5-minute bar end after it (roll + 70 min) -- which is exactly the first legacy row after each of the 7 rolls,
with 0 legacy rows missing afterwards. The capability's eligibility is `window_minutes >= min_window` (30) and A
defined; no row is `window_complete`, so the primary (`window_complete == true`) population is unaffected.
Per-roll evidence: `volume_profile_rolling_roll_warmup.json` (`scripts/parity_volume_profile_rolling_roll_warmup.py`);
summary: `volume_profile_rolling_divergences.json`.

**`LEGACY_FLOAT_TIE_DIVERGENCE` (no numerical epsilon).** 35 of 1,906,969 joined snapshots (0.0018%) differ in VAH or VAL
by one two-tick step. In every one the capability equals an independent exact-rational re-walk of the window
(`fractions.Fraction`, built in the parity script directly from the bars), and the oracle does not. Each such walk
contains an exact tie that the oracle's float arithmetic broke: 29 pair ties (the two-tick pairs above and below
are rationally equal; the oracle rule is "tie adds both") and 6 stop ties (the accumulated volume equals exactly
70% of the total; relative gap 4.4e-17, i.e. the rounding of the float product 0.7 x total decided). POC: zero
differences. By horizon: 120 = 29 pair + 2 stop, 360 = 4 stop, 1380 = 0. All 35 cases (ts, capability / oracle /
exact VAH and VAL, class) are listed in `volume_profile_rolling_divergences.json`. The parity contract stays exact:
POC, A, window bounds, node / LVN / HVN structure exact; VA exact except where the exact re-walk independently proves
a legacy float-tie artifact.

**How exactness is achieved.** Weights are int64 fixed point (scale 2^32), so the rolling add / subtract is exact
and order-independent (bit-identical to a scratch rebuild). range_uniform weights v/n are rounded per bar, so each
tick also carries the count of rounded contributions; a value-area comparison (pair or stop test) or a raw-argmax
choice whose margin lies inside the rigorous rounding bound (0.5 unit per contribution) is re-decided in exact
rational arithmetic from the window's per-minute (tick, n, volume) integer triplets. The first implementation
rounded without this and disagreed with the exact walk on all 16 mismatches of a 40-day probe (the oracle agreed
with it on 12) -- that is why the bound exists.

## Gates (`features/tests/test_volume_profile_rolling.py`, 12 tests)

- causal completed-bar timing: a snapshot of minute T is unchanged when bars after T are altered; the bar with
  ts_init == T closes minute T; T + 1 ns belongs to the next minute;
- Friday -> Sunday continuity: no synthetic minutes across a 49 h closure, the first Sunday bar closes only
  Friday's last minute, the window spans 6 Friday + 4 Sunday minutes with the exact volume;
- roll reset: a minute ending at the roll stays with the old contract; afterwards window and A restart,
  `roll_truncated` is set, `window_complete` returns exactly `horizon` minutes after the roll;
- full-window eligibility: profile fields null below `min_window` / undefined A; `window_complete` exactly when
  `window_minutes == horizon_open_minutes`; empty open minutes count and carry the close;
- incremental == scratch bit for bit for all three allocations; volume conservation (range_uniform within the
  rounding bound, close exact, full_per_tick = sum v x n, explicitly NOT conserving);
- exact tie: 3 x round(1/3) != 1 is flagged and resolved as a tie;
- binding fields == kernel snapshot; REQUIRED parameters enforced.

## Performance probe (`volume_profile_rolling_probe.json`)

First 7 days of 2022, horizons 120 / 360 / 1440 x the three allocations, each kernel incremental, every 97th
minute checked bit-for-bit against a scratch rebuild (71 checks per kernel, 0 mismatches). Seconds per kernel and
the full-study extrapolation are in the JSON; the full R0 parity runs took 540 s (2022) and 311 s (2023dev) for
three range_uniform kernels including the exact re-walks.

## Known limits / platform debt

- Tracker FIELDS are scalars: nodes are exposed as `hvns_json` / `lvns_json` strings; full profile vectors are
  available from the kernel (`snapshot(full=True)`) but not through the host sink.
- A minute's snapshot becomes readable on the bar with ts_init == T, else on the next bar (after a closure: the
  next session's first bar). Causal, but a minute with no bar at :00 is published late.
- `research cap scaffold` re-dumps the whole `capabilities_index.yaml` (comments and compact style lost); the
  file was restored by hand and only the new entry added.

## Merge gate (broad test_delta)

`python scripts/test_delta.py research_workflow/tests scripts/tests features/tests tests --baseline-reference c480d8af`
on e443c2b0 (6,190 s): 2,621 ran, 2,525 passed, 58 KNOWN_BASELINE_FAILURE, 1 BASELINE_FAILURE_NOW_FIXED, 11 NEW_FAILURE.
All 11 fail identically on a clean detached checkout of main 5fd71c48 (which lacks this capability): they are
main-side drift relative to the stale baseline reference, none touches a file of this change. Not re-baselined here.
