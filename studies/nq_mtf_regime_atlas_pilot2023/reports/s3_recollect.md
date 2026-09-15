# S3 — RE-COLLECT THE PILOT — nq_mtf_regime_atlas_pilot2023

Session 2026-09-15 · human-attended · acceptance test of chore/bucketing_and_gate (main `d83be2fd`)
Frame **`5c6ce87874737d3af43421d566054d2a6b669f9a3c13a4a0afbdd07e15eb0ed1`** · plan `10209696…` · closure
`4e28ee0a…` · frame seal `b1a9298b…` · dataset NQ_1S_V2_GLOBEX digest `9e7aecb7…` · years 2023 only, 2026 not opened.
Supersedes frame `80e644d1` (plan `ed2b9dfa`, `complete_bucket`).

## 0. The number

| timeframe | 5s | 30s | 1m | 3m | 5m | 15m | 30m | **1h** | **4h** |
|---|---|---|---|---|---|---|---|---|---|
| bars 2023 (partition, incl. 5-day warmup) | 4,306,860 | 717,810 | 358,816 | 119,636 | 71,782 | 23,928 | 11,966 | **5,985** | **1,621** |
| bars at S2 (`complete_bucket`) | 1,346,678 | 139,039 | 358,816 | 11,667 | 5,513 | 1,026 | 318 | 28 | 0 |
| regimes seen at 1m epochs | 262,484¹ | 59,115¹ | 28,030 | 8,715 | 5,188 | 1,648 | 797 | **390** | **104** |
| regimes at S2 | 89,210 | 11,471 | 28,030 | 977 | 474 | 95 | 35 | **3** | **0** |
| `dir == 0` / ATR null share | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 (was 100%) |
| median `seconds_since_update` | 0 s | 0 s | 0 s | 60 s | 120 s | 420 s | 900 s | **1,860 s** | 7,260 s |
| p99 / max `seconds_since_update` | 0 / 0 | 0 / 0 | 0 / 0 | 120 s / 73.0 h | 240 s / 73.1 h | 3,660 s / 73.2 h | 4,800 s / 73.5 h | 14,486 s / 74.0 h | 46.8 h / 72.0 h |
| `empty_windows_published` | 506,972 | 1,903 | — (external) | 0 | 0 | 0 | 0 | 0 | 0 |

¹ distinct regime starts observed at the 1m cadence; a 5s/30s regime that opens and closes inside one minute is not
seen, so these are lower bounds. The 3m–4h counts are exact at 1m resolution.

**A1 worked.** 1h: 3 → **390**; 4h: 0 → **104**; median 1h tracker age at a checkpoint 2,594 h → **31 min**.

**"Thousands" at 1h is not reachable, and 390 is the expected value.** 2023 has 5,985 hourly windows in session.
The 1m regime rate on this tape is 358,816 bars / 28,030 regimes = one regime per 12.8 bars; the same rule applied
per timeframe predicts 3m ≈ 9,300 (8,715), 5m ≈ 5,600 (5,188), 15m ≈ 1,870 (1,648), 30m ≈ 935 (797), 1h ≈ 470
(390), 4h ≈ 127 (104) — every timeframe lands just under bars/12.8, consistently. The packet's bound was an estimate;
the bar count is the ceiling.

**The calendar-aware fill stayed inside trading days — exactly.** The replay window's `TRADING_DAY` rows hold
21,534,300 in-session seconds. 5s bars = 21,534,300 / 5 = **4,306,860 exactly**; 30s = /30 = **717,810 exactly**;
3m +1, 1h +4 over the in-session count (windows straddling early closes); 4h 1,621 ≤ 1,495 + 262 straddles.
Every in-session window was published once; none outside. The fill is 11.8% of 5s windows (quiet seconds), 0.3% of
30s, and 0 from 3m up (every 3m+ window contains a trade). No fill before the first trade.

**`TRACKER_STALENESS_IMPOSSIBLE` never fired.** Maximum observed staleness ≈ 74 h (a context bar last completed
before a holiday closure, read at the first epoch after it), against the 691,200 s bound.

## 1. Census — read before any table

| | |
|---|---|
| rows (1m checkpoints) | **353,358** · session-day clusters **258** (unique `session_close_ts`) · identity `(regime_start_ns, observation_ts)` 0 duplicates |
| unique 1m regimes | **28,030** · flips **28,029** (flip row = `bars_1m == 0` = `flipped_1m`: 28,029 = 28,029; `bars_1m == 1`: 27,480) |
| flips per session day | median 109, mean 108.6, range 75–140 |
| censored, flips | **258 / 28,029 = 0.92%** — trading-day close 258 · data gap 0 · chronology boundary 0 |
| censored, all rows | 3,180 / 353,358 = 0.90%, all SESSION_END (one censored flip per session day: the regime open at the close) |
| ETH / RTH (flips; **verification count, not a governed table**) | ETH **20,358** · RTH **7,671** (27.4%) · censored ETH 243 / RTH 15 — RTH = platform `session_windows` (08:30 CT, min(15:15 CT, close)] |
| collect wall time | controller `--through merge` **44m05s** (09:41:50 → 10:25:53 local; partition replay 2,502 s); smoke 115.6 s; register 5.3 s |
| owner interventions | **0** |
| frame-to-table | **34.7 s** (load 0.22, pipeline 32.9, verify 0.38) — 11 steps; S2's one step was 1.2 s |

The 1m population and its censoring are identical to S2's (28,029 flips, 258 censored, 3,180 censored rows):
A1 changed the context streams, not the 1m anchor. **Censoring is under 1% of flips, so the time-to-flip
distribution is essentially complete.**

## 2. Tables (EXPLORE record `~/.nt_research/explore/5c6ce878…/87629996ba2a/`, spec `explore/pilot_atlas.yaml`)

Every mean carries a session-day-clustered SE (`analysis.uncertainty.clustered_mean`, CR1, t with G−1 df,
cluster = `session_close_ts`). n_rows and n_clusters beside every number.

### T6 — 1m census (produced)
| class | −1 (rows / clusters) | +1 (rows / clusters) |
|---|---|---|
| flip_resolved_next_flip | 13,879 / 258 | 13,892 / 258 |
| flip_censored_session_end | 136 / 136 | 122 / 122 |
| flip_censored_gap / other / unresolved | 0 | 0 |
| checkpoint_not_anchor | 156,588 / 258 | 168,741 / 258 |
ETH/RTH split: not a governed table (no session column on the frame; G6) — verification count in §1.

### T2 — time to the next 1m flip, flips only (produced, by direction; **not by outcome sign**, see §3)
| direction | n_rows / clusters | censored | median | p10 / p25 / p75 / p90 / p99 (s) | mean ± SE (95% CI) |
|---|---|---|---|---|---|
| −1 | 13,879 / 258 | 136 | 540 s | 180 / 300 / 960 / 1,560 / 2,880 | 724.4 ± 5.5 (713.6–735.2) |
| +1 | 13,892 / 258 | 122 | 540 s | 180 / 300 / 1,020 / 1,680 / 3,240 | 778.1 ± 6.0 (766.4–789.8) |
| long − short | 27,771 / 258 | | | | **+53.7 s ± 7.9 (38.2–69.2)** |
Censoring-aware cumulative incidence at 60…7,200 s is in `t2_incidence.json` (now producible: `observed_seconds`).

### T3 — running path at 1m offsets (produced WITHOUT the outcome-sign cut), all flips
| offset (bars) | n_rows / clusters | MFE ATR ± SE | MAE ATR ± SE | P&L ATR ± SE |
|---|---|---|---|---|
| 0 (flip bar) | 28,029 / 258 | 1.092 ± 0.004 | 0.157 ± 0.001 | 0.928 ± 0.003 |
| 1 | 27,480 / 258 | 1.498 ± 0.005 | 0.201 ± 0.002 | 0.944 ± 0.005 |
| 2 | 25,735 / 258 | 1.756 ± 0.006 | 0.244 ± 0.002 | 1.060 ± 0.007 |
| 3 | 23,673 / 258 | 1.992 ± 0.008 | 0.269 ± 0.002 | 1.220 ± 0.008 |
| 5 | 19,718 / 258 | 2.438 ± 0.010 | 0.294 ± 0.003 | 1.573 ± 0.011 |
| 10 | 12,403 / 258 | 3.537 ± 0.019 | 0.317 ± 0.004 | 2.548 ± 0.018 |
| 20 | 5,089 / 258 | 5.557 ± 0.040 | 0.336 ± 0.008 | 4.444 ± 0.038 |

**Read with its conditioning.** A row at offset k exists only for a regime that survived k bars (n falls 28,029 →
5,089), so the rising P&L is survivorship, not drift: the regimes still open at bar 20 are the ones that moved.
The offset-0 MFE ≈ 1.1 ATR is the flip bar's own range from its open (the excursion start price is the flip bar's
open). This is exactly the shape Q3 needs the outcome-sign cut to interpret, and that cut is not available (§3).

### T5 — 1m flip time-to-next-flip by 1m / 5m / 15m / 1h direction (produced; every combination)
16 cells, 482–4,080 flips, 141–229 clusters each (`t5_alignment.json`). Fully aligned: dir −1 on all four
748.3 ± 9.5 s (4,080 / 229); +1 on all four 784.7 ± 13.1 s (2,981 / 227). Against all three HTFs: −1 flip in
+1 context 730.1 ± 13.5 s (2,104 / 216); +1 flip in −1 context 809.2 ± 13.6 s (2,985 / 222). Cells range
691–809 s; intervals overlap broadly. **Descriptive; nothing here is a finding.** T5's outcome/path by alignment is
partly in T4 below; its outcome-sign cut is not available.

### T4 — path at offsets by 1m × 5m direction (produced without outcome sign)
1,110 cells with clustered SEs in `t4_path_by_5m.parquet` (same survivorship conditioning as T3).

### T7 — giveback: MFE retained at checkpoints (produced, by direction)
| offset | −1: n / clusters, median (IQR) | +1: n / clusters, median (IQR) |
|---|---|---|
| 1 | 13,750 / 258, 0.647 (0.357–0.833) | 13,730 / 258, 0.667 (0.375–0.852) |
| 3 | 11,822 / 258, 0.611 (0.300–0.826) | 11,851 / 258, 0.632 (0.333–0.833) |
| 5 | 9,794 / 258, 0.636 (0.372–0.829) | 9,924 / 258, 0.667 (0.391–0.844) |
| 10 | 6,068 / 258, 0.724 (0.533–0.864) | 6,335 / 258, 0.736 (0.548–0.873) |
| 20 | 2,348 / 258, 0.808 (0.686–0.902) | 2,741 / 258, 0.810 (0.696–0.905) |
Retained at the regime's END (the contract's giveback ratio) needs the terminal checkpoint — not available (§3).

## 3. Not produced, and why (findings, not failures)

| table | status | missing capability |
|---|---|---|
| T1 | **not produced** | winner/loser needs the realized outcome flip-close → next-flip-close in ATR. No frame column carries it (`pnl_atr_1m` is running; the kernel emits times, not prices) and no registered op selects a regime's last checkpoint. Not substituted. |
| T3 / T4 / T5 by eventual outcome sign | not produced | same |
| T7 at regime end | not produced | same (terminal checkpoint) |
| T8 | **not produced** | no session-bucket column (G4) and no ETH/RTH column (G6: `feature.session_membership` has no runtime adapter) |
| T6 ETH/RTH | verification count only | same as T8 |

Now producible that S2 could not: T2 (observed_seconds, A5), clustered uncertainty on every mean (A6), grouped
distributions T3/T4/T5/T7 (A6), cluster counts on every cell.

## 4. Platform checks this session was the test of

- **A1 on real GLOBEX data:** §0. Sealed replay of `v2_shape_b_deep_pullback_5s` was verified bit-identical in the chore.
- **A2:** nine `regime_<tf>_seconds_since_update` columns added automatically; medians sane; bound never reached.
- **A3 in practice.** This recompile changed BOTH plan and closure, so it staled every gate on composite alone and
  cannot isolate A3; the controller regenerated prepare/readiness/preflight/tests/seal itself and **no gate file was
  deleted by hand** (S2 had to delete five). Isolated check, read-only, on this study's real gate artifacts after
  merge: real fingerprints → all 12 stages fresh; same fingerprints with only `plan_sha256` changed → **prepare,
  readiness, preflight, seal, smoke, collection, reconcile, merge stale; compile, tests, causal audit, contract
  audit fresh.** A3 holds.
- **A4:** `explore compile` checked the condition vocabulary (spec uses `eq`).
- **A5:** `observed_seconds == (resolved_at_ts − observation_ts)/1e9` on every smoke row, 0 null.
- **No runtime failure after compile + seal.** Smoke ACCEPTED first try; collection exit 0.

## 5. Changes this session

1. main `d83be2fd` merged (`797d8b16`); recompiled to plan `10209696` (`86745be9`).
2. `research_decision.yaml` corrected: flip anchor `bars_1m == 0` with `flipped_1m`; identity
   `(regime_start_ns, observation_ts)` (`checkpoint_index` null on 100% of rows); `completed_bar_semantics` now
   says closed_window. `study.yaml` comment corrected likewise.
3. `audit/pass_05.md` delta causal audit CLEAR (0 C / 4 W / 2 N). **It was written by the same agent lineage that
   implemented A1/A2/A5 — not independent; an independent pass on `mux.py` is recommended before the six-year seal.**
4. Smoke `3bd64a98`; collect..merge + FRAME_REGISTERED `be430e7d`; EXPLORE spec `explore/pilot_atlas.yaml`.

## 6. After

Sane per-timeframe counts, fill confined to trading days, staleness bounded, and tables carrying clustered
uncertainty: **the pilot's acceptance test passes and the six-year atlas can start** on the same contract
(chronology widened, 2026 prohibited) — with three things settled first or knowingly carried: (a) T1 and every
outcome-sign cut need a realized-outcome column or a terminal-checkpoint op (capability route); (b) T8/ETH-RTH need
G4/G6; (c) the independent causal review of the closed-window mux (pass_05 W-new).
