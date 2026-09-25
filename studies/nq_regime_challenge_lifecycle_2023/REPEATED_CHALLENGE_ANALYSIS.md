# Repeated-challenge / deterioration analysis

Sources: `artifacts/BY_CHALLENGE_NUMBER_K0p5.csv`, `TOPOLOGY_K0p5.csv`, `SEQUENCE_PATTERNS.csv`, `ATLAS_SPREADS.csv`
(scopes `onset_k*`, `sequence_n>=3`), `HINDSIGHT_LAST_VS_EARLIER.csv`. "Residual" = beyond the location baseline.

## 1. Challenge number: survivorship, no information

0.5A challenges:

| n | N | P(new extreme) | residual | hold | remaining MFE | P(deepen) | MFE at onset | dist_flip |
|---|---|---|---|---|---|---|---|---|
| 1 | 6,024 | 74.6% | +0.9pp | −0.00 | 2.16 | 49.2% | 0.48 | 1.38 |
| 2 | 4,493 | 76.1% | +0.4pp | +0.02 | 2.27 | 49.1% | 1.00 | 1.60 |
| 3 | 3,420 | 76.8% | −0.5pp | +0.04 | 2.35 | 49.6% | 1.52 | 1.79 |
| 4 | 2,625 | 79.0% | +0.5pp | +0.08 | 2.45 | 49.1% | 2.03 | 1.95 |
| 6 | 1,626 | 81.0% | +1.2pp | +0.11 | 2.57 | 47.2% | 3.08 | 2.20 |
| 8+ | 6,057 | 82.7% | −0.3pp | +0.09 | 3.21 | 47.0% | 6.98 | 3.15 |

Later challenges succeed more often only because surviving regimes sit further from their flip threshold. The
residual is within ±1.2pp at every n, and the probability of deepening stays at 47–50%.

## 2. Topology: the next challenge does not remember the last one

P(next category | this category), 0.5A:

| this → next | fast rej. | slow rej. | deepen → recover | partial → flip | direct flip | END |
|---|---|---|---|---|---|---|
| A fast rejection | 34.1% | 17.2% | 28.5% | 9.5% | 10.7% | 0 |
| B slow rejection | 32.4% | 17.7% | 27.3% | 10.4% | 12.1% | 0.1% |
| E deepen → recover | 35.3% | 16.5% | 27.7% | 9.2% | 11.2% | 0.1% |

(C and F end the regime by construction.) Rows are identical within about 3pp. A hard-fought rejection says nothing
about how the next challenge will go.

## 3. Deterioration sequences (n ≥ 3, 0.5A)

Four prospective deterioration markers compare the current challenge with the previous ones:
- progress declining: the last recovery leg is smaller than the one before;
- depth increasing: the previous challenge was deeper than the one before it;
- impulse weakening: impulse efficiency fell;
- recovery slowing: the previous recovery took longer.

DETERIORATING = ≥ 3 of 4; STRENGTHENING = ≤ 1.

| block | pattern | n | P(new extreme) | residual | hold | hold residual | remaining MFE | +1A beyond the extreme |
|---|---|---|---|---|---|---|---|---|
| A | DETERIORATING | 5,088 | 79.3% | −0.3pp | +0.08 | +0.05 | 2.71 | 53.8% |
| A | STRENGTHENING | 5,297 | 80.6% | −0.2pp | +0.10 | +0.06 | 2.84 | 54.3% |
| B | DETERIORATING | 1,692 | 80.6% | +1.2pp | +0.14 | +0.11 | 2.57 | 52.0% |
| B | STRENGTHENING | 1,786 | 80.5% | +0.1pp | +0.24 | +0.21 | 2.77 | 55.9% |

The individual markers are just as flat. Top-minus-bottom residual P(new extreme) is within ±2pp for all four
markers, their count, the previous depth and the previous recovery time. The only exception is `prog_last_A` at
deeper challenges (−3.4 / −2.8pp at 1.0A, −5.6 / −5.8pp at 1.5A): a *large* previous recovery leg lowers the odds a
little, which reads as extension rather than deterioration. Hold residuals have no consistent sign.

**In hindsight the last challenge does look different** (regimes with ≥ 3 challenges, medians, last vs earlier):

| | impulse efficiency | challenge velocity | dist_flip | previous recovery leg |
|---|---|---|---|---|
| earlier | 0.449 | 3.75 A/min | 1.81A | 0.365A |
| last | 0.362 | 3.00 A/min | 1.63A | 0.315A |

The fatal challenge follows a slightly weaker, choppier impulse and is slower. The same differences, used
prospectively, are the 5–10pp race effects in CHALLENGE_RESPONSE_ATLAS.md §4. They are too small, and carry no value.

## 4. "We already tried and failed here", inside the regime

Top-minus-bottom residual; each cell is A / B:

| feature | race 0.5A | race 1.0A | race 1.5A | hold 1.0A |
|---|---|---|---|---|
| `n_prior_deeps_near_touch_0p5` (same support re-tested) | −1.2 / +0.8pp | −0.3 / +0.3pp | n/a | −0.04 / +0.04 |
| `n_marginal_ext` (earlier legs that barely made a new extreme) | −0.1 / −1.3pp | −0.4 / −6.9pp | n/a | −0.40 / −0.18 |
| `touch_vs_prev_deep_A` (higher vs lower low) | +1.1 / −0.2pp | −1.5 / −2.5pp | −1.9 / −2.8pp | +0.04 / −0.07 |
| `stalled_at_prior_regime_ext` (extreme = previous same-direction regime's extreme) | +0.2 / −0.3pp | −1.4 / −0.6pp | −3.6 / +3.8pp | −0.04 / +0.07 |
| `ext_vs_prev_same_regime_A` | −2.0 / −0.6pp | −1.9 / −2.8pp | −2.1 / +1.3pp | −0.15 / −0.04 |
| `n_turns_0p5` (prior-regime turning points near the touch) | +1.0 / +6.3pp | +2.7 / +2.4pp | +1.3 / +2.0pp | +0.10 / −0.15 |

Repeated tests of the same level, inside the regime or against prior regimes' turning points, add at most a few
percentage points with inconsistent signs. The one hint is `n_marginal_ext` at 1.0A: after earlier legs that barely
made new extremes, the hold value is −0.40 / −0.18A. It fails the B ≥ ½A rule. Level memory is **not** more
informative inside the regime than it was across completed regimes (`nq_regime_sequence_tradability_2023`).

## 5. Changing MTF context

The 15m regime flipping during the current 1m regime (`15m_flips_since_start` ≥ 1, 5.6% of 0.5A and 5.9% of 1.0A challenges):
- race −1.7 / −3.7pp;
- hold −0.42 / −0.57A (0.5A) and −0.53 / −0.48A (1.0A).

Static `5m_aligned` / `15m_aligned` have no race effect and inconsistent hold effects. So *changing* HTF context
carries more than static labels do, but vetting shows the hold effect is long-dominated (A long −1.05, A short +0.19)
and unstable at one episode per regime. It is a lead, not a finding.
