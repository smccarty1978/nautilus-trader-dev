from studies.Codex_structural_regime_geometry_maturity.implementation.promote import lint_ok, phase0_ok, promotion_status


def test_phase0_and_lint_gates_require_explicit_clean_status(tmp_path):
    phase0, lint = tmp_path / "phase0.json", tmp_path / "lint.json"
    phase0.write_text('{"status": "PASS"}')
    lint.write_text('{"critical": 0, "warning": 0}')
    assert phase0_ok(phase0) and lint_ok(lint)
    phase0.write_text('{"status": "FAIL"}')
    lint.write_text('{"critical": 0, "warning": 1}')
    assert not phase0_ok(phase0) and not lint_ok(lint)


def test_each_frozen_promotion_blocker_prevents_pass():
    clean = dict(verification={"pass": True}, report_hash="abc", validation={"status": "PASS"},
                 phase0_pass=True, lint_pass=True, causal_pass=True, contract_pass=True,
                 terminal="S5_NO_MATERIAL_INCREMENTAL_INFORMATION")
    assert promotion_status(**clean) == "PASS"
    for blocker in ("phase0_pass", "lint_pass", "causal_pass", "contract_pass"):
        blocked = dict(clean)
        blocked[blocker] = False
        assert promotion_status(**blocked) == "BLOCKED"
