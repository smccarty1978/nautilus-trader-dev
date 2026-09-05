# The parent's model arms are named by TRADE direction, not by prevailing regime

**Status:** found by the population parity STOP GATE, before any statistic was produced.
Corrected in `study.yaml`; verified against the parent's frozen artifacts.

## What the gate caught

The first `analyze` run aborted at step 2:

```
ANALYSIS_POPULATION_PARITY_FAILED:
  population has 303 rows, expected 239;
  regime_direction counts {'1': 153, '-1': 150} != expected {'-1': 124, '1': 115};
  3 reference key(s) absent, 67 unexpected key(s) present;
  235 key(s) resolve at a different instant than the reference
```

Zero artifacts were written.

## It was not the data

The collected frame is byte-exact against the parent's frozen March population:

| check | result |
|---|---|
| candidate key set | 35,872 common · **0** only-mine · **0** only-parent |
| all 13 model input features | **0** mismatches, `max abs delta = 0.000e+00` |
| `rolling_300s_*` nulls | 26,018 — the parent's own count exactly |
| derived scores | present on 35,872 / 35,872 rows |

## It was the arm orientation

Scores matched the parent's recorded values *exactly* — but on the **opposite arm**. Joining the
frozen `first_p90_parity.parquet` to the collected regime directions:

```
my_direction   -1    1
direction
LONG          115    0
SHORT           0  124
```

115 / 124, no overlap, no exceptions. Corroborated independently by the parent's own GATE_3 row
counts in `validation_summary.json`: LONG 17,029 = my `regime_direction == -1`;
SHORT 18,843 = my `regime_direction == +1`.

**The parent's arm names denote the trade direction taken on the anticipated flip, not the
direction of the prevailing regime.** A bear (`-1`) regime that is about to flip up is where you
go LONG, so it is scored by the arm called `LONG`.

I had matched arms by NAME: `regime_direction == 1 -> parent_long_score`. Every regime was
therefore scored by the wrong model, which is why the crossing moved for 235 of the 236 shared
regimes and 64 extra regimes crossed at all.

## The correction

Three coordinated changes in `study.yaml`, all downstream of one YAML anchor so the anchor,
control and score-path steps move together:

| | before (wrong) | after (verified) |
|---|---|---|
| `by.cases` | `1 -> parent_long_score` | `-1 -> parent_long_score` (LONG thresholds) |
| | `-1 -> parent_short_score` | `1 -> parent_short_score` (SHORT thresholds) |
| gate `expected_by` | `{1: 115, -1: 124}` | `{-1: 115, 1: 124}` |
| gate `value_map` | `{LONG: 1, SHORT: -1}` | `{LONG: -1, SHORT: 1}` |

Thresholds travel with their arm: LONG `p90 = 0.2852887899663343`,
SHORT `p90 = 0.28485631865861344`. No model, threshold or feature changed — only which arm is
applied to which regime.

## Why this matters beyond this study

Nothing in the machinery was broken. The models loaded, authenticated, and scored; the features
were exact; the binding reproduced the parent's own scores to `0.0`. A name was read as a
definition. Without an executable gate this would have produced a complete, internally consistent
set of statistics — cumulative incidence, negative decomposition, control comparison, warning
subtypes — over 303 anchors scored by the wrong model, and nothing in the output would have
looked wrong.

That is precisely the failure the parity gate exists to prevent, and the reason a STOP GATE has
to be executable rather than declared. See `declared_stop_gate_must_be_executable` and
`verify_reused_column_definition_not_name`.
