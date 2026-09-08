"""Feature identity types: the schema a definition is written in and the request shape a study makes.

Split out of ``features/registry.py`` so that the definition modules and the resolver share one
vocabulary without either importing the other.  This module carries no definitions and no
resolution: it changes only when the shape of a feature declaration changes, which is a
core-surface change by construction.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Set
import re
import hashlib
import warnings

@dataclass
class FeatureDefinition:
    """Metadata schema defining a registered canonical or alias feature."""
    name: str
    aliases: Tuple[str, ...] = ()
    version: str = "1.0"
    status: str = "verified"  # verified, provisional, deprecated, archived
    family: str = ""
    stateful: bool = True
    source_timeframe: str = "1s"
    update_anchor: str = "after_1s_close"
    snapshot_anchor: str = "caller_defined"
    warmup: Optional[int] = None
    normalizer: str = "study_contract"
    direction_normalized: bool = True
    dtype: str = "float64"
    null_policy: str = "disallow"
    implementation: str = ""
    tests: Tuple[str, ...] = ()
    parity_tolerance: str = "tight"
    # Added by nt_live_scoring_infra_prereqs Phase 2 -- FEATURE_REGISTRY_CONTRACT.md
    # section 2 already specified `window_unit`/`reset_policy` as required tracker
    # parameterization in prose; these fields encode that as actual registry data
    # instead of leaving it narrative-only. `window` is the paired numeric lookback
    # value (e.g. 30 for a 30-second window); None where a feature has no single
    # scalar window (e.g. stateless/session-boundary features).
    window: Optional[float] = None
    window_unit: Optional[str] = None  # bars|seconds|minutes|events|session|since_signal|since_regime_flip
    reset_policy: str = "none"  # e.g. event_start, session_boundary, none
    # V2 additions.  Legacy physical entries leave these empty; canonical definitions
    # declare their supported instance parameters here.  This deliberately extends the
    # existing registry record rather than creating a parallel metadata authority.
    parameter_schema: Tuple[str, ...] = ()
    supported_bar_states: Tuple[str, ...] = ("completed",)
    supported_timeframes: Tuple[str, ...] = ()
    supported_update_every: Tuple[str, ...] = ()
    supported_parameter_values: Mapping[str, Tuple[Any, ...]] = field(default_factory=dict)
    required_parameters: Tuple[str, ...] = ()
    supported_parameter_combinations: Tuple[Mapping[str, Any], ...] = ()
    temporal_identity_exception: bool = False
    coverage_family: str = ""


class FeatureInstanceError(ValueError):
    """Fail-closed instance/configuration error."""


_DURATION_RE = re.compile(r"^(?P<value>[1-9][0-9]*)(?P<unit>s|m)$")
_TEMPORAL_NAME_RE = re.compile(r"(?:^|_)[0-9]+(?:s|m)(?:_|$)|(?:^|_)rolling_[0-9]+(?:s|m)(?:_|$)")
_INSTANCE_NAME_RE = re.compile(
    r"(?:^|_)(?:ema|sma|wma|rsi|median|atr)_[1-9][0-9]*(?:_|$)|"
    r"(?:^|_)(?:period|window|lookback)_[1-9][0-9]*(?:_|$)|"
    r"(?:^|_)seq_[1-9][0-9]*r(?:_|$)"
)


@dataclass(frozen=True)
class FeatureInstance:
    """A study-local request for one canonical definition.

    Instances are intentionally not a registry and have no lifecycle state.  The
    physical alias is an output-compatibility name, while verification remains on the
    canonical FeatureDefinition.
    """
    canonical_name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    physical_alias: Optional[str] = None


def _duration_seconds(value: str) -> int:
    match = _DURATION_RE.fullmatch(value)
    if not match:
        raise FeatureInstanceError(f"INVALID_TEMPORAL_PARAMETER: {value!r}; expected '<positive>s' or '<positive>m'")
    number = int(match.group("value"))
    return number * (60 if match.group("unit") == "m" else 1)
