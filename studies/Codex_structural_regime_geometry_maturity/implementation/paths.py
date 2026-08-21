"""Single source of truth for corrected-collection lineage."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/Codex_structural_regime_geometry_maturity"
# Every producer and consumer must use this exact root.  It is intentionally
# distinct from the discarded pre-audit collection and is sealed in manifests.
COLLECTION_ROOT = STUDY / "_work/collection_audit_fix_v2"
