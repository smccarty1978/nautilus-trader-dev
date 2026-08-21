#!/usr/bin/env python3
"""Explicit, recorded bootstrap of a study's durable audit lineage anchor (RT3-B1).

Why this is a separate, deliberate command
------------------------------------------
``resolve_effective_lineage`` used to bootstrap the anchor silently whenever one was
missing but a local ledger existed. That made the anchor's absence indistinguishable
from a study that never had one -- which is precisely the state ``rm audit_lineage/<id>.json``
manufactures. Deleting the anchor therefore reset the audit high-water mark, and nothing
recorded that it had happened.

Bootstrap is now refused inside the audit path and lives here instead. It is the one
legitimate way an anchor comes into existence for a study that already has history, and
every use of it is visible: it writes ``bootstrapped_from_local_ledger: true``, records
the ledger it was derived from, and prints the ``git add`` the operator must run. An
anchor is only durable once it is committed.

Two legitimate uses
-------------------
1. **Migration.** A study that issued passes before the anchor existed --
   ``es_wick_imbalance_acceptance_v2`` is the one such study in this repository. Its
   ledger is committed; the anchor is derived from it.
2. **A deliberately copied study identity.** Copying ``studies/A`` to ``studies/B``
   carries A's ledger into B. B has no anchor, so the audit path refuses. The operator
   decides which is true and says so:
   ``--adopt-ledger``  B legitimately inherits A's audit history;
   ``--fresh-identity`` B is a new study and starts at pass 01 with an empty anchor.
   Neither is guessed, because guessing wrong in either direction is a real failure --
   one launders history, the other loses it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_preexec_audits import (  # noqa: E402
    _lineage_path,
    _lineage_rel_path,
    _read_pass_ledger,
    _write_lineage_anchor,
    read_lineage_anchor,
)


def bootstrap(study_dir: Path, repo_root: Path, adopt_ledger: bool, fresh: bool) -> int:
    study_dir = study_dir.resolve()
    if not study_dir.is_dir():
        print(f"STUDY_NOT_FOUND: {study_dir}")
        return 2

    existing = read_lineage_anchor(study_dir, repo_root)
    if existing is not None:
        print(
            f"ANCHOR_ALREADY_EXISTS: {_lineage_path(study_dir, repo_root)} already "
            f"records issuance {existing.get('issuance_counter')} / high_water "
            f"{existing.get('high_water')}. Bootstrap is a one-time act; refusing to "
            f"overwrite an established anchor."
        )
        return 1

    local = _read_pass_ledger(study_dir)

    if local and not (adopt_ledger or fresh):
        print(
            f"BOOTSTRAP_INTENT_REQUIRED: {study_dir.name} carries a local pass ledger "
            f"with {len(local)} entr{'y' if len(local) == 1 else 'ies'}. State which is "
            f"true:\n"
            f"  --adopt-ledger   this study legitimately owns that audit history "
            f"(migration of a pre-anchor study)\n"
            f"  --fresh-identity this is a NEW study identity whose audit/ was copied "
            f"from another; history does not transfer and it starts at pass 01"
        )
        return 1

    entries = [] if fresh else local
    _write_lineage_anchor(study_dir, entries, repo_root, bootstrapped=True)
    anchor_p = _lineage_path(study_dir, repo_root)
    payload = json.loads(anchor_p.read_text(encoding="utf-8"))

    print(f"ANCHOR_BOOTSTRAPPED: {anchor_p}")
    print(f"  study_id:          {payload['study_id']}")
    print(f"  entries adopted:   {len(entries)}")
    print(f"  high_water:        {payload['high_water']}")
    print(f"  issuance_counter:  {payload['issuance_counter']}")
    print(f"  chain_sha256:      {payload['chain_sha256'][:16]}...")
    print()
    print("The anchor is durable only once it is committed. Run:")
    print(f"  git add {_lineage_rel_path(study_dir)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--study", required=True, help="Path to the study directory")
    ap.add_argument(
        "--adopt-ledger",
        action="store_true",
        help="This study legitimately owns the audit history in its local pass ledger",
    )
    ap.add_argument(
        "--fresh-identity",
        action="store_true",
        help="New study identity: start at an empty anchor, ignoring a copied ledger",
    )
    args = ap.parse_args()

    if args.adopt_ledger and args.fresh_identity:
        print("BOOTSTRAP_INTENT_CONTRADICTORY: --adopt-ledger and --fresh-identity "
              "cannot both be true.")
        return 2

    return bootstrap(Path(args.study), REPO_ROOT, args.adopt_ledger, args.fresh_identity)


if __name__ == "__main__":
    raise SystemExit(main())
