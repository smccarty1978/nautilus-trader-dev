# Stair-Step Exit Comparison — SPEC

## Goal
Can stair-stepped protection reduce the loser tail **without** cutting the
+2/+3 ATR runner tail? Same entries, one exit-management matrix, honest fills.

## Hard separation: DECISION clock vs EXECUTION
- **Decision** (when a stop migrates / stall counts / structure updates): the
  version's decision clock ∈ {1m, 5s} — uses COMPLETED bars only.
- **Execution** (does a stop fill, and where): ALWAYS 1s OHLC, chronological.
- A stop update becomes active on the **next** 1s bar.
- If a proposed stop is already crossed by the current 1s close → **clamp** to
  market-side (close ∓ 1 tick) or **skip** the update (never a phantom fill).
- Stops are **ratchet-only** (never loosen). Built on `utils/safe_replay`
  (`safe_stop_replay_armed`, validity-at-arm, `at_or_worse_close`) + the
  `utils/audit_replay_fills` gate (0 impossible fills required) + the
  replay-vs-runtime parity gate before any deployment claim.

## Entries (same across all exit versions)
- **A — raw 1m flips**; **B — bar1-confirmed flips**. From the flip-truth
  detector, 2021–2024, NQ `NQ.v.0`, 24h (RTH/ETH tagged).
- **Entry fill (realistic):** market on the FIRST 1s bar after the decision
  (flip-bar close for A, bar1 close for B), at that bar's open **∓ 1 tick**
  (long pays +1 tick). ATR = `atr_at_entry` (fixed) for every ATR-denominated
  level. Tick = 0.25 = $5; NQ mult = $20/pt.

## Cost model (net metrics)
- **PRIMARY baseline:** entry slippage = **0**, stop/market/regime/prove-it
  exits = **0.5 tick**, PT **limit** = 0, commission **$5 round-trip**.
- **STRESS case (clearly labeled):** exits = **1.0 tick** (entry still 0).
- Also report **gross** (no slippage, no commission).
- Slippage is applied in the metrics layer by exit reason, so one replay yields
  gross / primary-net / stress-net without re-running. Tick = 0.25 = $5.
- Do NOT present 1-tick entry + 1-tick exit as the baseline; that is stress only.

## Sides
`both` is executed; **long-only** is a reporting cut on the screen (offline
replay treats every flip as an independent trade, so the long-slice == an
offline long-only run). **However:** any candidate selected from the long-side
slice MUST be re-run as **true long-only** before NT validation — in NT's
flat-only NETTING a still-open short can block a later long entry, which the
offline independent-trade screen does not capture. Also report by long/short,
RTH/ETH, year.

## Catastrophic stop
Flip-bar-open cat-stop applies ONLY to the continuity baselines (V0, V4-legacy
if run). Clamp-or-skip if invalid at entry; report invalid-at-entry rate. New
versions use their own initial stop.

## Intra-1s-bar ambiguity
If one 1s bar's range spans both the protective stop and PT/structure target →
assume **stop fills first** (conservative).

---

## EXIT VERSIONS (reconciled — authoritative)

| id | name | clock | lifecycle |
|----|------|-------|-----------|
| **V0** | Regime baseline | n/a | flip-bar-open cat-stop (clamp/skip); exit on opposite 1m regime flip (market, next 1s). No PT. |
| **BR10** | Fixed bracket (control) | n/a | PT +2 ATR (limit), SL −1.0 ATR (stop); regime-flip backstop. |
| **BR15** | Fixed bracket (control) | n/a | PT +2 ATR (limit), SL −1.5 ATR (stop); regime-flip backstop. |
| **V1** | Fixed ladder | n/a | init −0.75 ATR; MFE≥0.5→−0.25; ≥1.0→BE; ≥1.5→+0.5; ≥2.0→+1.0 (ratchet). Exit on stop hit or regime flip. No PT cap (runners ride the ladder). |
| **V2** | Prove-it + ladder | 5s (gate) | init −0.75 ATR. Gate: @+30s if net<0 AND 5s-opposed→exit; @+60s if net<0→exit. After pass: V1 ladder. |
| **V3** | Prove-it + structure trail | 1m / 5s | init −0.75 ATR + gate (as V2). After pass: trail = ratchet of (min last-3 completed clock-bar lows) − 1 tick (long; mirror short). Exit on stop or regime flip. |
| **V4-D1** | Corrected MA stall trail (clamp) | 1m / 5s | init −0.75 ATR. Stall = consecutive clock-bars w/o new favorable extreme; stall≥3 → migrate stop toward SMA13(clock), **clamped** to market-side if crossed. Ratchet. Regime exit allowed. |
| **V4-D2** | Corrected MA stall trail (skip) | 1m / 5s | as V4-D1 but **skip** the update when the MA stop is already crossed. |
| **V5** | Hybrid prove-it + MA/structure | 1m / 5s | init −0.75 ATR + gate. After pass: stop=max(stop,−0.25). MFE≥1.0→SMA13 protection (corrected). stall≥3→ratchet to SMA13/structure. MFE≥2.0→no target, trail SMA13/last-3 5s-low, exit on regime flip. |

Distinct execution configs per entry population = 5 clock-agnostic
(V0, BR10, BR15, V1, V2) + 4 clock-swept × 2 clocks (V3, V4-D1, V4-D2, V5) = 13.
× {A, B} = **26 offline replay runs**; sides/session/year are reporting cuts.

## Metrics (per config; + by year, long/short, RTH/ETH)
net PnL, gross PF, net PF, mean & median ATR/trade, max DD, trade count, avg
hold, % exited by stop, % by regime flip, % reached +2 ATR, % **captured** +2
ATR, MFE-capture = exit PnL / max MFE (cond. MFE>0; report excluded share),
giveback = max MFE − exit PnL.

## Pipeline
1. Build executable entries (A, B) with realistic fills.
2. Build/stream 1s + 5s OHLC per trade window (5s from catalog 1s).
3. Offline exit engine (safe_replay) → 26 runs → metrics.
4. `audit_replay_fills` gate (0 impossible fills) on every run.
5. Rank; pick top 1–2; **NT BacktestEngine parity-validate** (median diff
   ≤ $5/trade) before any deployment statement.
6. Report: does any stair-step cut the loser tail without cutting the runner
   tail? (If no → the issue isn't stop design.)
