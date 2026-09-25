# Regime-sequence feature and outcome definitions

Code: `extract.py` (regime primitives, parity) → `sequence.py` (features, outcomes, atlas). Every number in the
study artifacts comes from these two scripts.

## Population and conventions

| item | definition |
|---|---|
| population | `TRADE_EVENT_TIMELINE.parquet` of `nq_post_entry_path_mechanism_2023`: 6,024 completed 1m V_A regimes (RTH), 205 development sessions |
| blocks | `TEMPORAL_SPLIT_2023.json` (`nq_target_a_constrained_stationary_2023`): A = `development_train`, 154 sessions (2023-01-03 … 2023-08-07); B = `development_validation`, 51 sessions (2023-08-08 … 2023-10-17). `final_holdout` (52 sessions from 2023-10-18) is never loaded |
| flip instant `S_i` | `regime_start_ns` = close of the 1m detection bar |
| flip price `P0_i` | close of the last 1s bar with `ts_init <= S_i` (= the detection-bar close; the price known at the flip). The engine anchor `start_price_1m` (= detection-bar **open**, `generic_collector.py:1148`) is kept for parity only |
| regime end `T_i`, `P1_i` | `terminal_ts` (the next opposite flip), close of the last 1s bar with `ts_init <= T_i`. Within a contiguous segment `T_i == S_{i+1}` and `P1_i == P0_{i+1}` |
| regime high/low | max high / min low of 1s bars with `ts_init` in `(S_i, T_i]`, together with `P0_i` |
| favourable extreme `fav_i` | regime high if long, low if short |
| ATR `A` | audited `atr` (`atr_entry_1m`) of the regime being classified; every feature at flip i uses `A_i` |
| trade | entry = open of the first 1s bar after `T0 = S_i + 15 s` (audited); exit = audited `terminal_exit_price`; gross = `terminal_gross_atr` |
| cost | `terminal_cost_points` is NULL in the audited frame, so ntr `nq_default_v1` is used: 1 tick slippage/side + $2.25 commission/side = 2.9 ticks = **0.725 pt** round trip; `net = gross − 0.725 / A` (mean ≈ 0.09A) |
| segment | maximal run of regimes in one session with `S_i == T_{i-1}`. There are 289 segments: 205 session starts plus 84 in-session holes, which are regimes absent from the collector universe (60 s – 89 min). History never crosses a hole or a session start |

**Causality:** a feature at flip i uses only regimes j < i of the same segment (all of them complete at `S_i`),
the 1m close grid at or before `S_i`, and the audited T0 HTF snapshot (T0 = entry instant). A feature whose
window is not fully covered is NaN, never truncated.

## Primary sequence features (18)

| family | feature | definition | min history |
|---|---|---|---|
| 1 density | `flips_30m` | prior flips with `S_j` in `(S_i − 30 min, S_i)`; NaN unless the segment start is ≤ `S_i − 30 min` (also `flips_10m`, `flips_20m`) | clock |
| 1 density | `dur_mean_3` | mean duration (min) of regimes i−3..i−1 | 3 |
| 2 efficiency | `eff_3`, `eff_5` | `abs(P0_i − P0_{i−k}) / Σ_{j=i−k}^{i−1} abs(P1_j − P0_j)` | 3 / 5 |
| 2 efficiency | `eff_clock_30m` | `abs(c_now − c_{−30m}) / Σ abs(Δ 1m close)` over the last 30 1m closes at or before `S_i` (the grid starts 70 min before the first RTH flip, so this is always defined) | clock |
| 3 progress | `prog_same_last` | `d_i·(fav_{i−2} − fav_{i−4}) / A`: did the last same-direction regime extend the previous same-direction extreme | 4 |
| 3 progress | `prog_opp_last` | `d_i·(fav_{i−1} − fav_{i−3}) / A`: did the last opposite regime's extreme move in the current direction (a higher low for longs) | 4 |
| 3 progress | `frac_new_ext_4` | share of regimes i−4..i−1 with `d_j·(fav_j − fav_{j−2}) / A > 0.25` (a meaningful new extreme versus the previous same-direction regime) | 6 |
| 4 overlap | `terr_ratio_5` | `(max hi − min lo over i−5..i−1) / Σ ranges`. 1 = no overlap; 0.2 = five identical ranges | 5 |
| 4 overlap | `chan_width_5` | union range of i−5..i−1 / A | 5 |
| 5 clustering | `flip_disp_6` | std of flip prices `P0_{i−6..i}` / A | 6 |
| 5 clustering | `n_near_0p5_6` | number of flip prices `P0_{i−6..i−1}` within 0.5A of `P0_i` (also 0.25A and 1.0A) | 6 |
| 6 level memory | `headroom_same` | `d_i·(fav_{i−2} − P0_i) / A`: distance to where the last same-direction regime stalled (negative = already through it) | 6 |
| 6 level memory | `fails_at_level` | how many of `fav_{i−4}`, `fav_{i−6}` lie within 0.5A of `fav_{i−2}` (0–2): "this stall level was tried before" | 6 |
| 7 expansion | `rng_mean_3` | mean range of i−3..i−1 / A | 3 |
| 7 expansion | `rng_ratio_3v3` | mean range of i−3..i−1 / mean range of i−6..i−4 | 6 |
| 8 HTF progress | `htf5_prog` | `dir_5m·(P0_i − start_price_5m) / atr_5m` (progress of the current 5m regime) | T0 snapshot |
| 8 HTF progress | `htf15_prior_disp` | `prior_terminal_displacement_atr_15m` (net displacement of the last completed 15m regime) | T0 snapshot |

Recorded but not binned: `prev_disp` (= −(flip-to-flip lag of regime i−1)), `dist_same_flip`, `flips_10m/20m`,
`n_near_0p25_6`, `n_near_1p0_6`, `htf5_prior_disp`, `htf15_prog`. EMA/band width is **not** in the audited frame
and was not rebuilt; family 7 uses realised regime ranges instead.

**Composite rotation score** (Phase 5; equal weights, no fitting): mean of block-A percentile ranks of
`1−eff_5`, `1−terr_ratio_5`, `flips_30m`, `1−frac_new_ext_4` and `n_near_0p5_6`. ROTATION = score ≥ block-A P80
(0.685), EXPANSION = score ≤ block-A P20 (0.362), otherwise MIXED. NO_HISTORY = any component missing, i.e.
fewer than 6 completed regimes or less than 30 min of covered segment history.

## Forward outcomes (regime i = the trade opened at this flip)

| outcome | definition |
|---|---|
| `nx_gross`, `nx_net` | flip-to-flip gross/net P&L of regime i (A) |
| `nx_disp` | `d_i·(P1_i − P0_i) / A` |
| `nx_mfe`, `nx_mae` | from entry, over 1s bars through `T_i` (A) |
| `nx_dur_min` | `(T_i − S_i)` in minutes |
| `nx_reach_{0p5,1p0,2p0}` | audited timeline first-touch flags (before the terminal flip) |
| `nx_fav_first` | +1A touched strictly before −1A |
| `nx_new_ext` | `d_i·(fav_i − fav_{i−2}) > 0` |
| `fw{2,3,4}_gross/net` | sum of flip-to-flip P&L of regimes i..i+k−1 (NaN when the segment ends first) |
| `fw3_eff` | `abs(P1_{i+2} − P0_i) / Σ abs(P1_j − P0_j)` over i..i+2 |
| `fw3_net_disp` | `abs(P1_{i+2} − P0_i) / A` |
| `fw3_flips_per_30m` | 3 / (duration of i..i+2 in 30-min units) |
| `fw3_terr` | union range of i..i+2 / Σ ranges |
| `fw3_escape` | largest distance of the i..i+2 union range from `P0_i` / A |
| `fw3_rotational` | `fw3_net_disp < 1A` (after 3 regimes, price is still within 1A of the flip) |

**Binning:** quintile edges are computed on block A only and applied to both blocks. Discrete features collapse
to their occupied levels. Uncertainty is a 300-replicate session-block bootstrap of top-bin minus bottom-bin
(pooled) or ROTATION minus rest.
