# Drawdown Timing & Adaptive Exit Feasibility Study

NQ `NQ.v.0` 2021-2024, 24h, warmed events. A (raw flip) n=110,507, B (bar1-confirmed) n=47,068. Catalog `NQ_v0_2020_2026`. 1s-precise excursion timing (collector-recorded).

**Definitions:** +2ATR reacher = reached_2_0_atr; Elite = persistent≥15bars & MFE≥2 & MAE≤0.75; Fakeout = never reached +1.0 ATR MFE; '-X before +2' = adverse threshold crossed before the +2 MFE touch (1s).


# STUDY 1 — Drawdown Timing

Median time (s from entry) to each excursion threshold, by cohort. NaN = threshold never reached (excluded from median); reach-rate shown in parentheses.

### Population A
| cohort | n | 0.5ATR MAE | 1.0ATR MAE | max MAE | 0.5ATR MFE | 1.0ATR MFE | 2.0ATR MFE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 110,507 | 54s (81%) | 132s (59%) | 184s (100%) | 51s (75%) | 136s (59%) | 326s (38%) |
| +2ATR reach | 42,338 | 51s (58%) | 128s (28%) | 73s (100%) | 49s (100%) | 131s (100%) | 326s (100%) |
| non-reach | 68,169 | 56s (95%) | 133s (78%) | 239s (100%) | 53s (60%) | 145s (34%) | — |
| Elite | 16,968 | 57s (29%) | — | 23s (100%) | 35s (100%) | 103s (100%) | 307s (100%) |
| Fakeout | 45,127 | 43s (99%) | 116s (90%) | 227s (100%) | 54s (39%) | — | — |

**Adverse-before-favorable ordering (Population A, all events):**
- 0.5 MAE before 0.5 MFE: 51.4%
- 1.0 MAE before 1.0 MFE: 47.6%

### Population B
| cohort | n | 0.5ATR MAE | 1.0ATR MAE | max MAE | 0.5ATR MFE | 1.0ATR MFE | 2.0ATR MFE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 47,068 | 51s (82%) | 132s (61%) | 213s (100%) | 54s (76%) | 141s (61%) | 341s (40%) |
| +2ATR reach | 18,876 | 49s (61%) | 129s (31%) | 82s (100%) | 51s (100%) | 134s (100%) | 341s (100%) |
| non-reach | 28,192 | 51s (96%) | 133s (82%) | 282s (100%) | 57s (61%) | 157s (35%) | — |
| Elite | 7,518 | 61s (30%) | — | 24s (100%) | 36s (100%) | 101s (100%) | 309s (100%) |
| Fakeout | 18,419 | 40s (99%) | 114s (93%) | 240s (100%) | 58s (40%) | — | — |

**Adverse-before-favorable ordering (Population B, all events):**
- 0.5 MAE before 0.5 MFE: 52.3%
- 1.0 MAE before 1.0 MFE: 49.1%


# STUDY 2 — Drawdown Location (where does the heat sit for +2ATR reachers)

For events that reach +2 ATR: WHEN does the worst pre-+2 adverse excursion (`t_max_mae_before_2atr_s`) occur relative to the +0.5 / +1.0 ATR MFE milestones, and how big is that DD (`mae_before_2_0_atr`)?

### Population A  (n reachers = 42,338)
| DD location | share | median DD (ATR) | p90 DD (ATR) |
| --- | --- | --- | --- |
| before +0.5 ATR MFE | 70.8% | 0.43 | 1.32 |
| before +1.0 ATR MFE | 89.1% | 0.48 | 1.35 |
| after +1.0 ATR MFE | 10.9% | 0.66 | 1.52 |

Overall: median worst-pre-2ATR DD = 0.50 ATR, occurring at median 39s after entry (vs +2 ATR reached at median 326s).

### Population B  (n reachers = 18,876)
| DD location | share | median DD (ATR) | p90 DD (ATR) |
| --- | --- | --- | --- |
| before +0.5 ATR MFE | 69.8% | 0.47 | 1.39 |
| before +1.0 ATR MFE | 88.2% | 0.52 | 1.43 |
| after +1.0 ATR MFE | 11.8% | 0.68 | 1.55 |

Overall: median worst-pre-2ATR DD = 0.54 ATR, occurring at median 45s after entry (vs +2 ATR reached at median 341s).


# STUDY 3 — Extension-Bar Conditioning

Decile each entry/confirm-bar feature; report forward path outcomes. Shows whether bigger/stronger entry bars precede better follow-through or just bigger drawdown.

## Population A
### confirm_bar_range_ATR  (Population A)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.00..0.69 | 11,051 | 32.9% | 0.45 | 1.23 | 343s | 46.9% | 14.1% |
| 2 | 0.69..0.83 | 11,051 | 36.3% | 0.49 | 1.27 | 352s | 43.6% | 15.4% |
| 3 | 0.83..0.95 | 11,050 | 35.9% | 0.48 | 1.30 | 347s | 43.0% | 15.0% |
| 4 | 0.95..1.05 | 11,051 | 36.3% | 0.49 | 1.31 | 347s | 43.0% | 14.9% |
| 5 | 1.05..1.16 | 11,051 | 37.6% | 0.49 | 1.29 | 338s | 41.7% | 15.3% |
| 6 | 1.16..1.28 | 11,050 | 39.0% | 0.49 | 1.33 | 344s | 40.3% | 16.2% |
| 7 | 1.28..1.41 | 11,051 | 38.4% | 0.51 | 1.36 | 340s | 40.3% | 15.6% |
| 8 | 1.41..1.59 | 11,050 | 40.1% | 0.53 | 1.40 | 331s | 38.6% | 16.3% |
| 9 | 1.59..1.89 | 11,051 | 40.8% | 0.52 | 1.43 | 311s | 37.5% | 15.6% |
| 10 | 1.89..11.86 | 11,051 | 45.8% | 0.57 | 1.71 | 244s | 33.5% | 15.0% |
_D10−D1: reach2 +12.8%, p90_DD +0.48 ATR, elite +0.9%, fakeout -13.4%_

### confirm_bar_body_ATR  (Population A)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.00..0.39 | 11,051 | 34.9% | 0.46 | 1.23 | 339s | 45.0% | 14.8% |
| 2 | 0.39..0.54 | 11,051 | 35.6% | 0.48 | 1.27 | 336s | 43.8% | 14.8% |
| 3 | 0.54..0.65 | 11,050 | 36.2% | 0.50 | 1.29 | 357s | 43.2% | 15.0% |
| 4 | 0.65..0.75 | 11,051 | 37.3% | 0.47 | 1.31 | 335s | 41.9% | 15.5% |
| 5 | 0.75..0.86 | 11,051 | 36.9% | 0.49 | 1.30 | 344s | 42.0% | 15.5% |
| 6 | 0.86..0.97 | 11,050 | 37.3% | 0.50 | 1.36 | 342s | 41.8% | 15.4% |
| 7 | 0.97..1.10 | 11,051 | 39.3% | 0.50 | 1.34 | 326s | 40.1% | 15.6% |
| 8 | 1.10..1.26 | 11,050 | 39.4% | 0.51 | 1.40 | 324s | 39.0% | 16.1% |
| 9 | 1.26..1.53 | 11,051 | 41.0% | 0.53 | 1.46 | 320s | 37.9% | 16.0% |
| 10 | 1.53..9.11 | 11,051 | 45.2% | 0.58 | 1.68 | 258s | 33.7% | 14.8% |
_D10−D1: reach2 +10.3%, p90_DD +0.45 ATR, elite +0.0%, fakeout -11.3%_

### close_location_in_confirm_bar  (Population A)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.00..0.69 | 11,109 | 38.5% | 0.46 | 1.32 | 313s | 41.2% | 15.6% |
| 2 | 0.69..0.76 | 11,147 | 38.2% | 0.47 | 1.33 | 320s | 40.8% | 16.0% |
| 3 | 0.77..0.82 | 10,881 | 38.8% | 0.47 | 1.36 | 328s | 39.9% | 16.0% |
| 4 | 0.82..0.86 | 12,599 | 37.8% | 0.47 | 1.33 | 321s | 40.6% | 15.2% |
| 5 | 0.86..0.89 | 9,569 | 38.6% | 0.51 | 1.38 | 333s | 40.0% | 15.6% |
| 6 | 0.89..0.92 | 11,245 | 39.4% | 0.51 | 1.39 | 335s | 40.0% | 16.2% |
| 7 | 0.92..0.96 | 10,938 | 39.6% | 0.51 | 1.37 | 332s | 38.8% | 16.4% |
| 8 | 0.96..1.00 | 32,939 | 37.4% | 0.54 | 1.41 | 326s | 42.3% | 14.2% |
_D10−D1: reach2 -1.1%, p90_DD +0.09 ATR, elite -1.4%, fakeout +1.1%_

### extension_from_EMA13_ATR  (Population A)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -0.96..0.32 | 11,051 | 33.4% | 0.47 | 1.24 | 368s | 45.1% | 14.8% |
| 2 | 0.32..0.41 | 11,051 | 35.3% | 0.46 | 1.24 | 361s | 44.0% | 16.0% |
| 3 | 0.41..0.50 | 11,050 | 36.3% | 0.48 | 1.28 | 354s | 42.8% | 15.5% |
| 4 | 0.50..0.57 | 11,051 | 37.2% | 0.47 | 1.27 | 326s | 42.1% | 15.8% |
| 5 | 0.57..0.66 | 11,051 | 37.3% | 0.46 | 1.29 | 320s | 42.0% | 15.1% |
| 6 | 0.66..0.75 | 11,050 | 38.4% | 0.50 | 1.34 | 330s | 41.0% | 15.5% |
| 7 | 0.75..0.86 | 11,051 | 38.9% | 0.51 | 1.36 | 337s | 40.1% | 15.1% |
| 8 | 0.86..1.00 | 11,050 | 40.7% | 0.51 | 1.40 | 314s | 38.2% | 15.7% |
| 9 | 1.00..1.24 | 11,051 | 40.7% | 0.54 | 1.44 | 310s | 38.9% | 15.5% |
| 10 | 1.24..11.33 | 11,051 | 44.8% | 0.62 | 1.69 | 271s | 34.2% | 14.4% |
_D10−D1: reach2 +11.4%, p90_DD +0.46 ATR, elite -0.4%, fakeout -10.8%_

### extension_from_VWAP_ATR  (Population A)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -108.85..-8.81 | 11,051 | 37.2% | 0.51 | 1.39 | 355s | 41.8% | 14.9% |
| 2 | -8.81..-5.22 | 11,051 | 37.9% | 0.50 | 1.33 | 353s | 40.7% | 16.0% |
| 3 | -5.22..-3.00 | 11,050 | 37.9% | 0.49 | 1.33 | 327s | 40.9% | 15.7% |
| 4 | -3.00..-1.26 | 11,051 | 37.6% | 0.50 | 1.34 | 343s | 40.9% | 15.2% |
| 5 | -1.26..0.17 | 11,051 | 38.5% | 0.48 | 1.34 | 315s | 40.9% | 15.9% |
| 6 | 0.17..1.55 | 11,050 | 38.2% | 0.48 | 1.39 | 320s | 41.0% | 15.3% |
| 7 | 1.55..3.23 | 11,051 | 38.0% | 0.50 | 1.39 | 312s | 41.6% | 14.8% |
| 8 | 3.23..5.50 | 11,050 | 39.4% | 0.52 | 1.39 | 309s | 39.8% | 15.5% |
| 9 | 5.50..9.15 | 11,051 | 39.4% | 0.51 | 1.42 | 307s | 40.4% | 15.3% |
| 10 | 9.15..126.33 | 11,051 | 39.1% | 0.53 | 1.38 | 334s | 40.4% | 15.0% |
_D10−D1: reach2 +1.8%, p90_DD -0.01 ATR, elite +0.1%, fakeout -1.4%_

## Population B
### confirm_bar_range_ATR  (Population B)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.09..0.61 | 4,707 | 34.4% | 0.46 | 1.25 | 359s | 45.5% | 14.7% |
| 2 | 0.61..0.73 | 4,707 | 37.8% | 0.49 | 1.31 | 377s | 41.0% | 16.9% |
| 3 | 0.73..0.82 | 4,707 | 36.6% | 0.48 | 1.31 | 361s | 42.2% | 15.8% |
| 4 | 0.82..0.90 | 4,706 | 39.0% | 0.50 | 1.37 | 349s | 39.4% | 16.4% |
| 5 | 0.90..0.99 | 4,707 | 39.1% | 0.54 | 1.36 | 349s | 41.4% | 15.9% |
| 6 | 0.99..1.10 | 4,707 | 41.0% | 0.51 | 1.40 | 363s | 37.5% | 16.8% |
| 7 | 1.10..1.22 | 4,706 | 39.9% | 0.57 | 1.49 | 361s | 37.6% | 15.4% |
| 8 | 1.22..1.39 | 4,707 | 42.0% | 0.55 | 1.44 | 342s | 37.3% | 16.8% |
| 9 | 1.39..1.69 | 4,707 | 44.4% | 0.60 | 1.56 | 315s | 35.7% | 16.1% |
| 10 | 1.69..10.10 | 4,707 | 46.8% | 0.64 | 1.82 | 257s | 33.7% | 15.0% |
_D10−D1: reach2 +12.4%, p90_DD +0.57 ATR, elite +0.3%, fakeout -11.8%_

### confirm_bar_body_ATR  (Population B)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.01..0.12 | 4,707 | 37.9% | 0.44 | 1.21 | 327s | 41.8% | 17.3% |
| 2 | 0.12..0.21 | 4,707 | 37.9% | 0.48 | 1.30 | 340s | 41.8% | 16.3% |
| 3 | 0.21..0.29 | 4,707 | 37.6% | 0.51 | 1.35 | 350s | 41.0% | 14.9% |
| 4 | 0.29..0.38 | 4,706 | 38.1% | 0.52 | 1.36 | 334s | 39.8% | 15.7% |
| 5 | 0.38..0.48 | 4,707 | 38.8% | 0.51 | 1.42 | 362s | 40.1% | 16.5% |
| 6 | 0.48..0.59 | 4,707 | 39.6% | 0.54 | 1.41 | 365s | 39.9% | 15.2% |
| 7 | 0.59..0.72 | 4,706 | 40.3% | 0.55 | 1.46 | 364s | 39.3% | 15.9% |
| 8 | 0.72..0.89 | 4,707 | 41.2% | 0.60 | 1.53 | 363s | 38.2% | 16.0% |
| 9 | 0.89..1.17 | 4,707 | 42.7% | 0.56 | 1.53 | 321s | 36.1% | 16.4% |
| 10 | 1.17..8.52 | 4,707 | 46.9% | 0.64 | 1.76 | 285s | 33.2% | 15.5% |
_D10−D1: reach2 +9.0%, p90_DD +0.54 ATR, elite -1.8%, fakeout -8.6%_

### close_location_in_confirm_bar  (Population B)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.02..0.40 | 4,881 | 39.2% | 0.45 | 1.31 | 318s | 41.1% | 16.6% |
| 2 | 0.40..0.52 | 4,534 | 38.2% | 0.48 | 1.33 | 319s | 40.4% | 16.1% |
| 3 | 0.52..0.62 | 4,933 | 39.4% | 0.54 | 1.42 | 355s | 39.0% | 15.4% |
| 4 | 0.62..0.69 | 4,488 | 39.9% | 0.53 | 1.40 | 345s | 39.9% | 16.6% |
| 5 | 0.69..0.75 | 5,452 | 40.0% | 0.54 | 1.40 | 353s | 39.1% | 16.5% |
| 6 | 0.75..0.80 | 3,954 | 40.9% | 0.54 | 1.47 | 343s | 38.0% | 15.5% |
| 7 | 0.80..0.86 | 4,705 | 40.6% | 0.55 | 1.47 | 356s | 38.9% | 15.9% |
| 8 | 0.86..0.92 | 4,911 | 41.3% | 0.55 | 1.49 | 340s | 37.4% | 16.9% |
| 9 | 0.92..1.00 | 9,210 | 40.8% | 0.60 | 1.54 | 345s | 38.6% | 15.1% |
_D10−D1: reach2 +1.6%, p90_DD +0.22 ATR, elite -1.5%, fakeout -2.5%_

### extension_from_EMA13_ATR  (Population B)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -0.34..0.52 | 4,707 | 34.7% | 0.41 | 1.21 | 350s | 44.2% | 15.6% |
| 2 | 0.52..0.67 | 4,707 | 36.6% | 0.46 | 1.25 | 354s | 42.6% | 16.3% |
| 3 | 0.67..0.79 | 4,707 | 37.1% | 0.51 | 1.33 | 372s | 42.8% | 15.6% |
| 4 | 0.79..0.90 | 4,706 | 38.4% | 0.50 | 1.32 | 363s | 40.4% | 16.3% |
| 5 | 0.90..1.02 | 4,707 | 38.5% | 0.52 | 1.38 | 342s | 40.6% | 15.6% |
| 6 | 1.02..1.14 | 4,707 | 39.5% | 0.53 | 1.41 | 360s | 39.5% | 16.8% |
| 7 | 1.14..1.29 | 4,706 | 42.5% | 0.55 | 1.46 | 335s | 37.1% | 16.7% |
| 8 | 1.29..1.48 | 4,707 | 42.0% | 0.58 | 1.50 | 344s | 36.2% | 15.8% |
| 9 | 1.48..1.79 | 4,707 | 44.0% | 0.61 | 1.58 | 331s | 35.5% | 16.5% |
| 10 | 1.79..8.77 | 4,707 | 47.7% | 0.66 | 1.86 | 276s | 32.4% | 14.7% |
_D10−D1: reach2 +13.0%, p90_DD +0.65 ATR, elite -0.8%, fakeout -11.8%_

### extension_from_VWAP_ATR  (Population B)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -98.51..-8.38 | 4,707 | 37.7% | 0.54 | 1.40 | 379s | 41.7% | 14.9% |
| 2 | -8.38..-4.79 | 4,707 | 38.3% | 0.53 | 1.40 | 366s | 38.7% | 16.1% |
| 3 | -4.79..-2.56 | 4,707 | 39.5% | 0.50 | 1.33 | 339s | 40.0% | 16.5% |
| 4 | -2.56..-0.80 | 4,706 | 38.7% | 0.54 | 1.41 | 353s | 40.2% | 15.5% |
| 5 | -0.80..0.68 | 4,707 | 40.4% | 0.52 | 1.42 | 323s | 38.7% | 17.0% |
| 6 | 0.69..2.07 | 4,707 | 40.4% | 0.53 | 1.41 | 328s | 38.3% | 17.0% |
| 7 | 2.07..3.73 | 4,706 | 40.9% | 0.53 | 1.46 | 319s | 38.8% | 16.1% |
| 8 | 3.73..6.02 | 4,707 | 41.5% | 0.56 | 1.55 | 334s | 38.9% | 15.5% |
| 9 | 6.02..9.64 | 4,707 | 42.1% | 0.58 | 1.49 | 319s | 37.2% | 16.0% |
| 10 | 9.64..117.03 | 4,707 | 41.4% | 0.58 | 1.54 | 352s | 38.9% | 15.2% |
_D10−D1: reach2 +3.7%, p90_DD +0.14 ATR, elite +0.4%, fakeout -2.8%_

### gap_flip_to_entry_ATR  (Population B)
| decile | range | n | reach2 | med_DD | p90_DD | med_t2 | fakeout | elite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -0.54..0.10 | 4,707 | 37.3% | 0.43 | 1.23 | 333s | 42.3% | 16.5% |
| 2 | 0.10..0.19 | 4,707 | 37.2% | 0.48 | 1.30 | 333s | 41.1% | 16.0% |
| 3 | 0.19..0.28 | 4,707 | 38.2% | 0.49 | 1.33 | 344s | 41.2% | 15.9% |
| 4 | 0.28..0.37 | 4,706 | 38.2% | 0.53 | 1.39 | 353s | 41.3% | 15.8% |
| 5 | 0.37..0.47 | 4,707 | 39.7% | 0.51 | 1.42 | 356s | 39.8% | 16.1% |
| 6 | 0.47..0.58 | 4,707 | 38.1% | 0.54 | 1.38 | 360s | 40.1% | 15.3% |
| 7 | 0.58..0.71 | 4,706 | 40.0% | 0.58 | 1.46 | 376s | 39.5% | 15.8% |
| 8 | 0.71..0.89 | 4,707 | 42.3% | 0.57 | 1.49 | 355s | 36.7% | 16.7% |
| 9 | 0.89..1.18 | 4,707 | 43.1% | 0.58 | 1.53 | 319s | 36.1% | 16.1% |
| 10 | 1.18..8.03 | 4,707 | 46.8% | 0.64 | 1.80 | 282s | 33.3% | 15.5% |
_D10−D1: reach2 +9.4%, p90_DD +0.57 ATR, elite -1.1%, fakeout -8.9%_


# STUDY 4 — Checkpoint Feasibility

At each checkpoint, bucket OPEN trades by their state THEN (quartiles), and report forward whole-trade outcomes. `P(reach+2)`, the adverse races, and `E[term PnL]` are eventual outcomes conditioned on the checkpoint state — the feasibility signal for a hold/cut decision at that moment.

## 4a. Forward outcomes by checkpoint — bucketed on path efficiency (bottom Q1 vs top Q4)
### Population A
| checkpoint | Q1 P(reach+2) | Q4 P(reach+2) | Q1 E[term] | Q4 E[term] | Q4 P(-0.75 b/f +2) | n/qtile |
| --- | --- | --- | --- | --- | --- | --- |
| +30s | 24.8% | 54.0% | -0.70 | +0.63 | 42.4% | 27,578 |
| +60s | 21.4% | 59.7% | -0.85 | +0.85 | 34.5% | 27,379 |
| +90s | 18.0% | 65.2% | -1.00 | +1.08 | 28.7% | 27,048 |
| +120s | 16.8% | 69.6% | -1.06 | +1.23 | 24.8% | 26,384 |
| Bar2 | 16.8% | 69.6% | -1.06 | +1.23 | 24.8% | 26,384 |
| Bar3 | 15.6% | 76.9% | -1.11 | +1.56 | 20.6% | 24,574 |
| Bar5 | 17.0% | 88.6% | -1.01 | +2.18 | 19.1% | 20,704 |

### Population B
| checkpoint | Q1 P(reach+2) | Q4 P(reach+2) | Q1 E[term] | Q4 E[term] | Q4 P(-0.75 b/f +2) | n/qtile |
| --- | --- | --- | --- | --- | --- | --- |
| +30s | 26.0% | 55.6% | -0.66 | +0.62 | 43.5% | 11,550 |
| +60s | 22.8% | 61.8% | -0.85 | +0.89 | 35.2% | 11,689 |
| +90s | 19.4% | 66.8% | -1.03 | +1.07 | 30.4% | 11,583 |
| +120s | 17.8% | 70.8% | -1.11 | +1.23 | 26.6% | 11,389 |
| Bar2 | 17.8% | 70.8% | -1.11 | +1.23 | 26.6% | 11,389 |
| Bar3 | 16.3% | 77.8% | -1.16 | +1.56 | 22.9% | 10,804 |
| Bar5 | 17.6% | 88.5% | -1.06 | +2.15 | 21.1% | 9,333 |

## 4a. Forward outcomes by checkpoint — bucketed on net PnL (ATR) (bottom Q1 vs top Q4)
### Population A
| checkpoint | Q1 P(reach+2) | Q4 P(reach+2) | Q1 E[term] | Q4 E[term] | Q4 P(-0.75 b/f +2) | n/qtile |
| --- | --- | --- | --- | --- | --- | --- |
| +30s | 25.1% | 55.4% | -0.73 | +0.65 | 42.6% | 27,625 |
| +60s | 21.7% | 61.5% | -0.89 | +0.88 | 34.7% | 27,385 |
| +90s | 18.3% | 67.2% | -1.04 | +1.11 | 28.7% | 27,070 |
| +120s | 17.2% | 71.9% | -1.10 | +1.29 | 24.8% | 26,385 |
| Bar2 | 17.2% | 71.9% | -1.10 | +1.29 | 24.8% | 26,385 |
| Bar3 | 16.1% | 80.4% | -1.13 | +1.63 | 20.4% | 24,575 |
| Bar5 | 17.6% | 93.4% | -1.02 | +2.28 | 19.0% | 20,705 |

### Population B
| checkpoint | Q1 P(reach+2) | Q4 P(reach+2) | Q1 E[term] | Q4 E[term] | Q4 P(-0.75 b/f +2) | n/qtile |
| --- | --- | --- | --- | --- | --- | --- |
| +30s | 26.8% | 57.0% | -0.71 | +0.66 | 43.6% | 11,767 |
| +60s | 23.0% | 63.3% | -0.90 | +0.90 | 35.6% | 11,698 |
| +90s | 19.7% | 68.7% | -1.07 | +1.10 | 30.5% | 11,590 |
| +120s | 18.1% | 72.9% | -1.14 | +1.27 | 26.6% | 11,390 |
| Bar2 | 18.1% | 72.9% | -1.14 | +1.27 | 26.6% | 11,390 |
| Bar3 | 16.9% | 80.5% | -1.19 | +1.59 | 22.7% | 10,805 |
| Bar5 | 18.2% | 92.4% | -1.08 | +2.21 | 21.3% | 9,334 |

## 4b. Full quartile breakdown at +60s (Population A)
### cur MFE @ +60s
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -6.24..0.15 | 27,386 | 24.5% | 89.8% | 78.4% | -0.66 |
| Q2 | 0.15..0.40 | 27,385 | 31.0% | 77.3% | 64.5% | -0.28 |
| Q3 | 0.40..0.76 | 27,385 | 39.3% | 63.7% | 51.2% | +0.05 |
| Q4 | 0.76..146.79 | 27,385 | 59.8% | 39.6% | 30.5% | +0.77 |

### cur MAE @ +60s
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -146.79..0.19 | 27,386 | 52.9% | 41.0% | 30.8% | +0.62 |
| Q2 | 0.19..0.43 | 27,385 | 41.9% | 57.2% | 45.2% | +0.17 |
| Q3 | 0.43..0.74 | 27,385 | 34.7% | 72.9% | 60.8% | -0.14 |
| Q4 | 0.74..133.60 | 27,385 | 25.1% | 99.3% | 87.8% | -0.76 |

### net PnL @ +60s
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -132.88..-0.44 | 27,386 | 21.7% | 97.0% | 89.1% | -0.89 |
| Q2 | -0.44..-0.00 | 31,998 | 31.8% | 77.3% | 62.3% | -0.22 |
| Q3 | 0.01..0.40 | 22,772 | 41.2% | 58.3% | 44.8% | +0.18 |
| Q4 | 0.40..146.79 | 27,385 | 61.5% | 34.7% | 25.4% | +0.88 |

### path eff @ +60s
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -1.00..-0.15 | 27,390 | 21.4% | 94.9% | 86.0% | -0.85 |
| Q2 | -0.15..0.00 | 31,984 | 32.1% | 79.1% | 65.0% | -0.26 |
| Q3 | 0.00..0.12 | 22,778 | 43.4% | 58.5% | 45.3% | +0.22 |
| Q4 | 0.12..1.00 | 27,379 | 59.7% | 34.5% | 25.0% | +0.85 |

### stall_s @ +60s
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | 0.00..16.00 | 28,369 | 52.7% | 46.4% | 35.0% | +0.58 |
| Q2 | 17.00..40.00 | 26,903 | 42.2% | 60.2% | 48.4% | +0.14 |
| Q3 | 41.00..56.00 | 27,761 | 32.9% | 76.4% | 64.5% | -0.28 |
| Q4 | 57.00..172821.00 | 26,508 | 26.0% | 88.7% | 77.9% | -0.60 |

### HH−LL @ +60s
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -34.00..-4.00 | 27,500 | 41.3% | 65.7% | 55.9% | +0.01 |
| Q2 | -3.00..0.00 | 30,533 | 36.5% | 69.2% | 56.2% | -0.07 |
| Q3 | 1.00..4.00 | 29,162 | 37.1% | 69.0% | 56.0% | -0.05 |
| Q4 | 5.00..38.00 | 22,346 | 40.5% | 65.9% | 56.6% | -0.00 |

## 4b. Full quartile breakdown at Bar3 (Population A)
### cur MFE @ Bar3
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -6.24..0.37 | 24,575 | 21.0% | 94.9% | 85.7% | -0.78 |
| Q2 | 0.37..0.78 | 24,575 | 30.1% | 79.9% | 64.1% | -0.26 |
| Q3 | 0.78..1.37 | 24,574 | 42.7% | 57.3% | 41.7% | +0.28 |
| Q4 | 1.37..146.94 | 24,575 | 78.3% | 23.9% | 15.5% | +1.40 |

### cur MAE @ Bar3
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -144.85..0.32 | 24,575 | 65.2% | 22.0% | 14.3% | +1.11 |
| Q2 | 0.32..0.66 | 24,575 | 47.9% | 45.2% | 33.0% | +0.47 |
| Q3 | 0.66..1.09 | 24,574 | 35.8% | 89.6% | 60.6% | -0.06 |
| Q4 | 1.09..32.67 | 24,575 | 23.2% | 99.2% | 99.2% | -0.88 |

### net PnL @ Bar3
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -31.26..-0.53 | 24,575 | 16.1% | 98.7% | 94.4% | -1.13 |
| Q2 | -0.53..0.08 | 24,575 | 30.3% | 83.1% | 65.3% | -0.24 |
| Q3 | 0.08..0.77 | 24,574 | 45.2% | 53.9% | 36.0% | +0.38 |
| Q4 | 0.77..145.45 | 24,575 | 80.4% | 20.4% | 11.3% | +1.63 |

### path eff @ Bar3
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -1.00..-0.06 | 24,579 | 15.6% | 97.9% | 92.4% | -1.11 |
| Q2 | -0.06..0.01 | 24,577 | 31.0% | 84.0% | 67.5% | -0.25 |
| Q3 | 0.01..0.08 | 24,566 | 48.4% | 53.5% | 35.9% | +0.44 |
| Q4 | 0.08..1.00 | 24,574 | 76.9% | 20.6% | 11.1% | +1.56 |

### stall_s @ Bar3
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | 0.00..38.00 | 24,712 | 64.4% | 42.2% | 28.0% | +1.10 |
| Q2 | 39.00..100.00 | 24,651 | 49.5% | 51.7% | 38.0% | +0.45 |
| Q3 | 101.00..158.00 | 24,546 | 34.6% | 70.3% | 57.6% | -0.17 |
| Q4 | 159.00..189909.00 | 24,390 | 23.2% | 92.2% | 83.9% | -0.75 |

### HH−LL @ Bar3
| q | range | n | P(reach+2) | P(-0.75 b/f +2) | P(-1.0 b/f +2) | E[term PnL] |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | -76.00..-6.00 | 24,844 | 49.4% | 56.2% | 48.3% | +0.35 |
| Q2 | -5.00..0.00 | 25,636 | 37.5% | 72.0% | 54.8% | -0.02 |
| Q3 | 1.00..6.00 | 25,074 | 38.0% | 70.8% | 54.3% | +0.04 |
| Q4 | 7.00..62.00 | 22,745 | 47.7% | 56.1% | 49.2% | +0.29 |


# FINAL ANSWERS

## 1. When does DD usually occur?
**Front-loaded.** For +2 ATR winners the worst adverse excursion lands at median ~73-82s (Elite: ~23s), while +2 ATR itself is not reached until ~5.5 min. 89% of a winner's worst pre-+2 drawdown is taken BEFORE the trade shows even +1 ATR of favorable progress, at a median of ~40s. By contrast, non-reachers and fakeouts keep printing new MAE lows late (median max-MAE 227-239s). Whether adverse or favorable hits first is ~a coin flip at entry (0.5 MAE before 0.5 MFE = 51%). **Takeaway: a winner's pain is in the first ~30-60s; a trade still making new lows after a minute is behaving like a loser.**

## 2. Is DD worse after large extension bars?
**Yes — but it buys follow-through, not quality.** Bigger confirm-bar range/body and bigger EMA13 extension raise p90 pre-2ATR DD by +0.45-0.65 ATR (D1->D10), AND raise reach-2ATR by +10-13pp, cut fakeout by ~11pp, and reach +2 faster (~250s vs ~350s). But **Elite rate is FLAT across all deciles** — the extra follow-through is exactly cancelled by the extra drawdown (Elite requires MAE<=0.75). close_location and VWAP-distance carry no signal: it is the SIZE of the move, not its polish or location. Big bars trade heat for follow-through at no net quality edge.

## 3. Which early path states justify HOLDING for +2 ATR?
By **+60s**: net PnL >= ~0 (top quartile -> 62% reach+2, +0.88 ATR expectancy), high path efficiency (60% reach+2), low accumulated MAE (<0.19 ATR -> 53% reach+2), still printing new highs (low stall -> 53% reach+2). These cohorts run P(reach+2) 50-62% with positive expectancy. By **Bar3** the top-quartile net-PnL / path-efficiency trades reach +2 ATR ~80% with +1.6 ATR expectancy. **Hold the trades that are green, efficient, low-MAE, and still extending at +60s.**

## 4. Which early path states should be CUT?
By **+60s**: net PnL negative (bottom quartile -> 22% reach+2, -0.89 expectancy, **97% chance of touching -0.75 ATR before +2**), negative path efficiency (21% reach+2), accumulated MAE already >0.74 ATR (25% reach+2, -0.76), or stalled >57s with no new high (26% reach+2, -0.60). Holding these for +2 ATR is not justified — expectancy is clearly negative and the adverse race is nearly certain. **HH-LL net-extreme count and ALL entry features carry no usable signal.**

## Feasibility verdict
An adaptive exit IS causally designable. Entry features cannot sort winners from fakeouts (prior finding |d|<0.09), but the **first ~60s of PATH does**: net PnL / path efficiency / accumulated MAE / stall separate P(reach+2) from ~21% to ~60% and expectancy from -0.9 to +0.9 ATR. Natural design: a ~60s prove-it gate that cuts net-negative / high-MAE / stalled trades and holds the rest.

**Caveats (not yet a strategy):** (a) all outcomes are measured to the next opposite flip WITHOUT spread/commission; a real stop+target bracket must be 1s/tick-validated before any deployment claim (BE/SL 1s-precision rule). (b) Part of the +60s separation is mechanically tautological — a trade already up is likelier to continue and already has low MAE — so the tradeable edge is only whatever survives a proper bracket sim with costs. That sim is the next step and is deliberately out of scope here.
