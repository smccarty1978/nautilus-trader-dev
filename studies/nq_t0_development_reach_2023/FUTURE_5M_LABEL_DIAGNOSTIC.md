# FUTURE_5M_ALIGNMENT — label audit and diagnostic

**Definition.** The label is 1 if a 5m regime with direction equal to the trade's 1m direction **started**
strictly after the T0 observation and strictly before the terminal opposite 1m flip.

- **Future label only.** It is never in any feature matrix (a leak guard checks every arm), and no model was
  trained on it.
- **How it is built.** `start_ns_5m` is the 5m flip-detection bar close; it always lies on a 5-minute
  boundary, and `prior_frozen_at == start`. Every observation carries the current 5m regime and its
  predecessor, and consecutive regimes always alternate direction.
  - **Implementation 1:** find the first observation at or after the terminal flip in the same session. Walk
    the 5m regime links from that observation back to the T0 regime. A missing link gives NULL; nothing is
    guessed.
  - **Implementation 2:** an interval query over the union of every known 5m regime start.

## Audit (all 7,475 audited trades; counts only, never split by block)

| | |
|---|---|
| exact | 7,248 |
| NULL — no in-session observation after the terminal flip (flip after the last RTH row) | 223 |
| NULL — broken chain | 4 |
| regime-map conflicts | 0 |
| implementation 1 vs 2 mismatches on exact rows | **0** |
| prevalence on exact rows | 18.1% |

## Diagnostic — development rows only (first 80% of sessions; 5,842 exact rows of 6,024)

| | N | 5m-alignment rate |
|---|---|---|
| all | 5,842 | 17.9% |
| 5m already aligned at T0 | 2,392 | **0.0%** (would need two 5m flips inside the trade; none occurred) |
| 5m misaligned at T0 | 3,450 | **30.4%** |

**Relationship with the reach labels and Target A:**

| | F5 = 0 | F5 = 1 | F5 = 0, misaligned at T0 only |
|---|---|---|---|
| +2A reach | 25.4% | **87.5%** | 14.0% |
| +3A reach | 14.0% | 68.0% | 3.8% |
| terminal win (Target A) | 21.0% | **83.1%** | 9.8% |

Phi correlations: F5 with +2A = 0.50; F5 with win = 0.51; F5 with −1A = −0.29.

**By initial exact MTF state (development rows):**

| state | N | aligned at T0 | F5 % | +2A % | +3A % | win % |
|---|---|---|---|---|---|---|
| L/L/L/L | 746 | 100 | 0.0 | 40.2 | 27.1 | 36.3 |
| L/L/L/S | 271 | 100 | 0.0 | 32.1 | 23.2 | 28.4 |
| L/L/S/L | 106 | 100 | 0.0 | 36.8 | 27.4 | 37.7 |
| L/L/S/S | 250 | 100 | 0.0 | 36.0 | 18.8 | 30.4 |
| L/S/L/L | 322 | 0 | 35.4 | 32.9 | 22.0 | 32.0 |
| L/S/L/S | 125 | 0 | 39.2 | 44.0 | 29.6 | 39.2 |
| L/S/S/L | 341 | 0 | 31.7 | 37.0 | 24.0 | 34.3 |
| L/S/S/S | 761 | 0 | 32.6 | 38.1 | 24.7 | 36.9 |
| S/L/L/L | 971 | 0 | 24.6 | 34.4 | 22.0 | 27.3 |
| S/L/L/S | 412 | 0 | 29.4 | 37.9 | 24.8 | 31.3 |
| S/L/S/L | 147 | 0 | 29.3 | 39.5 | 23.8 | 31.3 |
| S/L/S/S | 371 | 0 | 34.0 | 34.2 | 20.5 | 31.3 |
| S/S/L/L | 206 | 100 | 0.0 | 40.3 | 26.2 | 30.6 |
| S/S/L/S | 76 | 100 | 0.0 | 32.9 | 21.1 | 31.6 |
| S/S/S/L | 224 | 100 | 0.0 | 32.6 | 23.2 | 29.0 |
| S/S/S/S | 513 | 100 | 0.0 | 35.9 | 22.8 | 30.4 |

## Reading

Among trades whose 5m was against them at T0, 30% saw the 5m turn their way before the 1m flipped back.
Those trades almost always reached +2A and won: 87.5% and 83.1%, against 14.0% and 9.8% for misaligned
trades whose 5m never turned.

The 5m transition is therefore very close to **the same event** as a successful trade. A move large enough to
flip the 5m regime is, in most cases, the +2A move itself. This table does **not** show which comes first:
the frame does not carry the 5m flip time relative to the +2A touch. It must not be read as "5m alignment
causes development".

A 5m-transition model was **not** trained; the brief did not authorise one. Given how closely F5 tracks +2A,
and that T0 does not rank +2A (`DEVELOPMENT_MODEL_RESULTS.md`), there is no reason from this study to expect
T0 to rank F5 either. That is an inference, not a test.

Machine-readable: `artifacts/FUTURE_5M_LABEL_AUDIT.json`, `FUTURE_5M_DIAGNOSTIC.json`,
`FUTURE_5M_BY_STATE.{csv,parquet}`, `TARGET_OVERLAP.{csv,parquet}`.
