# Original W4 Short-RTH Threshold Ladder — Entry-Timing Diagnostic

## Decision

**`EARLIER_THRESHOLD_ADDS_TOO_MANY_FALSE_STARTS`**
(and, on the confirmed pocket, `CURRENT_THRESHOLD_STILL_BEST`)

Lowering the prevailing-long W4 weakness threshold does **not** improve the
short-RTH pocket. On the exact confirmed 807-trade pocket, earlier entry
monotonically **worsens** PnL; the only place a lower threshold shows a higher
total is the candidate basis at 0.675, and that gain is pure added-trade volume
with worse per-trade economics and worse drawdown. Keep the current 0.688350
threshold. The entry trigger is not the lever — the next step is short-RTH-only
retraining on earlier years, not an earlier threshold.

Offline 1-second OHLC research simulation, not retraining or optimization. RTH
08:30–15:00 America/Chicago (entry only). NQ $20/pt, $10 RT, 1 contract. Policy
A unchanged (1.25 pre / 300s timeout / 1.50 post / opposing flip). Both control
gates reproduced exactly (candidate 650/222; fixed-807 604/203 = +$27,013).

## Two bases (per user direction)

- **Candidate basis** — first-crossing short-RTH entry per prevailing-long
  regime (control = 872), independent Policy A. Captures the "added trades" a
  lower threshold creates.
- **Fixed-807 basis** — the exact confirmed pocket (the globally one-position-
  executed 807), holding the population fixed and moving each entry to the
  earlier crossing within the **same** regime. Pure entry-timing effect;
  reproduces the +$27,013 control.

## Fixed-807 basis — pure entry-timing on the confirmed pocket

| Threshold | Trades | Net $ | $/tr | PF | Max DD | Opp-flip | Timeout | Pre-stop |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| **0.688350 (control)** | 807 | **27,013** | 33.47 | 1.174 | 14,331 | 372 | 144 | 255 |
| 0.675 | 806 | 26,031 | 32.30 | 1.168 | 14,163 | 364 | 152 | 254 |
| 0.650 | 804 | 20,832 | 25.91 | 1.136 | 14,165 | 348 | 162 | 261 |
| 0.625 | 803 | 19,824 | 24.69 | 1.131 | 15,685 | 321 | 184 | 272 |

Earlier entry is **monotonically worse**: −$982 (0.675), −$6,181 (0.650),
−$7,189 (0.625). The mechanism is direct — starting the 300s confirmation clock
earlier makes it expire before the bearish alignment flip, converting
profitable opposing-flip winners into timeouts: opposing-flip exits fall
372 → 321 (46.1% → 40.0%) while timeouts rise 144 → 184. Both years agree:
2025 control +$20,304 is best; 2026 control +$6,709 is best.

## Candidate basis — including added trades (control = 872)

| Threshold | Trades | Net $ | $/tr | PF | Max DD | 2025 | 2026 |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 0.688350 (control) | 872 | 22,250 | 25.52 | 1.129 | 18,686 | 15,366 | 6,884 |
| 0.675 | 909 | 22,797 | 25.08 | 1.129 | 20,645 | 15,760 | 7,037 |
| 0.650 | 960 | 9,788 | 10.20 | 1.052 | 23,786 | 5,850 | 3,938 |
| 0.625 | 1,063 | 11,539 | 10.85 | 1.057 | 20,030 | 14,630 | −3,092 |

Note the candidate-basis control (+$22,250 on 872) is **below** the fixed-807
control (+$27,013 on 807): the 65 candidates the one-position rule drops are net
**negative** — the executed pocket was correctly excluding them. 0.675 edges the
candidate control on total (+$547) but only via +37 trades; per-trade is lower
(25.08 vs 25.52) and drawdown worse ($20,645 vs $18,686). 0.650/0.625 are far
worse.

## Entry-timing attribution (candidate basis vs control)

| Threshold | Bucket | Count | PnL $ | $/tr | Median entry Δ | Median px impr (ATR) | Pre-stop before ctrl entry |
|:--|:--|--:|--:|--:|--:|--:|--:|
| 0.675 | matched same time | 761 | 19,151 | 25.2 | 0s | 0 | — |
| 0.675 | matched earlier | 109 | 2,419 | 22.2 | −15s | 0.087 | 15 |
| 0.675 | added trades | 38 | 797 | 21.0 | — | — | — |
| 0.650 | matched earlier | 278 | 3,499 | 12.6 | −15s | 0.097 | 35 |
| 0.650 | added trades | 91 | −5,891 | −64.7 | — | — | — |
| 0.625 | matched earlier | 551 | −5,636 | −10.2 | −25s | 0.140 | 94 |
| 0.625 | added trades | 195 | 2,134 | 10.9 | — | — | — |

Two things kill the thesis:

1. **The entry-price "improvement" is negligible** — median 0.09–0.14 ATR even
   at 0.625. Earlier entries do not enter meaningfully higher.
2. **Earlier entries perform worse, not better.** The matched-earlier cohort
   earns *less* per trade than matched-same at every threshold, and turns
   negative at 0.625 (−$10.2/tr). At 0.625, **94** earlier entries hit their
   pre-alignment stop *before the control would even have entered* — textbook
   false starts. Added trades are inconsistent (0.650 adds 91 at −$64.7/tr).

## Answers to the required questions

1. **Any lower threshold beats 0.688350?** On the confirmed pocket, **no** — all
   lower thresholds are worse (monotonically). On the candidate basis 0.675 is
   +$547 higher in total only.
2. **Better entry price or more trades?** More trades. The fixed-807 (same
   regimes) shows earlier entry *hurts*; the 0.675 candidate blip is pure added
   volume, and the entry-price gain is ~0.09 ATR (negligible).
3. **Extra pre-alignment stop-outs?** Fixed-807 pre-stops 255 → 254 → 261 → 272;
   timeouts rise more (144 → 184). At 0.625, 94 earlier entries stop out before
   the control entry.
4. **Opposing-flip cohort more profitable?** No — it **shrinks** (372 → 321
   trades, 46.1% → 40.0%); its PnL is flat-to-lower ($137.2K → $133.7K).
5. **Timeout cohort?** **Increases** with earlier entry (144 → 184) — the core
   failure mechanism.
6. **Stable both years?** Yes — control is best in both 2025 and 2026 on the
   fixed-807 basis; earlier entry hurts both years.
7. **Drawdown?** Roughly flat to worse (fixed-807 0.625 = $15,685 vs control
   $14,331; candidate basis clearly worse, up to $23,786).
8. **Any threshold clearly beats control before costs/fill?** No.
9. **Justify an NT Phase 1 replay for a new threshold?** No — nothing to
   promote.

## Recommendation

Keep the current **0.688350** threshold. Entry timing is not the constraint:
crossing earlier does not improve entry price and it forfeits opposing-flip
winners to the confirmation timeout. Per the study's Q7, the productive next
branch is **short-RTH-only W4 retraining on earlier years**, not an earlier
threshold on the existing model.

## Audit / provenance

Pre-execution lookahead audit: PASS on causality, 0 CRITICAL
(`audit/pre_execution_audit.md`). The generation reuses the audited established-
filter + crossing helpers with only the threshold parametrized; both control
gates (candidate 650/222 vs the audited multi-candidate seq-1 population;
fixed-807 604/203 reproducing the frozen Policy A +$27,013) reconcile exactly.
W4 was not retrained or recalibrated. The Parquet/JSON deliverables are
authoritative.
