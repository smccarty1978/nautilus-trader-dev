from studies.Codex_structural_regime_geometry_maturity.implementation.contracts import TERMINAL_LABELS, classify_terminal, verify_selection_seal, write_selection_seal


def test_every_frozen_terminal_label_is_reachable():
    observed = {
        classify_terminal(abort=True, classification_cells=9, younger_only=False, economics_nonworse=True, economic_tail_only=True),
        classify_terminal(abort=False, classification_cells=2, younger_only=False, economics_nonworse=True, economic_tail_only=False),
        classify_terminal(abort=False, classification_cells=2, younger_only=True, economics_nonworse=True, economic_tail_only=False),
        classify_terminal(abort=False, classification_cells=2, younger_only=False, economics_nonworse=False, economic_tail_only=False),
        classify_terminal(abort=False, classification_cells=0, younger_only=False, economics_nonworse=False, economic_tail_only=True),
        classify_terminal(abort=False, classification_cells=0, younger_only=False, economics_nonworse=False, economic_tail_only=False),
    }
    assert observed == set(TERMINAL_LABELS)


def test_selection_seal_detects_tampering(tmp_path):
    artifact = tmp_path / "metric.csv"
    artifact.write_text("original")
    write_selection_seal(tmp_path, ["metric.csv"])
    assert verify_selection_seal(tmp_path)["pass"]
    artifact.write_text("altered")
    check = verify_selection_seal(tmp_path)
    assert not check["pass"]
    assert check["mismatches"] == ["metric.csv"]


def test_selection_seal_detects_tampered_seal_payload(tmp_path):
    artifact = tmp_path / "metric.csv"
    artifact.write_text("original")
    write_selection_seal(tmp_path, ["metric.csv"])
    seal = tmp_path / "selection_seal.json"
    seal.write_text(seal.read_text().replace('"artifact_count": 1', '"artifact_count": 2'))
    assert not verify_selection_seal(tmp_path)["pass"]
