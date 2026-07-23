# Canonical Checkpoint Population Quality Report

## Status

Build validation passed. This is a policy-neutral descriptive artifact; no strategy or exit conclusion is made.

## Row counts

| direction    |   year |   rows |
|:-------------|-------:|-------:|
| bearish_fade |   2024 | 161220 |
| bearish_fade |   2025 | 163397 |
| bullish_fade |   2024 | 204610 |
| bullish_fade |   2025 | 198255 |

## Prediction parity

```json
{
  "bullish_reference_max_abs_diff": 0.0,
  "bearish_fixture_max_abs_diff": 0.0
}
```

## Missingness

| column                              |   missing |   missing_pct |
|:------------------------------------|----------:|--------------:|
| regime_start_ns                     |         0 |    0          |
| observation_time                    |         0 |    0          |
| confirm_flip_ns                     |         0 |    0          |
| checkpoint_price                    |         0 |    0          |
| atr_at_checkpoint                   |         0 |    0          |
| seconds_to_flip                     |         0 |    0          |
| flip_le_300                         |         0 |    0          |
| flip_le_600                         |         0 |    0          |
| direction                           |         0 |    0          |
| year                                |         0 |    0          |
| artifact_name                       |         0 |    0          |
| artifact_causal_status              |         0 |    0          |
| known_feature_lookahead_seconds     |         0 |    0          |
| trade_direction                     |         0 |    0          |
| model_score                         |         0 |    0          |
| checkpoint_sequence                 |         0 |    0          |
| regime_age_seconds                  |         0 |    0          |
| score_percentile                    |         0 |    0          |
| is_top_1                            |         0 |    0          |
| is_first_top_1                      |         0 |    0          |
| is_top_2_5                          |         0 |    0          |
| is_first_top_2_5                    |         0 |    0          |
| is_top_5                            |         0 |    0          |
| is_first_top_5                      |         0 |    0          |
| is_top_10                           |         0 |    0          |
| is_first_top_10                     |         0 |    0          |
| is_top_25                           |         0 |    0          |
| is_first_top_25                     |         0 |    0          |
| top_bucket                          |         0 |    0          |
| selected_first_signal               |         0 |    0          |
| flip_open_price                     |         0 |    0          |
| flip_close_price                    |         0 |    0          |
| atr_at_confirmed_flip               |         0 |    0          |
| atr_confirm_source_observation_time |         0 |    0          |
| atr_confirm_source_gap_seconds      |         0 |    0          |
| checkpoint_to_flip_close_atr        |         0 |    0          |
| next_opposing_confirm_flip_ns       |         0 |    0          |
| to_flip_path_available              |         0 |    0          |
| to_flip_first_bar_lag_s             |         1 |    0.00013746 |
| to_flip_terminal_bar_lag_s          |         1 |    0.00013746 |
| to_flip_interior_gap_count          |         1 |    0.00013746 |
| mfe_to_flip_atr                     |         1 |    0.00013746 |
| mae_to_flip_atr                     |         1 |    0.00013746 |
| mfe_timestamp                       |         1 |    0.00013746 |
| mae_timestamp                       |         1 |    0.00013746 |
| fixed_300_path_available            |         0 |    0          |
| fixed_300_first_bar_lag_s           |         0 |    0          |
| fixed_300_terminal_bar_lag_s        |         0 |    0          |
| fixed_300_interior_gap_count        |         0 |    0          |
| mfe_300s_atr                        |         0 |    0          |
| mae_300s_atr                        |         0 |    0          |
| fixed_600_path_available            |         0 |    0          |
| fixed_600_first_bar_lag_s           |         0 |    0          |
| fixed_600_terminal_bar_lag_s        |         0 |    0          |
| fixed_600_interior_gap_count        |         0 |    0          |
| mfe_600s_atr                        |         0 |    0          |
| mae_600s_atr                        |         0 |    0          |
| post_60_path_available              |         0 |    0          |
| post_60_first_bar_lag_s             |        64 |    0.00879747 |
| post_60_terminal_bar_lag_s          |        64 |    0.00879747 |
| post_60_interior_gap_count          |        64 |    0.00879747 |
| post_flip_mfe_60s_atr               |        64 |    0.00879747 |
| post_flip_mae_60s_atr               |        64 |    0.00879747 |
| post_300_path_available             |         0 |    0          |
| post_300_first_bar_lag_s            |        64 |    0.00879747 |
| post_300_terminal_bar_lag_s         |        64 |    0.00879747 |
| post_300_interior_gap_count         |        64 |    0.00879747 |
| post_flip_mfe_300s_atr              |        64 |    0.00879747 |
| post_flip_mae_300s_atr              |        64 |    0.00879747 |
| post_600_path_available             |         0 |    0          |
| post_600_first_bar_lag_s            |        64 |    0.00879747 |
| post_600_terminal_bar_lag_s         |        64 |    0.00879747 |
| post_600_interior_gap_count         |        64 |    0.00879747 |
| post_flip_mfe_600s_atr              |        64 |    0.00879747 |
| post_flip_mae_600s_atr              |        64 |    0.00879747 |
| post_next_flip_path_available       |         0 |    0          |
| post_next_flip_first_bar_lag_s      |         0 |    0          |
| post_next_flip_terminal_bar_lag_s   |         0 |    0          |
| post_next_flip_interior_gap_count   |         0 |    0          |
| post_flip_mfe_until_next_flip_atr   |         0 |    0          |
| post_flip_mae_until_next_flip_atr   |         0 |    0          |

## Provenance

```json
{
  "years": [
    2024,
    2025
  ],
  "bullish_model_sha256": "efec43fe7bf73298b6cdd8d71c90ecbe4642d7ebf8729efe5f27d88a71a67215",
  "bearish_model_sha256": "1d696d85f2e31026db8415fb15913267d447bd7fde9be0fcefed490c7bf4af26",
  "raw_sha256": {
    "2024": "387303eccf03893a5ba34f93c6ddec79893542289503147960533b1655daa954",
    "2025": "c4d498e77da916fd372b1faf455c68513dac38fdf45eced028b9fb99345d1e2d"
  },
  "frozen_inputs": {
    "bullish_manifest_sha256": "9fdddbd941a97829c3df1060e8bd0c6d8544850f9a8a3555059d270dff50e1c2",
    "bearish_manifest_sha256": "76cd0c03ba2fc5cd0380cef66217a7e2223d38a0fd640a0aa4aeedadf6f0667c",
    "bearish_monthly": {
      "2024": {
        "checkpoint_sha256": "e1b69345ff6533c4f34d6e2985ea743055c249ee8a756c112d61749230ba9f48",
        "rows": 161220
      },
      "2025": {
        "checkpoint_sha256": "5b93b795b15f016acecf7a7f6963d788392a9185ff3e71f616f526bb8674069a",
        "rows": 163397
      }
    }
  },
  "estimated_peak_memory_mb": {
    "2024": 5386.676228046417,
    "2025": 5386.676228046417
  },
  "configured_memory_bound_mb": 10000,
  "output_sha256": "97afa92a737749fe217a217f87f8ade25ef39cc14b18ad47f8a48b77f0a595c3"
}
```
