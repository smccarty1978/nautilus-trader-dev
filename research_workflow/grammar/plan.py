"""CompiledPlan: the single artifact the host executes and the audits read.

A plan is plain data (JSON-serialisable dict sections) plus its own identity.  Every
scientific implementation is named by dotted path; the host loads it, never imports it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PLAN_VERSION = 1


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class CompiledPlan:
    study: Dict[str, Any]
    instruments: Dict[str, Dict[str, Any]]
    streams: List[Dict[str, Any]]
    session: Dict[str, Any]
    trackers: List[Dict[str, Any]]
    population: Dict[str, Any]
    triggers: Dict[str, Any]
    outcome: Dict[str, Any]
    columns: Dict[str, Any]
    chronology: Dict[str, Any]
    model: Optional[Dict[str, Any]]
    closure: Dict[str, Any]
    binding_proof: List[Dict[str, Any]]
    warmup: Dict[str, Any]
    availability: Dict[str, Any]
    plan_version: int = PLAN_VERSION
    plan_sha256: str = ""
    spec_sha256: str = ""
    registry_sha256: str = ""
    features: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def identity_payload(self) -> Dict[str, Any]:
        d = self.to_dict()
        d.pop("plan_sha256", None)
        d.pop("notes", None)
        return d

    def seal(self) -> "CompiledPlan":
        self.plan_sha256 = hashlib.sha256(canonical_json(self.identity_payload()).encode("utf-8")).hexdigest()
        return self

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> "CompiledPlan":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompiledPlan":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def card(self) -> Dict[str, Any]:
        return {
            "STATUS": "COMPILED", "study_id": self.study.get("id"), "plan_sha256": self.plan_sha256,
            "streams": [s["key"] for s in self.streams], "trackers": [t["id"] for t in self.trackers],
            "features": len((self.features or {}).get("instances") or []),
            "population": self.population.get("cadence", {}).get("kind"),
            "triggers": self.triggers.get("kind"), "outcome": {"contract": self.outcome.get("contract"), "kernel": self.outcome.get("kernel")},
            "closure_sha256": self.closure.get("composite_sha256"), "catalog_opened": False,
        }


__all__ = ["CompiledPlan", "PLAN_VERSION", "canonical_json"]
