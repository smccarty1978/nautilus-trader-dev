# Updated Pre-Flip Model Contracts

Model identity is defined by the prevailing regime being faded. Trade direction is separate metadata.

## Bullish Fade contract

- Candidate regime: bullish (`+1`).
- Positive class: confirmed bearish flip within 300 seconds.
- Score: positive-class probability, column index `1`.
- Economic meaning: high score means a weakening bullish regime and a possible future short entry.
- Current status: `REQUIRES_TARGET_AND_DIRECTION_SEMANTICS_REAUDIT` / `UNVALIDATED_FOR_PRODUCTION`.
- Reason: the frozen lineage discloses an inherited open-labelled one-second look-ahead and the reliability study found abnormal timing behavior. Naming and polarity are internally consistent; production validity is not established.

## Bearish Fade contract

- Candidate regime: bearish (`-1`).
- Positive class: confirmed bullish flip within 300 seconds.
- Score: positive-class probability, column index `1`.
- Economic meaning: high score means a weakening bearish regime and a possible future long entry.
- Current production artifact: `BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2`.
- Strict timing: every open-labelled source bar satisfies `ts_event < observation_time`.

Frozen historical artifact paths and binaries remain unchanged. New code must resolve models through `model_registry.py` and use canonical names or lowercase runtime aliases.

