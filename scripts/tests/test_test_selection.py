"""Tests for diff-aware test selection in scripts/select_required_tests.py.
========================================================================
"""

import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.select_required_tests import select_tests_for_files


def test_select_resampling_test():
    files = ["utils/resampling.py"]
    tests = select_tests_for_files(files)
    assert "scripts/tests/test_resampling.py" in tests


def test_select_model_binding_test():
    files = ["scripts/check_model_binding.py"]
    tests = select_tests_for_files(files)
    assert "scripts/tests/test_model_binding.py" in tests


def test_unresolved_falls_back_to_full_suite():
    files = ["strategies/unknown_strategy.py"]
    tests = select_tests_for_files(files)
    assert "scripts/tests/test_causal_lint.py" in tests
    assert "scripts/tests/test_causal_canaries.py" in tests
