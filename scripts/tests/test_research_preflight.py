"""Tests for research preflight orchestrator in scripts/research_preflight.py.
===========================================================================
"""

import json
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.research_preflight import run_preflight


def test_preflight_clean_study(tmp_path):
    study_dir = tmp_path / "study_clean"
    study_dir.mkdir()
    (study_dir / "SPEC.md").write_text("# Test Spec", encoding="utf-8")
    (study_dir / "run_study.py").write_text(
        "import pandas as pd\ndef run():\n    return pd.Series([1, 2, 3])\n",
        encoding="utf-8",
    )
    
    code, result = run_preflight(study_dir, [], skip_tests=True)
    assert code == 0
    assert result["status"] == "CLEAR"
    assert (study_dir / "audit" / "preflight.json").exists()


def test_preflight_blocked_by_causal_leak(tmp_path):
    study_dir = tmp_path / "study_leaky"
    study_dir.mkdir()
    (study_dir / "SPEC.md").write_text("# Leaky Spec", encoding="utf-8")
    # Deliberate B1 centered rolling leak
    (study_dir / "run_study.py").write_text(
        "import pandas as pd\ndef run(df):\n    return df.c.rolling(10, center=True).mean()\n",
        encoding="utf-8",
    )

    code, result = run_preflight(study_dir, [], skip_tests=True)
    assert code == 1
    assert result["status"] == "BLOCKED"
    assert result["failed_gate"] == "CAUSAL_LINT"
    assert "B1" in result["failure_ids"]
    assert (study_dir / "audit" / "failure_packet.json").exists()
