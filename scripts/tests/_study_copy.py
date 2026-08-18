"""Shared test helper: copy a study into scratch space as a FRESH audit identity.

RT3-B1 made a missing durable anchor fail closed for any study that already carries audit
history, because "no anchor" was indistinguishable from `rm audit_lineage/<id>.json` --
which is how the anchor was reset. A scratch `shutil.copytree(STUDY_DIR, tmp/study)`
inherits the source study's committed `audit/pass_ledger.json` while having a different
identity and no anchor, so it is, correctly, exactly that refused shape.

The tests that do this are not testing lineage; they want a working study to exercise
seals, smoke gating or deliverables against. The honest way to express that is what the
production tool calls `--fresh-identity`: the copy is a new study, so the source's audit
history does not transfer and its ledger is dropped.

Tests that DO exercise lineage (`test_rt_blockers`, `test_rt_final_blockers`) build their
own studies and must not use this helper -- dropping the ledger is the very state they
assert against.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PASS_LEDGER_NAME = "pass_ledger.json"


def copy_study_as_fresh_identity(
    src: Path, dst: Path, dirs_exist_ok: bool = True
) -> Path:
    """Copies ``src`` to ``dst`` and drops any inherited audit pass ledger."""
    shutil.copytree(Path(src), Path(dst), dirs_exist_ok=dirs_exist_ok)
    ledger = Path(dst) / "audit" / PASS_LEDGER_NAME
    if ledger.is_file():
        ledger.unlink()
    return Path(dst)
