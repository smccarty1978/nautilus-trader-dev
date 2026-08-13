"""Deterministic identifiers and version pins for the regime-complete store.

Every identifier here is derived only from immutable facts and is stable across
reruns, independent of row order, partition boundaries, and process identity.

`regime_engine_version` is the SHA-256 of the `RegimeEngine` class source text.
Because it is an input to `regime_id`, a silent substitution of the regime rule
changes every identifier in the store and is immediately detectable rather than
quietly producing a different population under the same keys.
"""
from __future__ import annotations

import hashlib
import inspect
import struct
from functools import lru_cache
from pathlib import Path

CONTRACT_VERSION = "regime_complete_v1"
_NULL = b"\x00"


@lru_cache(maxsize=1)
def regime_engine_version() -> str:
    from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine

    source = inspect.getsource(RegimeEngine).encode("utf-8")
    return hashlib.sha256(source).hexdigest()


@lru_cache(maxsize=None)
def collector_version(*module_files: str) -> str:
    """Hash of this study's implementation sources, in a stable order."""
    here = Path(__file__).parent
    names = sorted(module_files) or sorted(p.name for p in here.glob("*.py"))
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(_NULL)
        digest.update(hashlib.sha256((here / name).read_bytes()).digest())
    return digest.hexdigest()


def regime_id(instrument_id: str, start_decision_ns: int, direction: int) -> str:
    """Frozen construction. See SPEC section 5.1."""
    if direction not in (-1, 1):
        raise ValueError(f"regime direction must be +/-1, got {direction!r}")
    digest = hashlib.sha256()
    digest.update(CONTRACT_VERSION.encode("utf-8"))
    digest.update(_NULL)
    digest.update(instrument_id.encode("utf-8"))
    digest.update(_NULL)
    digest.update(struct.pack("<q", int(start_decision_ns)))
    digest.update(_NULL)
    digest.update(struct.pack("<b", int(direction)))
    digest.update(_NULL)
    digest.update(regime_engine_version().encode("utf-8"))
    return "RGM_" + digest.hexdigest()[:24]


def score_observation_id(instrument_id: str, decision_ns: int) -> str:
    """The accepted store's semantic key, promoted to an explicit column."""
    digest = hashlib.sha256()
    digest.update(CONTRACT_VERSION.encode("utf-8"))
    digest.update(_NULL)
    digest.update(instrument_id.encode("utf-8"))
    digest.update(_NULL)
    digest.update(struct.pack("<q", int(decision_ns)))
    return "SCR_" + digest.hexdigest()[:24]


def feature_snapshot_id(instrument_id: str, decision_ns: int) -> str:
    """One feature snapshot per true score checkpoint (DECISION-5, inline)."""
    return "FSN_" + score_observation_id(instrument_id, decision_ns)[4:]
