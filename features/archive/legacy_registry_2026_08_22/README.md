# Legacy Feature Registry Archive (2026-08-22)

This is a non-runtime, immutable rollback/reference snapshot created immediately
before the Feature System V2 full canonical-registry cutover.  It preserves the
legacy registry, lifecycle evidence, promotion evidence, provider source, and
relevant schema/validation source.

To reference the previous authority, inspect the copied files in this directory.
To restore deliberately, copy only the required source files back to the repo and
restart governed acceptance; this archive is never imported by runtime code.

The complete migration inventory is written to
`scratch/feature_system_v2_full_migration_inventory.json`.  `manifest.json` and
`sha256s.json` enumerate and integrity-pin every archived source file.
