"""DEPRECATED — DO NOT RUN. This builder used resample(closed='right')
which injects 1 second of look-ahead into 1m bars (see memory:
catalog_1m_resample_bug.md). Use build_v0_2026_catalog_fixed.py
instead. Legacy code removed; this stub blocks accidental runs.
"""
import sys

print("ERROR: This builder is DEPRECATED — it produced 1m bars with"
      " 1-second look-ahead bias.\n"
      "Use build_v0_2026_catalog_fixed.py (closed='left') instead.\n"
      "See memory/catalog_1m_resample_bug.md for details.")
sys.exit(2)
