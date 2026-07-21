# Rejection-Filter Analysis — Level Momentum Study

## Definitions

Categorize each trade by gap size and MAE:
- Wide gaps (>= 25.0 pt): deep MAE = > 15.0 pt
- Narrow gaps (< 25.0 pt): deep MAE = > 12.0 pt

Categories:
- **clean_win**: winner with MAE <= deep threshold (low-stress wins)
- **deep_win**: winner with MAE > deep threshold ('lucky' wins that drew down deep)
- **cat_loss**: loser with MAE > deep threshold (would have hit cat-30 territory)
- **other_loss**: loser with MAE <= deep threshold (would have BE-stopped or hit a tight stop)
- **timed_out**: time limit reached

Question: do `deep_win` and `cat_loss` share features that distinguish them from `clean_win`? If yes, we can filter them out at trigger time.

## Category sizes (overall)

| Category | n | % |
|---|--:|--:|
| clean_win | 30,168 | 51.3% |
| cat_loss | 21,565 | 36.7% |
| deep_win | 5,088 | 8.6% |
| other_loss | 1,224 | 2.1% |
| timed_out | 786 | 1.3% |

## Feature distributions by category (overall)

Means with [p25, p75] for context.

| Category | n | close_dist_from_level | close_pos_in_zone | trigger_range_pts | trigger_close_pos | first_bar_range_pts | first_bar_close_pos | first_bar_close_move_pts |
|---|---|---|---|---|---|---|---|---|
| cat_loss | 21,565 | 2.57 [1.00,3.50] | 0.17 [0.07,0.26] | 14.21 [6.00,17.50] | 0.78 [0.68,0.93] | 13.23 [5.25,16.25] | 0.38 [0.13,0.59] | -5.06 [-8.00,0.25] |
| clean_win | 30,168 | 2.66 [1.00,3.50] | 0.20 [0.08,0.30] | 12.72 [6.00,16.25] | 0.79 [0.69,0.93] | 11.43 [5.00,14.50] | 0.59 [0.35,0.84] | 4.04 [-0.75,6.50] |
| deep_win | 5,088 | 3.52 [1.50,5.00] | 0.21 [0.09,0.32] | 16.03 [7.50,20.75] | 0.79 [0.69,0.93] | 13.64 [6.00,18.00] | 0.42 [0.17,0.67] | -2.43 [-6.75,1.00] |
| other_loss | 1,224 | 0.83 [0.25,1.00] | 0.08 [0.03,0.10] | 7.73 [3.75,9.25] | 0.78 [0.65,0.94] | 6.72 [3.25,8.75] | 0.42 [0.14,0.67] | -1.43 [-3.75,0.75] |
| timed_out | 786 | 1.77 [0.75,2.50] | 0.09 [0.03,0.12] | 5.05 [2.75,6.25] | 0.79 [0.69,0.95] | 3.78 [2.25,4.69] | 0.47 [0.18,0.75] | -0.19 [-1.50,1.00] |

## Comparison: clean_win vs deep_win vs cat_loss

Side-by-side means for the three key categories.

| Feature | clean_win | deep_win | cat_loss | Δ (cat - clean) | Δ (deep - clean) |
|---|--:|--:|--:|--:|--:|
| close_dist_from_level | 2.659 | 3.519 | 2.570 | -0.089 | +0.860 |
| close_pos_in_zone | 0.196 | 0.210 | 0.168 | -0.028 | +0.014 |
| trigger_range_pts | 12.724 | 16.027 | 14.214 | +1.489 | +3.302 |
| trigger_close_pos | 0.787 | 0.791 | 0.783 | -0.004 | +0.004 |
| first_bar_range_pts | 11.430 | 13.637 | 13.227 | +1.796 | +2.207 |
| first_bar_close_pos | 0.585 | 0.421 | 0.376 | -0.210 | -0.164 |
| first_bar_close_move_pts | 4.038 | -2.428 | -5.060 | -9.099 | -6.466 |

## By gap-size class

### >= 25.0pt gaps

| Category | n | % |
|---|--:|--:|
| clean_win | 5,290 | 43.7% |
| deep_win | 1,026 | 8.5% |
| other_loss | 161 | 1.3% |
| cat_loss | 5,297 | 43.8% |
| timed_out | 321 | 2.7% |

| Category | close_dist_from_level | close_pos_in_zone | trigger_range_pts | trigger_close_pos | first_bar_range_pts | first_bar_close_pos | first_bar_close_move_pts |
|---|---|---|---|---|---|---|---|
| clean_win | 3.874 | 0.172 | 15.181 | 0.797 | 13.237 | 0.604 | 4.974 |
| deep_win | 4.459 | 0.198 | 17.454 | 0.809 | 14.526 | 0.459 | -1.739 |
| cat_loss | 3.185 | 0.142 | 14.974 | 0.790 | 13.355 | 0.403 | -4.531 |

### < 25.0pt gaps

| Category | n | % |
|---|--:|--:|
| clean_win | 24,878 | 53.2% |
| deep_win | 4,062 | 8.7% |
| other_loss | 1,063 | 2.3% |
| cat_loss | 16,268 | 34.8% |
| timed_out | 465 | 1.0% |

| Category | close_dist_from_level | close_pos_in_zone | trigger_range_pts | trigger_close_pos | first_bar_range_pts | first_bar_close_pos | first_bar_close_move_pts |
|---|---|---|---|---|---|---|---|
| clean_win | 2.400 | 0.201 | 12.202 | 0.784 | 11.046 | 0.581 | 3.839 |
| deep_win | 3.282 | 0.213 | 15.666 | 0.786 | 13.413 | 0.412 | -2.601 |
| cat_loss | 2.369 | 0.177 | 13.966 | 0.781 | 13.185 | 0.367 | -5.233 |

## Hour-of-CT distribution by category

(% of category falling in each hour bucket; helps identify time-of-day filters)

| Category | h00 | h01 | h02 | h03 | h04 | h05 | h06 | h07 | h08 | h09 | h10 | h11 | h12 | h13 | h14 | h15 | h16 | h17 | h18 | h19 | h20 | h21 | h22 | h23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean_win | 2.9% | 3.8% | 4.4% | 4.5% | 3.8% | 4.1% | 4.3% | 4.6% | 6.2% | 6.9% | 6.6% | 5.6% | 5.3% | 5.4% | 5.3% | 3.6% | 0.0% | 3.9% | 3.3% | 4.1% | 3.4% | 2.8% | 2.4% | 2.6% |
| deep_win | 3.1% | 3.5% | 4.4% | 3.3% | 2.7% | 2.9% | 3.6% | 4.7% | 8.3% | 8.9% | 7.6% | 6.7% | 6.6% | 6.0% | 6.3% | 2.9% | 0.1% | 3.4% | 3.2% | 3.1% | 2.4% | 2.1% | 2.2% | 2.0% |
| cat_loss | 2.9% | 3.7% | 4.3% | 4.4% | 3.6% | 3.8% | 4.1% | 4.8% | 6.9% | 7.5% | 6.7% | 5.8% | 5.7% | 5.6% | 5.6% | 3.4% | 0.0% | 3.6% | 3.1% | 3.6% | 3.0% | 2.7% | 2.5% | 2.5% |

## Round-level breakdown

Round = breach at .00 or .50 within handle.

| Category | round n | round % | non-round n | non-round % |
|---|--:|--:|--:|--:|
| clean_win | 9,762 | 32.4% | 20,406 | 67.6% |
| deep_win | 2,003 | 39.4% | 3,085 | 60.6% |
| cat_loss | 6,856 | 31.8% | 14,709 | 68.2% |
| other_loss | 428 | 35.0% | 796 | 65.0% |
| timed_out | 480 | 61.1% | 306 | 38.9% |
