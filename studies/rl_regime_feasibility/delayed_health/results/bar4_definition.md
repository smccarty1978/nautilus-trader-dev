# Bar-4 Delayed Entry Definition

## Resolution

**Bar-4 decision timestamp**: `flip_time + 240 seconds`
**Observation step**: `step_index >= 48` (5s steps from flip)
**Fill**: next 1s bar OPEN at or after decision timestamp

## Counting Convention

- **Bar 0**: the 1m flip bar itself (closes at `flip_time`)
- **Bar 1**: closes at `flip_time + 60s`
- **Bar 2**: closes at `flip_time + 120s`
- **Bar 3**: closes at `flip_time + 180s`
- **Bar 4**: closes at `flip_time + 240s` ← **decision point**

Entry fill occurs at the next 1s bar open after the bar-4 close.

## Survival Requirement

Episode must still be active (no opposing flip, no cap) at the bar-4 decision timestamp.

## Sources and Ambiguity

The archived `delayed_entry_bar4.py` uses `delay_s=120` from V_A entry_ts, which was
approximately flip_time - 30s (V_A entry = flip_bar_open + 30s). This yields
~flip_time + 90s, not 240s.

The MEMORY.md ML entry study ("bar-4 all-flips") and post-bar3 studies consistently
treat "bar 4" as the 4th bar after flip close = flip + 240s.

We adopt **flip + 240s** as canonical and run placebo tests at [60, 120, 180, 240, 300, 360]s
to empirically locate the survival knee.

## Example

```
flip confirmed at 10:00:00 (bar 0 closes)
bar 1 completes at 10:01:00
bar 2 completes at 10:02:00
bar 3 completes at 10:03:00
bar 4 completes at 10:04:00  <- entry decision
fill at 10:04:01 (next 1s bar open)
```
