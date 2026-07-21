# NT Event-Driven Backtest — Original W4 Short-RTH Policy A (Phase 1)

## Decision

**`NT_SHORT_RTH_CONFIRMED`** (magnitude is mildly fill-sensitive)

The short-RTH Policy A pocket **survives** a NautilusTrader event-driven
implementation. It stays clearly positive in both years with strong structural
parity to the offline benchmark; the ~14% shortfall in total PnL is fully
attributable to the NT fill model (FOK market fills at the completed bar's
close) versus the offline next-open assumption — not to any signal, regime, or
management difference.

This is **Phase 1 — schedule-driven parity**: NT is fed the frozen 807-trade
short-RTH W4 entry schedule and validates Policy A management + NT fill/event
semantics with a **live** RegimeEngine. It is a 1-second OHLC event-driven
research simulation, not tick-level or live execution. Phase 2 (live signal
generation inside NT) is a separate follow-on and is not claimed here.

## Headline vs offline benchmark

| Split | NT trades | NT net $ | NT $/trade | NT PF | NT WR | NT maxDD | Bench net $ | Bench $/tr | Bench maxDD |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Combined | 807 | **23,270** | 28.84 | 1.149 | 32.3% | 15,000 | 27,013 | 33.47 | 14,331 |
| 2025 | 604 | 18,315 | 30.32 | 1.163 | 32.5% | 15,000 | 20,304 | 33.62 | 14,331 |
| 2026 | 203 | 4,955 | 24.41 | 1.111 | 32.0% | 11,730 | 6,709 | 33.05 | 11,144 |

Trade count is exact (604 / 203 / 807, **zero** overlap skips). Net PnL is
−$3,743 combined (−13.9%): −$1,989 in 2025 and −$1,754 in 2026. Profit factor
1.149 vs 1.174. Max closed-trade drawdown is marginally larger (fill-driven).

## Parity — the critical validation

- **Regime parity is exact.** The live catalog-fed RegimeEngine reproduced the
  offline raw-built canonical flip stream with **0 mismatches** in both years
  (27,166/27,166 flips in 2025; 8,935/8,935 in 2026). The fail-fast parity
  gate did not trip. Catalog and raw do **not** diverge for this v0 series in
  the trading window (including roll windows).
- **Alignment timing is exact.** All 406 aligned trades have an alignment
  timestamp identical to the frozen `confirm_flip_ns` (0 ns delta) — the live
  event loop identifies the aligning bearish flip at the same instant the
  offline atlas did.
- **Exit-reason agreement is 97.9%** (790/807 identical class). The 17
  off-diagonal trades are marginal bucket shifts from fill timing (e.g. 7
  offline confirmation-timeouts became NT pre-alignment stop-outs because the
  bar-close entry was a hair less favorable). Alignment-outcome agreement is
  99.5%.
- **Tie races are empirically zero.** Across both years: 0 post-stop, 0
  pre-stop, and 0 pre-align race flags. The max adverse excursion among
  opposite-flip exits is 1.47 ATR (< the 1.50 post stop) and among timeouts
  1.24 ATR (< the 1.25 pre stop), so no stop level was ever breached-but-not-
  filled. The audit's residual same-`ts_init` dispatch Note is immaterial here.

## Where the PnL comes from (combined, by exit reason)

| Exit reason | NT count | NT net $ |
|:--|--:|--:|
| opposite_flip (held to opposing flip) | 368 | +135,155 |
| confirmation_timeout | 139 | +30 |
| stop_after_flip (post-alignment 1.50) | 38 | −15,510 |
| stop_before_flip (pre-alignment 1.25) | 262 | −96,405 |

The edge is entirely the held-to-opposing-flip winners, net of stop losses —
the intended Policy A structure. Offline reason counts (372 / 144 / 36 / 255)
are within a few trades of NT.

## Source of the −$3,743 gap: the fill model

- Entry fills: 169 trades identical to offline, 460 within one tick (≤0.25),
  347 differing by >1 tick (median entry delta 0.0000, mean −0.074, max 3.75).
  NT fills a FOK market at the just-completed 1s bar's **close** (fixture-
  verified), whereas the offline sim used the **next 1s open**; at 1s
  granularity these usually coincide but not always.
- Per-trade PnL delta is roughly balanced (331 NT>offline, 392 NT<offline, 84
  identical), skewed slightly negative — fill-timing noise plus ~7 marginal
  trades tipped from timeout/flip into a pre-stop by the slightly worse entry.
- No slippage or spread model was added beyond the offline assumption; costs
  are $10 round-trip, $20/point, 1 contract. Gross and net differ only by the
  flat $10 cost. NT fills: FOK market at bar close; GTC stop-market at trigger
  (gap-through fills at trigger, none observed as a tie); no slippage model.

## Answers to the seven questions

1. **Positive combined under NT?** Yes: +$23,270 (807 trades, PF 1.149).
2. **Positive in both years?** Yes: +$18,315 (2025) and +$4,955 (2026); both
   PF > 1.10.
3. **How close is trade count?** Exact — 807 (604 + 203), zero skips.
4. **How close are PnL / PF / DD?** Net PnL 86.1% of benchmark (−$3,743); PF
   1.149 vs 1.174; max closed-trade DD $15,000 vs $14,331. Close, modestly
   lower.
5. **Which exit reasons produce the PnL?** The held-to-opposing-flip exits
   (+$135,155), offset by pre-alignment (−$96,405) and post-alignment
   (−$15,510) stops; timeouts net flat.
6. **What explains the differences?** Fills, not logic. Regime parity is exact
   (0 flip mismatches, 0 ns alignment delta), exit-reason parity 97.9%; the
   whole gap traces to the NT bar-close vs offline next-open entry fill and the
   ~7 marginal trades it re-buckets. No signal/RTH/ATR/timestamp-ordering
   divergence.
7. **Robust enough for a tick/queue realism pass?** Yes. The edge is stable in
   sign, both years, and structure, and the only degradation is fill-model
   magnitude — which is exactly what a tick/queue-aware execution pass would
   stress next. This is the warranted next stage.

## Convention disclosures

- **RTH = 08:30–15:00 America/Chicago** (matches the repaired prior studies'
  `is_rth` and the frozen `session` column that produced the 807-trade
  benchmark). The task text also wrote "15:15"; that conflicts with the named
  source, so 15:00 was used. RTH gates entry only; Phase 1 uses the frozen
  schedule so this choice does not affect these results (it would only matter
  for Phase 2 live generation near the boundary).
- **One-position NETTING backtest.** Overlapping entries would be skipped
  (`position_open_at_entry`); none occurred (0 skips), so the NT population
  equals the full 807.
- **Two drawdown types** are reported separately; the closed-trade-sequence DD
  ($15,000 combined) is the benchmark-comparable one. Mark-to-market DD is not
  claimed here (bar-level, 1 contract).

## Audit

Pre-execution lookahead audit: **PASS — 0 CRITICAL, 0 WARNING** (4 passes;
`audit/pre_execution_audit.md`). The original CRITICAL (no live-engine vs
frozen-source parity check) was closed by the fail-fast flip-parity gate, which
then confirmed exact regime parity at run time. Completion validation is the
empirical parity result above (`audit/completion_audit.md`).

The Parquet/JSON deliverables are authoritative for every trade, reconciliation
row, parity figure, and monthly value.
