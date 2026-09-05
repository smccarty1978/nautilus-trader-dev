"""Thin entrypoint for the Research Supervisor (same verbs as ``python scripts/research.py supervise ...``).

    python scripts/research_supervisor.py start --question question.md [--study-id <id>] [--provider <p>] [--execute-authorized]
    python scripts/research_supervisor.py loop [--study <id>] [--once]        # what the detached loop runs
    python scripts/research_supervisor.py status <id> | list | stop <id> | tick [<id>] | decide <id> --answer <file> | adopt --study <dir> | providers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    from research_workflow.supervisor.cli import add_supervise_parser
    ap = argparse.ArgumentParser(prog="research_supervisor", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="group", required=True)
    add_supervise_parser(sub, ROOT)
    ns = ap.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    raise SystemExit(main())
