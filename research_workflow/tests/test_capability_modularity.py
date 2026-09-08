"""Capability modularity (chore/capability-modularity, 2026-09-08): adding a tracker never edits a
registration module, never creates an import cycle, and never drags the feature registry into the
import closure of unrelated modules.

B1  the compiler's binding table resolves seeded bindings from ``capabilities_index.yaml`` by import
    path; ``BaseBinding`` lives in ``features/trackers/base.py`` so a binding module and the
    registration module never import each other at load time.
B2  ``import features`` (and any ``features.trackers.<x>``) does not import ``features.registry``.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[2]

_BINDING_SRC = '''
from features.trackers.base import BaseBinding, BarView


class SynthCountBinding(BaseBinding):
    CAPABILITY = "tracker.synth.count"
    PARAMS = {"window": 20}
    INPUTS = {"bars": "stream"}
    FIELDS = ("count",)
    EVENTS = ()
    CADENCE = "per_source_bar"

    def __init__(self, params, inputs):
        super().__init__(params, inputs)
        self.count = 0

    def on_bar(self, input_key: str, bar: BarView) -> None:
        self.count += 1
'''


def _seed_module(tmp_path: Path) -> Path:
    pkg = tmp_path / "synthcap"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "count_binding.py").write_text(_BINDING_SRC, encoding="utf-8")
    return tmp_path


def _seed_index(tmp_path: Path) -> Path:
    index = tmp_path / "capabilities_index.yaml"
    index.write_text(yaml.safe_dump({"trackers": [{"id": "tracker.synth.count", "version": 1, "description": "synthetic",
                                                    "implementation": "synthcap.count_binding.SynthCountBinding",
                                                    "parameters": ["window"], "status_override": "candidate"}]}), encoding="utf-8")
    return index


def test_seeded_binding_resolves_from_the_index_without_editing_the_registration_module(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_seed_module(tmp_path)))
    from features.trackers import host_bindings as hb
    from research_workflow.grammar import compiler
    index = _seed_index(tmp_path)
    assert "tracker.synth.count" not in hb.BUILTIN_BINDINGS
    table = hb.tracker_bindings(index_path=index)
    assert table["tracker.synth.count"].__name__ == "SynthCountBinding"
    assert set(hb.BUILTIN_BINDINGS) <= set(table)
    # the compatibility view and the compiler's table see the seed through the default index path
    monkeypatch.setattr(hb, "_INDEX_PATH", index)
    assert "tracker.synth.count" in hb.TRACKER_BINDINGS
    assert compiler._binding_table()["tracker.synth.count"] is table["tracker.synth.count"]


def test_unresolvable_or_foreign_seed_entries_are_skipped(tmp_path):
    from features.trackers import host_bindings as hb
    index = tmp_path / "idx.yaml"
    index.write_text(yaml.safe_dump({"trackers": [
        {"id": "tracker.nope.missing", "implementation": "synthcap.does_not_exist.Nope"},
        {"id": "tracker.regime.dual_ema", "implementation": "features.trackers.regime_dual_ema.DualEmaRegimeTracker"},  # built-in wins
        {"id": "tracker.wrong.cap", "implementation": "features.trackers.host_bindings.DualEmaRegimeBinding"},          # CAPABILITY mismatch
    ]}), encoding="utf-8")
    table = hb.tracker_bindings(index_path=index)
    assert "tracker.nope.missing" not in table and "tracker.wrong.cap" not in table
    assert table["tracker.regime.dual_ema"] is hb.BUILTIN_BINDINGS["tracker.regime.dual_ema"]


def test_importing_a_binding_module_before_the_registration_module_is_not_a_cycle(tmp_path):
    root = _seed_module(tmp_path)
    code = "import synthcap.count_binding as m; import features.trackers.host_bindings as hb; " \
           "assert issubclass(m.SynthCountBinding, hb.BaseBinding); print('OK')"
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True,
                       env={**_env(), "PYTHONPATH": str(root) + ";" + str(ROOT)})
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-800:]


def test_scaffold_template_imports_the_base_module_and_yields_a_binding():
    from features.trackers.base import BaseBinding
    from research_workflow.capability_flow import _binding_template
    p = {"name": "tracker.synth.template", "semantics": "s", "availability_rule": "a", "reset_policy": "none",
         "null_policy": "allow", "gap_policy": "carry", "parameters": {"window": 20}, "inputs": {"bars": "stream"}, "fields": ["value"]}
    src = _binding_template(p, "SynthTemplateBinding")
    assert "from features.trackers.base import" in src and "host_bindings" not in src
    ns: dict = {}
    exec(compile(src, "<scaffold>", "exec"), ns)
    cls = ns["SynthTemplateBinding"]
    assert issubclass(cls, BaseBinding) and cls.CAPABILITY == "tracker.synth.template" and cls.PARAMS == {"window": 20}


def test_compiler_refuses_a_candidate_seeded_tracker_status():
    from research_workflow.grammar.compiler import _registry_status
    ctx = SimpleNamespace(registry={"kinds": {"trackers": [{"id": "tracker.synth.count", "status": "candidate"}],
                                             "feature_hosts": [{"id": "feature_host.x", "status": "verified"}]}})
    assert _registry_status(ctx, "tracker.synth.count") == "candidate"
    assert _registry_status(ctx, "feature_host.x") == "verified"
    assert _registry_status(ctx, "tracker.unknown") is None


def test_features_package_does_not_import_the_registry():
    code = textwrap.dedent("""
        import sys
        import features
        import features.trackers.regime_dual_ema
        import features.trackers.base
        assert 'features.registry' not in sys.modules, sorted(m for m in sys.modules if m.startswith('features'))
        print('OK')
    """)
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, env={**_env(), "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-800:]


def _env() -> dict:
    import os
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
