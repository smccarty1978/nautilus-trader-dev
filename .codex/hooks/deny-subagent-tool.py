#!/usr/bin/env python3
"""Deny a tool call for a bounded Codex subagent."""

from __future__ import annotations

import json
import sys
from typing import Any


def main() -> int:
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError) as exc:
        print(f"Blocked tool call: invalid hook input: {exc}", file=sys.stderr)
        return 2

    tool_name = str(payload.get("tool_name", "unknown"))
    print(
        f"Blocked {tool_name}: this subagent is configured as read-only "
        "or non-editing.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
