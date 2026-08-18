# Durable audit lineage anchors

One JSON file per study identity: `audit_lineage/<study_id>.json`.

**These files are part of the repository and MUST be committed.** They are the durable
half of the audit-immutability control (RT-3 / RT3-B1). The study-local
`studies/<id>/audit/pass_ledger.json` records the same issuances, but it lives inside the
directory an attacker or a careless rebuild deletes; the anchor does not.

## What the anchor guarantees

Once an issuance has been **committed**, deleting or rewinding working-tree files cannot
silently restore an earlier audit high-water mark:

| Attack | Detected as |
| --- | --- |
| delete `audit_lineage/<id>.json` | `AUDIT_LINEAGE_ANCHOR_MISSING` |
| delete `studies/<id>/audit/` (ledger) | `AUDIT_LINEAGE_RESET_DETECTED` |
| roll anchor **and** ledger back together | `AUDIT_LINEAGE_ROLLBACK_DETECTED` (via `HEAD`) |
| edit anchor entries | `AUDIT_LINEAGE_TAMPERED` |
| point the anchor at another study | `AUDIT_LINEAGE_IDENTITY_MISMATCH` |
| hand-edit the ledger to add passes | `AUDIT_LINEAGE_UNANCHORED` |

## What it does NOT guarantee

No signature, no trusted timestamp, no defence against a rewritten git history. Those
require a key or a server and this repository has neither. The durability boundary is
**the commit**: an issuance that has not been committed is only as durable as the
working tree.

## Creating an anchor

Never by hand, and never as a silent side effect. A study with existing audit history but
no anchor fails closed. Bootstrap is explicit:

```
python scripts/bootstrap_audit_lineage.py --study studies/<id> --adopt-ledger
git add audit_lineage/<id>.json
```

Use `--fresh-identity` instead when the study directory was copied from another and the
audit history does **not** transfer.
