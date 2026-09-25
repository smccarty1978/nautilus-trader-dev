# Development replication (block A = 154 sessions, block B = 51 sessions)

Every bin edge comes from block A and is applied unchanged to block B. The final 20% of 2023 was never loaded.
Sources: `artifacts/MATERIALITY.csv`, `NULL_SHIFT_ONSET.json`, `CANDIDATE_VETTING.csv`, `ATLAS_SPREADS.csv`.

**Materiality rule** (pre-declared in `atlas.py`): |top − bottom residual| ≥ 5pp on P(new extreme) or ≥ 0.15A on hold
value, the same sign in A and B, and |B| ≥ ½|A|.

## 1. Is there more replicated structure than chance?

Null = the location-residual outcome vector rotated in time by a random offset within each block. This keeps both
autocorrelations and breaks the alignment; 20 rotations (`null_shift.py`).

| scope | outcome | features | real material | null mean (p95) | real A/B same sign | null same sign |
|---|---|---|---|---|---|---|
| onset 0.5A | race P(new extreme) | 82 | **4** | 0.0 (0) | **69.5%** | 50.4% |
| onset 0.5A | hold value | 82 | 14 | 3.6 (9.1) | 52.4% | 48.5% |
| onset 1.5A | race P(new extreme) | 82 | **5** | 0.45 (2) | **65.5%** | 48.3% |
| onset 1.5A | hold value | 82 | 13 | 4.45 (8.5) | 56.3% | 47.8% |

- **Race:** clearly above the null in count and in sign agreement.
- **Hold:** above the null in count only. Sign agreement is at chance, which means a few large features are doing
  the work, and §2 shows those are drift.
- Response checkpoints were not null-calibrated. Their A/B sign agreement is 52–58% (256–271 feature × checkpoint
  rows per depth), close to chance.

## 2. Robustness vetting of every candidate (`vet.py`)

Top-minus-bottom residual. "Consistent" counts how many of 10 splits share the sign of block A:
- A, B;
- A trimmed, B trimmed (1st/99th percentile);
- A long, A short, B long, B short;
- A and B with one episode per regime.

| k | feature | outcome | A | B | A long / A short | B long / B short | one per regime A / B | consistent | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 | `ch_dur_s` | race | −6.4pp | −6.7pp | −5.9 / −7.4 | −8.3 / −4.6 | −8.9 / −2.4 | 10/10 | **replicated** |
| 0.5 | `ret15_A` | race | +5.5pp | +5.5pp | +4.4 / +7.2 | +7.0 / +4.0 | +8.6 / +13.6 | 10/10 | **replicated** |
| 1.0 | `ch_wick_frac` | race | +5.1pp | +5.8pp | +3.7 / +6.4 | +9.7 / +2.1 | +6.4 / +5.1 | 10/10 | **replicated** |
| 1.5 | `since_prev_onset_s` | race | −7.7pp | −7.7pp | −12.9 / −3.6 | −18.9 / +4.3 | −11.0 / −10.0 | 9/10 | replicated |
| 1.5 | `prog_last_A` | race | −5.6pp | −5.8pp | −8.4 / −2.8 | −10.1 / −1.7 | −8.5 / −4.5 | 10/10 | **replicated** |
| 1.5 | `opening_drive` | race | +7.7pp | +4.2pp | +9.8 / +4.8 | +5.7 / +1.8 | +8.2 / +4.5 | 10/10 | **replicated** |
| 2.0 | `imp_bars` | race | −9.7pp | −9.5pp | −12.1 / −5.3 | −8.5 / −10.5 | −3.0 / −13.8 | 10/10 | **replicated** |
| 0.5 | `atr_pts` | hold | −0.57 | −0.92 | −1.03 / +0.01 | −1.15 / −0.72 | −0.01 / −0.64 | 9/10 | drift: long-only in A, gone at one per regime in A |
| 1.0 | `atr_pts` | hold | −0.46 | −0.58 | −0.82 / −0.06 | −0.85 / −0.34 | −0.04 / −0.66 | 10/10 | same caveat; lowest-ATR quintile, April–May |
| 0.5 | `1h_aligned` | hold | +0.28 | +0.41 | +0.59 / −0.13 | +0.43 / +0.39 | +0.12 / +0.15 | 9/10 | known regime-level 1h residual; A shorts reverse |
| 0.5 | `15m_flips_since_start` | hold | −0.42 | −0.57 | −1.05 / +0.19 | −0.21 / −0.99 | −1.27 / +2.41 | 8/10 | unstable |
| 0.5 | `opening_drive` | hold | +0.39 | +0.35 | +0.95 / −0.32 | +0.83 / −0.56 | +0.10 / −0.01 | 7/10 | drift (long + / short −) |
| 2.0 | `imp_bars` | hold | +0.86 | +0.69 | +0.63 / +1.22 | +0.48 / +0.92 | +0.84 / +0.38 | 10/10 | one degenerate bin (`imp_bars = 0`, n = 135 + 31); no trend across bins 1–4 |
| 2.0 | `prev_rec_time_s` / `since_prev_onset_s` | hold | +0.87 / +0.85 | +1.65 / +1.13 | | | | 10/10 | top bins n = 27–48 in B, too small |

## 3. Summary

| relationship | block A | block B | pooled | n | status |
|---|---|---|---|---|---|
| slow 0.5A challenge → fewer new extremes (beyond location) | −6.4pp | −6.7pp | −6.4pp [−7.7, −4.8] | 5,500 per quintile | replicated, value-neutral |
| fast / heavy 0.5A challenge → more new extremes | +4.9pp | +6.6pp | +5.3pp [+3.9, +6.7] | ≈ 5,500 per quintile | replicated, value-neutral |
| long impulse before a 2.0A challenge → fewer new extremes | −9.7pp | −9.5pp | | 790 / 272 top bin | replicated, value-neutral |
| at the first close through EMA3-low: deeper price (0.5A) / more new lows (1.0A) → fewer new extremes | −13.5pp / −10.7pp | −9.6pp / −10.2pp | | 2,896 / 2,761 events | replicated at the event, value-neutral |
| any challenge-internal feature → hold value | none survives vetting | | | | **not replicated** |
