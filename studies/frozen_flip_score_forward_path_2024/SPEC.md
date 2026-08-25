# Frozen Flip Score Forward Path 2024

This is a descriptive, post-event OOS follow-up to the repaired classifier study.
It applies frozen TRAIN C-arm scores, thresholds, and decile boundaries to 2024
and measures forward price paths. It does not fit a model, select a threshold from
2024, or define an executable strategy.

The signal-entry and confirmation-entry populations are separate. Signal entries
are selected at frozen first crossings; confirmation entries use the completed 1m
flip close only after a signal has confirmed. Outcome columns are post-event data
and are prohibited from the classifier feature surface.
