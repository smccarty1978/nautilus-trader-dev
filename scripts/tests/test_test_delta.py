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
