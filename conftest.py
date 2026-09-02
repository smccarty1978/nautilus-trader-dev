"""Repository-wide test isolation for machine-local roots (research_workflow.roots).

Catalog roots stay as configured (tests that need real market data use them); the MODEL
store root is redirected to a per-session temporary directory so no test fit can land in
the operator's durable store.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_model_store(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    monkeypatch.setenv("NT_RESEARCH_MODEL_ROOT", str(tmp_path_factory.mktemp("model_root")))
    yield
