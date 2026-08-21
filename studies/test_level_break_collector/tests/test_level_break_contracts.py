import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY_DIR = Path(__file__).resolve().parents[1]

def test_nautilustrader_runtime_invariant():
    study_yaml = STUDY_DIR / "study.yaml"
    assert study_yaml.exists()

def test_feature_count_7():
    import yaml
    with open(STUDY_DIR / "study.yaml", "r") as f:
        data = yaml.safe_load(f)
    assert len(data["features"]["feature_list"]) == 7
