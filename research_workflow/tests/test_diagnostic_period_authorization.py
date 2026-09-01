import yaml
import pytest

from research_workflow.experiment import ExperimentAuthorizationError, authorize_diagnostic_period


def _write_study(path, *, diagnostic, prohibited):
    path.mkdir(); (path / "artifacts").mkdir()
    (path / "study.yaml").write_text(yaml.safe_dump({"study": {"id": path.name}, "chronology": {"diagnostic": diagnostic, "prohibited": prohibited}}))


def test_diagnostic_authorization_inherits_parent_open_year_and_rejects_prohibited(tmp_path):
    parent = tmp_path / "parent"; child = tmp_path / "child"
    _write_study(parent, diagnostic=[], prohibited=[])
    (parent / "study.yaml").write_text(yaml.safe_dump({"study": {"id": "parent"}, "chronology": {"train": [2023], "dev": [2024], "prohibited": [2025]}}))
    _write_study(child, diagnostic=[2024], prohibited=[2025, 2026])
    assert authorize_diagnostic_period(child, parent_study_path=parent)["years"] == [2024]
    (child / "study.yaml").write_text(yaml.safe_dump({"study": {"id": "child"}, "chronology": {"diagnostic": [2025], "prohibited": [2025, 2026]}}))
    with pytest.raises(ExperimentAuthorizationError, match="DIAGNOSTIC_YEAR_PROHIBITED"):
        authorize_diagnostic_period(child, parent_study_path=parent)
