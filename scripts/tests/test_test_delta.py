import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('delta_under_test', Path(__file__).parents[1] / 'test_delta.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
NODE = 'scripts/tests/test_example.py::test_one'
ENV = {'python': 'test-python', 'platform': 'test-platform'}

@pytest.fixture
def baseline(monkeypatch):
    monkeypatch.setattr(d, '_git', lambda args: 'a' * 40)
    monkeypatch.setattr(d, 'environment_identity', lambda: ENV, raising=False)
    return {'schema_version': 2, 'platform_commit': 'a' * 40, 'environment': ENV,
            'scopes': ['scripts/tests'], 'expected_failures': [
                {'node_id': NODE, 'scopes': ['scripts/tests'], 'message': 'AssertionError: old',
                 'classification': 'pre_existing', 'reason': 'fixture'}]}

def known(result):
    return result['counts']['KNOWN_BASELINE_FAILURE']

@pytest.mark.parametrize('message', ['FileNotFoundError: missing.py', 'ModuleNotFoundError: missing', 'is not a directory'])
def test_new_missing_file_import_path_is_never_automatic_environment(baseline, message):
    baseline['expected_failures'] = []
    r = d.classify({NODE: ('FAILED', message)}, baseline, ['scripts/tests'])
    assert r['counts']['ENVIRONMENTAL_MISSING_ARTIFACT'] == 0
    assert r['counts']['NEW_FAILURE'] == 1

def test_changed_failure_at_known_node_is_new(baseline):
    assert known(d.classify({NODE: ('FAILED', 'AssertionError: different')}, baseline, ['scripts/tests'])) == 0

def test_entry_scope_precedes_exact_node(baseline):
    baseline['expected_failures'][0]['scopes'] = ['features/tests']
    assert known(d.classify({NODE: ('FAILED', 'AssertionError: old')}, baseline, ['scripts/tests'])) == 0

@pytest.mark.parametrize('field,value', [('platform_commit', 'b' * 40), ('environment', {'python': 'other'})])
def test_baseline_commit_and_environment_are_matching_conditions(baseline, field, value):
    baseline[field] = value
    assert known(d.classify({NODE: ('FAILED', 'AssertionError: old')}, baseline, ['scripts/tests'])) == 0

def test_pytest_error_return_code_is_enforced_even_with_parsed_pass(monkeypatch, baseline, tmp_path, capsys):
    p = tmp_path / 'baseline.json'
    p.write_text(json.dumps(baseline), encoding='utf-8')
    monkeypatch.setattr(d, 'run_pytest', lambda *args: ({NODE: ('PASSED', '')}, 2, 'interrupted'))
    assert d.main(['scripts/tests', '--baseline', str(p), '--json']) != 0

def test_exact_unchanged_compatible_failure_remains_known(baseline):
    assert known(d.classify({NODE: ('FAILED', 'AssertionError: old')}, baseline, ['scripts/tests'])) == 1

def test_empty_legacy_signature_is_not_evidence(baseline):
    baseline['expected_failures'][0]['message'] = ''
    assert known(d.classify({NODE: ('FAILED', '')}, baseline, ['scripts/tests'])) == 0

def test_scope_is_path_boundary_not_prefix():
    assert not d._scope_covers(['scripts/test'], 'scripts/testing/test_x.py::test_x')


def test_real_capture_keeps_full_failure_and_per_test_timings(tmp_path, monkeypatch):
    p = tmp_path / 'test_capture.py'
    p.write_text("def test_ok(): pass\ndef test_bad(): assert False, 'signature-tail-' + 'x' * 500\n", encoding='utf-8')
    monkeypatch.setattr(d, 'ROOT', tmp_path)
    results, rc, _ = d.run_pytest([str(p)], [])
    assert rc == 1
    assert sorted(o for o, _ in results.values()) == ['FAILED', 'PASSED']
    failure = next(msg for o, msg in results.values() if o == 'FAILED')
    assert 'x' * 500 in failure
    assert set(d.run_pytest.last_timings) == set(results)
    assert all(t['seconds'] >= 0 and 'call' in t['phases'] for t in d.run_pytest.last_timings.values())

def test_real_collection_error_is_not_a_passing_result(tmp_path, monkeypatch):
    p = tmp_path / 'test_import.py'
    p.write_text('import nonexistent_wave2_fixture_module\n', encoding='utf-8')
    monkeypatch.setattr(d, 'ROOT', tmp_path)
    results, rc, _ = d.run_pytest([str(p)], [])
    assert rc == 2
    assert any(o == 'ERROR' and 'nonexistent_wave2_fixture_module' in msg for o, msg in results.values())


def test_invalid_explicit_reference_cannot_fall_back(baseline):
    assert 'BASELINE_COMMIT_MISMATCH' in d.baseline_issues(baseline, '')


def test_subprocess_env_has_no_empty_pythonpath_entry(monkeypatch, tmp_path):
    """An empty PYTHONPATH element resolves to the CWD; for a test that then spawns `python scripts/<x>.py`
    this puts scripts/ ahead of the repo root and scripts/research.py shadows the `research` package."""
    import os
    import subprocess
    seen = {}

    def fake_run(cmd, **kw):
        seen['env'] = kw['env']
        Path(kw['env']['TEST_DELTA_REPORT']).write_text('{}', encoding='utf-8')

        class R:
            returncode = 0
            stdout = ''
            stderr = ''
        return R()

    monkeypatch.setattr(subprocess, 'run', fake_run)
    for prior in (None, '', 'C:\\somewhere' if os.name == 'nt' else '/somewhere'):
        if prior is None:
            monkeypatch.delenv('PYTHONPATH', raising=False)
        else:
            monkeypatch.setenv('PYTHONPATH', prior)
        d.run_pytest(['x'], [])
        entries = seen['env']['PYTHONPATH'].split(os.pathsep)
        assert all(entries), (prior, entries)
        if prior:
            assert prior in entries


def test_portable_signature_normalises_only_machine_local_tokens():
    root = str(d.ROOT)
    sibling = root + "-some-topic"
    m = ("E  StaleCompiledStudyError: run compile --study " + sibling + "\\studies\\x | tmp_path = WindowsPath("
         "'C:/Users/Some One/AppData/Local/Temp/pytest-of-Some One/pytest-2883/test_x0') scratch/_delta_scope_3e06fffc/f.py at 0x1515AD43AC0 "
         "compiler.py:868 sha d2f026775d832ae9d290d15db79e8086d38b92dffed25820a17d8fed9f934286 in 1.69s")
    n = d.portable_signature(m)
    assert sibling not in n and "<ROOT>\\studies\\x" in n
    assert "pytest-2883" not in n and "<PYTEST_TMP>" in n
    assert "_delta_scope_3e06fffc" not in n and "_delta_scope_<TMP>" in n
    assert "0x1515AD43AC0" not in n and "<ADDR>" in n
    for exact in ("compiler.py:868", "d2f026775d832ae9d290d15db79e8086d38b92dffed25820a17d8fed9f934286", "in 1.69s"):
        assert exact in n
    assert d.portable_signature(n) == n
    assert d.portable_signature(m.replace(sibling, root).replace("pytest-2883", "pytest-2861")) == n
    doubled = "path " + root.replace("\\", "\\\\") + "\\\\features\\\\engine.py"
    assert d.portable_signature(doubled) == "path <ROOT>\\\\features\\\\engine.py"


def test_known_failure_matches_across_worktrees_but_a_changed_hash_or_line_is_still_new(baseline):
    entry = baseline['expected_failures'][0]
    node, scopes, ref = entry['node_id'], baseline['scopes'], baseline['platform_commit']
    canon = "E  boom at " + str(d.ROOT) + "\\studies\\s line compiler.py:853 hash " + "a" * 64
    entry['message'] = canon; entry['outcome'] = 'FAILED'
    from_worktree = canon.replace(str(d.ROOT), str(d.ROOT) + "-topic")
    rep = d.classify({node: ('FAILED', from_worktree)}, baseline, scopes, ref)
    assert rep['counts']['KNOWN_BASELINE_FAILURE'] == 1 and rep['counts']['NEW_FAILURE'] == 0
    for changed in (canon.replace(":853", ":868"), canon.replace("a" * 64, "b" * 64)):
        rep = d.classify({node: ('FAILED', changed)}, baseline, scopes, ref)
        assert rep['counts']['NEW_FAILURE'] == 1 and rep['NEW_FAILURE'][0]['reason'] == 'FAILURE_SIGNATURE_CHANGED_OR_MISSING'
