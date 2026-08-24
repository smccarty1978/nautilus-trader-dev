#!/usr/bin/env python3
"""Generate the shareable canonical feature vocabulary from registry authority.

The output is deliberately generated, never hand-maintained.  It is only run
after the canonical registry authority has complete parity evidence; running it
before cutover produces a staging preview and refuses to overwrite the final
reference unless explicitly requested.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_OUT = ROOT / "features" / "CANONICAL_FEATURE_REFERENCE.yaml"


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("'", "''")


def render() -> str:
    from features.candidate_authority import load_authority
    bundle = load_authority("active")
    aliases = bundle["aliases"].get("aliases", {})
    lines = ["schema_version: 2", "generated_from: active canonical feature authority", "features:"]
    for definition in sorted(bundle["registry"].get("definitions", []), key=lambda item: item["canonical_name"]):
        name = definition["canonical_name"]
        parameters = definition.get("parameter_schema", [])
        parameter_lines = [f"      - {parameter}" for parameter in parameters]
        if not parameter_lines:
            parameter_lines = ["      []"]
        examples = [alias for alias, record in aliases.items() if record.get("canonical_feature") == name][:3]
        lines.extend((
            f"  - canonical_name: {name}",
            f"    family: {', '.join(definition.get('family', []))}",
            f"    description: Canonical {name} building block.",
            f"    dtype: {definition.get('dtype', 'float64')}",
            f"    status: {definition.get('status', 'verified')}",
            f"    provider: {definition.get('provider', '')}",
            "    parameters:",
            *parameter_lines,
            "    temporal_semantics:",
            f"      input_requirements: [{', '.join(definition.get('input_availability_contracts', []))}]",
            f"    null_policy: {', '.join(definition.get('null_policies', []))}",
            f"    reset_policy: {', '.join(definition.get('reset_policies', []))}",
            f"    example_instances: [{', '.join(examples)}]",
        ))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--staging", action="store_true", help="write a staging preview before registry authority cutover")
    args = parser.parse_args()
    from features.candidate_authority import ACTIVE_POINTER
    if args.output == DEFAULT_OUT and not args.staging and not ACTIVE_POINTER.is_file():
        raise SystemExit("CANONICAL_REFERENCE_REQUIRES_AUTHORITY_CUTOVER: use --staging before cutover")
    args.output.write_text(render(), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
