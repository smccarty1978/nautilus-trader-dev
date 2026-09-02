"""Feature instance set-expansion.

    - {feature: regime_efficiency, over: {timeframe: [1m, 5m]}, context: prior}

expands to one instance per element of the cartesian product of ``over``; every other key
(except ``feature``/``parameters``/``alias``) is a fixed parameter.  Expansion is purely
syntactic and deterministic (row order, then product order), so a 532-instance matrix is
authored as a handful of lines and compiles to exactly the same ordered instance list.
"""
from __future__ import annotations

from itertools import product
from typing import Any, Dict, List, Mapping, Sequence

_RESERVED = {"feature", "parameters", "over", "alias"}


def expand_instances(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in items:
        row = dict(row)
        feature = row["feature"]
        fixed: Dict[str, Any] = dict(row.get("parameters") or {})
        for k, v in row.items():
            if k not in _RESERVED:
                fixed[k] = v
        over: Dict[str, List[Any]] = dict(row.get("over") or {})
        alias = row.get("alias")
        if not over:
            out.append({"feature": feature, "parameters": dict(fixed), **({"alias": alias} if alias else {})})
            continue
        if alias:
            raise ValueError(f"FEATURE_EXPANSION_ALIAS: {feature}: an explicit alias cannot be combined with 'over'")
        keys = list(over)
        for combo in product(*(list(over[k]) for k in keys)):
            params = dict(fixed)
            params.update(dict(zip(keys, combo)))
            out.append({"feature": feature, "parameters": params})
    return out


__all__ = ["expand_instances"]
