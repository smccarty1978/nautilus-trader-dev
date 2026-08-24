"""Mandatory preflight facade."""
from scripts.research_preflight import main, run_preflight
from scripts.select_required_tests import get_test_selection_report

__all__ = ["main", "run_preflight", "get_test_selection_report"]
