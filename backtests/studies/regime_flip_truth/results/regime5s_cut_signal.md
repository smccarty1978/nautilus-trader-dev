# 5s/30s Regime in the First 90s — Quicker Cut Signal?

NQ `NQ.v.0` 2021-2024, warmed. A n=110,507, B n=47,068. 1s-causal 5s/30s regime path.


## Q1 — Do eventual winners flip 5s-OPPOSED in the first 90s?

Share of each cohort whose 5s regime turns opposed to the trade by +T, median time of first 5s-opposed, and median 5s churn (flips) in 90s.

### Population A
| cohort | n | 5s-opp ≤30s | ≤60s | ≤90s | med t_first_5s | med 5s-flips/90s |
| --- | --- | --- | --- | --- | --- | --- |
| winners (+2ATR) | 42,338 | 23.8% | 48.5% | 68.1% | 61s | 1 |
| non-reachers | 68,169 | 35.9% | 67.9% | 86.5% | 41s | 1 |
| cut-set (net<0 @60s) | 54,708 | 46.0% | 86.3% | 96.3% | 31s | 2 |
| Elite | 16,968 | 15.7% | 36.8% | 58.3% | 76s | 1 |
| Fakeout | 45,127 | 42.0% | 76.4% | 92.7% | 36s | 1 |

30s regime (Population A), opposed by +60s / +90s:
- winners (+2ATR): ≤60s 1.2%, ≤90s 2.4%, med 541s
- non-reachers: ≤60s 2.9%, ≤90s 6.6%, med 212s
- cut-set (net<0 @60s): ≤60s 3.2%, ≤90s 8.7%, med 216s
- Elite: ≤60s 0.6%, ≤90s 0.6%, med 692s
- Fakeout: ≤60s 3.8%, ≤90s 8.6%, med 158s

### Population B
| cohort | n | 5s-opp ≤30s | ≤60s | ≤90s | med t_first_5s | med 5s-flips/90s |
| --- | --- | --- | --- | --- | --- | --- |
| winners (+2ATR) | 18,876 | 38.7% | 60.0% | 75.6% | 42s | 1 |
| non-reachers | 28,192 | 51.4% | 77.0% | 90.8% | 27s | 1 |
| cut-set (net<0 @60s) | 23,645 | 60.7% | 91.5% | 97.8% | 22s | 2 |
| Elite | 7,518 | 30.5% | 49.5% | 67.2% | 61s | 1 |
| Fakeout | 18,419 | 57.3% | 84.1% | 95.5% | 25s | 1 |

30s regime (Population B), opposed by +60s / +90s:
- winners (+2ATR): ≤60s 0.7%, ≤90s 1.8%, med 541s
- non-reachers: ≤60s 2.2%, ≤90s 5.8%, med 217s
- cut-set (net<0 @60s): ≤60s 2.5%, ≤90s 7.7%, med 242s
- Elite: ≤60s 0.2%, ≤90s 0.2%, med 721s
- Fakeout: ≤60s 3.0%, ≤90s 7.8%, med 181s


## Q2 — 5s-opposed as a stand-alone CUT signal

Rule: cut the trade the first time the 5s regime is opposed, if that happens by +T. A good cut has LOW P(reach2|trig), HIGH P(reach2|keep), and kills few winners.

### Population A
| cut@T | trig% | P(reach2\|trig) | P(reach2\|keep) | winners killed% | E[term\|trig] | E[term\|keep] |
| --- | --- | --- | --- | --- | --- | --- |
| ≤15s | 12.1% | 29.3% | 39.6% | 9.3% | -0.51 | +0.02 |
| ≤30s | 31.3% | 29.1% | 42.5% | 23.8% | -0.47 | +0.14 |
| ≤45s | 47.6% | 29.8% | 46.0% | 37.1% | -0.42 | +0.29 |
| ≤60s | 60.5% | 30.7% | 49.9% | 48.5% | -0.37 | +0.45 |
| ≤90s | 79.4% | 32.8% | 59.5% | 68.1% | -0.28 | +0.85 |

### Population B
| cut@T | trig% | P(reach2\|trig) | P(reach2\|keep) | winners killed% | E[term\|trig] | E[term\|keep] |
| --- | --- | --- | --- | --- | --- | --- |
| ≤15s | 27.1% | 34.6% | 42.1% | 23.4% | -0.24 | +0.05 |
| ≤30s | 46.3% | 33.5% | 45.8% | 38.7% | -0.31 | +0.22 |
| ≤45s | 60.2% | 33.8% | 49.6% | 50.8% | -0.30 | +0.38 |
| ≤60s | 70.2% | 34.3% | 53.8% | 60.0% | -0.27 | +0.54 |
| ≤90s | 84.7% | 35.8% | 64.0% | 75.6% | -0.21 | +0.99 |


## Q3 — Does 5s ADD to the +60s net-PnL gate? (orthogonality)

At +60s, cross net-PnL sign with 5s alignment. If 5s-opposed sharpens the cut WITHIN a PnL bucket, it adds information; if reach2 is flat across 5s within each PnL bucket, it is redundant with PnL.

### Population A (n=109,541)
| @+60s state | n | P(reach2) | E[term] |
| --- | --- | --- | --- |
| net≥0 & 5s aligned | 47,078 | 52.3% | +0.56 |
| net≥0 & 5s opposed | 7,755 | 42.4% | +0.23 |
| net<0 & 5s aligned | 15,491 | 30.7% | -0.36 |
| net<0 & 5s opposed | 39,217 | 24.7% | -0.66 |

### Population B (n=46,792)
| @+60s state | n | P(reach2) | E[term] |
| --- | --- | --- | --- |
| net≥0 & 5s aligned | 19,368 | 54.5% | +0.60 |
| net≥0 & 5s opposed | 3,779 | 45.1% | +0.29 |
| net<0 & 5s aligned | 5,692 | 32.0% | -0.38 |
| net<0 & 5s opposed | 17,953 | 26.7% | -0.64 |


## Q4 — Quicker? 5s at +30s vs the +60s gate

Can a +30s read (30s earlier) act as the cut? Cross +30s net-PnL sign with +30s 5s alignment.

### Population A @+30s (n=110,499)
| @+30s state | n | P(reach2) | E[term] | winners-killed share |
| --- | --- | --- | --- | --- |
| net≥0 & 5s aligned | 52,340 | 48.0% | +0.38 | 59.3% |
| net≥0 & 5s opposed | 2,786 | 39.1% | +0.10 | 2.6% |
| net<0 & 5s aligned | 25,958 | 32.2% | -0.31 | 19.8% |
| net<0 & 5s opposed | 29,415 | 26.4% | -0.59 | 18.3% |

### Population B @+30s (n=47,068)
| @+30s state | n | P(reach2) | E[term] | winners-killed share |
| --- | --- | --- | --- | --- |
| net≥0 & 5s aligned | 20,814 | 50.5% | +0.43 | 55.6% |
| net≥0 & 5s opposed | 2,287 | 41.9% | +0.10 | 5.1% |
| net<0 & 5s aligned | 8,336 | 35.1% | -0.22 | 15.5% |
| net<0 & 5s opposed | 15,631 | 28.7% | -0.56 | 23.8% |


## Q5 — 5s CHURN (chop) in first 90s

Number of 5s regime flips in the first 90s vs outcomes. High churn = chop.

### Population A
| 5s flips /90s | n | P(reach2) | fakeout% | elite% | E[term] |
| --- | --- | --- | --- | --- | --- |
| 0 | 22,855 | 59.3% | 14.9% | 31.0% | +0.84 |
| 1 | 38,944 | 27.5% | 54.4% | 8.6% | -0.56 |
| 2 | 28,317 | 42.7% | 34.5% | 16.7% | +0.18 |
| 3 | 14,281 | 26.6% | 56.9% | 7.3% | -0.49 |
| 4 | 4,625 | 38.4% | 39.9% | 14.1% | +0.03 |
| 5+ | 1,485 | 28.2% | 55.2% | 7.7% | -0.57 |

### Population B
| 5s flips /90s | n | P(reach2) | fakeout% | elite% | E[term] |
| --- | --- | --- | --- | --- | --- |
| 0 | 7,939 | 59.5% | 17.4% | 31.2% | +0.79 |
| 1 | 16,030 | 31.5% | 49.3% | 10.6% | -0.45 |
| 2 | 12,960 | 44.2% | 33.1% | 17.4% | +0.19 |
| 3 | 7,033 | 31.6% | 50.5% | 9.6% | -0.36 |
| 4 | 2,320 | 39.3% | 38.8% | 14.3% | -0.07 |
| 5+ | 786 | 31.4% | 49.5% | 11.5% | -0.32 |


# ANSWERS — is 5s a quicker / additional cut signal?

## How many eventual winners flip 5s-negative in the first 90s?
A lot — but fewer and later than the trades we want to cut (Population A):
- **Winners (+2ATR): 68% flip 5s-opposed by 90s** (24% by 30s, 49% by 60s; median first-opposed 61s).
- **Elite: only 58%** (median 76s) — the best trades waver least.
- **Non-reachers: 87%** (median 41s); **cut-set (net<0@60s): 96%** (median 31s); **Fakeout: 93%**.
So winners and cut-trades OVERLAP heavily on 5s-opposition — 5s is noisy. The
30s regime is the opposite problem: <3% of ANY cohort flips 30s-opposed within
90s (median ~540s for winners) — far too slow to be an early cut.

## Is 5s-opposed a good STAND-ALONE cut? No.
Cutting on first 5s-opposition by +60s kills **48% of winners** (A) yet the cut
trades still reach +2 ATR 31% of the time (vs 50% kept). P(reach2|cut) is stuck
at ~29-33% for ANY cut time — weak separation, heavy winner loss. 5s is too
twitchy to cut on by itself.

## Does 5s ADD to the +60s net-PnL gate? Yes — modestly.
Within each net-PnL bucket at +60s, 5s alignment adds ~6-10pp (Population A):
| @+60s | n | P(reach+2) | E[term] |
|---|---|---|---|
| net≥0 & 5s aligned | 47,078 | 52.3% | +0.56 |
| net≥0 & 5s opposed | 7,755 | 42.4% | +0.23 |
| net<0 & 5s aligned | 15,491 | 30.7% | −0.36 |
| net<0 & 5s opposed | 39,217 | **24.7%** | **−0.66** |
net PnL is the dominant axis (52% vs 25%); 5s is a refinement. The cleanest cut
cohort is **net<0 AND 5s-opposed** (25% reach2, −0.66) — but most of that is
already caught by the PnL sign alone.

## Is there a QUICKER cut? Yes — but it is net PnL at +30s, not 5s.
At +30s the net-PnL sign already separates 48% (≥0) vs ~28-32% (<0) — a usable
gate 30s earlier than the +60s version. The cohort **net<0 & 5s-opposed @+30s**
(27% of A) reaches +2 only 26% (E −0.59) and kills just 18% of winners — a
cleaner early cut than 5s-alone. But the lift over plain +30s net-PnL is small.

## The single most useful new signal: ZERO 5s-flips (parity effect).
5s churn is NON-monotonic — odd flip-counts end 5s-opposed (bad), even end
aligned (good). The standout is **0 flips** (5s never wavered in 90s):
- 0 flips: **59% reach+2, E +0.84, 31% Elite** — by far the cleanest HOLD.
- 1 flip: 28% / −0.56 / 9%. 2 flips: 43% / +0.18. (then alternates.)
A trade whose 5s regime never turns opposed for the full 90s is a genuinely
strong trend — but you only confirm it at +90s.

## Verdict
- 5s-opposition is **not a clean quicker cut** — winners flip it 68% of the
  time; cutting on it loses ~half your winners.
- 5s is a **mild ADDITIONAL refinement** on the net-PnL gate (~6-10pp within
  bucket); 'net<0 & 5s-opposed' is the sharpest cut cohort.
- The genuinely **quicker** lever is the net-PnL sign at **+30s** (acts 30s
  sooner), not the 5s regime.
- **0 5s-flips in 90s** is the cleanest HOLD signal found (59%/+0.84/31% Elite),
  but it is a +90s confirmation, not an early cut.
Same caveats: whole-trade conditioned outcomes, partly mechanical, no costs —
needs a 1s/tick costed bracket sim before any deployment claim.
