#!/usr/bin/env python3
"""Restrict Bash commands available to the results-triager subagent.

This is a command-shape guard, not a complete operating-system sandbox.
It permits only direct pytest execution using a small set of recognized
Python/pytest launch forms. It rejects shell composition, arbitrary Python
scripts, external plugin-loading options, dangerous pytest path/configuration
overrides, and commands outside the allowlist.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Sequence


# Reject all common shell composition, substitution, redirection, and
# background-execution operators before parsing the command.
BLOCKED_SHELL_SYNTAX = (
    "&&",
    "||",
    "|",
    "&",
    ";",
    ">",
    "<",
    "`",
    "$(",
    "\n",
    "\r",
)

PYTEST_EXECUTABLES = {
    "pytest",
    "pytest.exe",
}

PYTHON_EXECUTABLES = {
    "python",
    "python.exe",
    "python3",
    "python3.exe",
}

PY_LAUNCHERS = {
    "py",
    "py.exe",
}

# These pytest options can load arbitrary modules, redirect discovery outside
# the project, overwrite or clear arbitrary temporary directories, alter
# import/configuration behavior, or create unmanaged output files.
BLOCKED_PYTEST_EXACT_OPTIONS = {
    "-c",
    "-o",
    "-p",
    "--basetemp",
    "--confcutdir",
    "--doctest-modules",
    "--html",
    "--junit-xml",
    "--junitxml",
    "--override-ini",
    "--pdb",
    "--pdbcls",
    "--pyargs",
    "--rootdir",
    "--self-contained-html",
    "--trace",
}

BLOCKED_PYTEST_OPTION_PREFIXES = (
    "--basetemp=",
    "--confcutdir=",
    "--html=",
    "--junit-xml=",
    "--junitxml=",
    "--override-ini=",
    "--pdbcls=",
    "--rootdir=",
)

WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:")


def block(reason: str) -> int:
    """Block the pending Bash call and explain why."""
    print(f"Blocked results-triager Bash command: {reason}", file=sys.stderr)
    return 2


def executable_name(value: str) -> str:
    """Return a normalized executable basename."""
    return Path(value).name.lower()


def strip_python_launcher(argv: Sequence[str]) -> list[str] | None:
    """Return pytest arguments if argv is an approved launch form."""
    if not argv:
        return None

    executable = executable_name(argv[0])

    if executable in PYTEST_EXECUTABLES:
        return list(argv[1:])

    if executable in PYTHON_EXECUTABLES:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2].lower() == "pytest":
            return list(argv[3:])
        return None

    if executable in PY_LAUNCHERS:
        remaining = list(argv[1:])

        # Permit Windows launcher forms such as:
        # py -3 -m pytest ...
        # py -3.12 -m pytest ...
        if remaining and re.fullmatch(r"-\d+(?:\.\d+)?", remaining[0]):
            remaining = remaining[1:]

        if len(remaining) >= 2 and remaining[0] == "-m" and remaining[1].lower() == "pytest":
            return remaining[2:]

        return None

    return None


def contains_outside_project_path_syntax(argument: str) -> bool:
    """Conservatively reject obvious paths outside the current project."""
    if not argument:
        return False

    # Preserve pytest node identifiers such as:
    # tests/test_file.py::test_name
    path_candidate = argument.split("::", 1)[0]

    if path_candidate.startswith(("/", "\\", "~")):
        return True

    if WINDOWS_ABSOLUTE_PATH.match(path_candidate):
        return True

    path_parts = re.split(r"[\\/]", path_candidate)
    if ".." in path_parts:
        return True

    return False


def validate_pytest_arguments(arguments: Sequence[str]) -> str | None:
    """Return a blocking reason, or None when arguments are accepted."""
    for index, argument in enumerate(arguments):
        normalized = argument.lower()

        if normalized in BLOCKED_PYTEST_EXACT_OPTIONS:
            return f"pytest option is not permitted: {argument!r}"

        if any(normalized.startswith(prefix) for prefix in BLOCKED_PYTEST_OPTION_PREFIXES):
            return f"pytest option is not permitted: {argument!r}"

        # Block compact plugin forms such as "-pfoo" and "-pno:plugin".
        if normalized.startswith("-p") and normalized != "-q":
            return f"pytest plugin-loading option is not permitted: {argument!r}"

        # Block compact configuration override forms such as "-ovalue".
        if normalized.startswith("-o") and normalized != "-q":
            return f"pytest configuration override is not permitted: {argument!r}"

        if contains_outside_project_path_syntax(argument):
            return f"paths outside the project are not permitted: {argument!r}"

        # A standalone option that requires a following value is already
        # blocked above. This check documents malformed trailing options.
        if index == len(arguments) - 1 and normalized in {
            "-c",
            "-k",
            "-m",
            "-o",
            "-p",
            "--basetemp",
            "--confcutdir",
            "--junitxml",
            "--maxfail",
            "--pdbcls",
            "--rootdir",
        }:
            return f"pytest option is missing its required value: {argument!r}"

    return None


def is_within_project(path: Path, project_root: Path) -> bool:
    """Return True when path resolves inside project_root."""
    try:
        path.resolve().relative_to(project_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def main() -> int:
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError) as exc:
        return block(f"invalid hook input: {exc}")

    tool_name = str(payload.get("tool_name", ""))
    if tool_name and tool_name != "Bash":
        return block(f"unexpected tool name: {tool_name!r}")

    command = str(payload.get("tool_input", {}).get("command", "")).strip()
    if not command:
        return block("empty command")

    for token in BLOCKED_SHELL_SYNTAX:
        if token in command:
            return block(
                "shell chaining, piping, redirection, substitution, "
                f"or background execution is not allowed: {token!r}"
            )

    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        return block(f"command could not be parsed safely: {exc}")

    pytest_arguments = strip_python_launcher(argv)
    if pytest_arguments is None:
        return block(
            "only direct pytest, python -m pytest, python3 -m pytest, "
            "or py -3 -m pytest commands are permitted"
        )

    argument_error = validate_pytest_arguments(pytest_arguments)
    if argument_error is not None:
        return block(argument_error)

    project_root_value = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_root_value:
        project_root = Path(project_root_value)

        cwd_value = payload.get("cwd")
        if cwd_value:
            cwd = Path(str(cwd_value))
            if not is_within_project(cwd, project_root):
                return block(
                    f"hook working directory is outside the project: {cwd}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
