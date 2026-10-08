"""NTFS read-only protection of live data (incident 2026-10-08: catalogs deleted through a worktree junction).

Every test works on a sandbox catalog root under tmp_path and lifts the protection afterwards, so pytest can clean up.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="NTFS ACL protection is Windows-only")

from scripts import protect_live_data as P  # noqa: E402


@pytest.fixture()
def live(tmp_path: Path):
    cat_root = tmp_path / "live" / "catalog"
    ds = cat_root / "NQ_FAKE" / "data" / "bar"
    ds.mkdir(parents=True)
    (ds / "part.parquet").write_bytes(b"irreplaceable\n")
    (cat_root / "NQ_FAKE" / "dataset_manifest.json").write_text("{}")
    raw = tmp_path / "live" / "raw"
    raw.mkdir()
    (raw / "NQ_v0_1s_2022.parquet").write_bytes(b"raw\n")
    args = ["--catalog-root", str(cat_root), "--raw-dir", str(raw), "--state", str(tmp_path / "state.json")]
    assert P.main(["apply", *args]) == 0
    yield cat_root, raw, args
    P.main(["remove", *args])


def _junction(link: Path, target: Path) -> None:
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"junction creation unavailable: {res.stdout} {res.stderr}")


def test_apply_then_verify_reports_protected(live):
    cat_root, raw, args = live
    assert P.main(["verify", *args]) == 0


def test_verify_fails_closed_on_unprotected_catalog(tmp_path):
    root = tmp_path / "c"
    (root / "DS").mkdir(parents=True)
    assert P.main(["verify", "--catalog-root", str(root), "--state", str(tmp_path / "s.json")]) == 1


def test_reads_still_work(live):
    cat_root, raw, _ = live
    assert (cat_root / "NQ_FAKE" / "data" / "bar" / "part.parquet").read_bytes() == b"irreplaceable\n"
    assert (raw / "NQ_v0_1s_2022.parquet").read_bytes() == b"raw\n"


def test_rmtree_of_protected_catalog_is_denied_and_nothing_is_lost(live):
    cat_root, _, _ = live
    with pytest.raises(PermissionError):
        shutil.rmtree(cat_root / "NQ_FAKE")
    assert (cat_root / "NQ_FAKE" / "data" / "bar" / "part.parquet").read_bytes() == b"irreplaceable\n"


def test_writes_renames_and_new_files_inside_a_catalog_are_denied(live):
    cat_root, _, _ = live
    part = cat_root / "NQ_FAKE" / "data" / "bar" / "part.parquet"
    with pytest.raises(PermissionError):
        part.write_bytes(b"overwritten")
    with pytest.raises(PermissionError):
        (part.parent / "new.parquet").write_bytes(b"x")
    with pytest.raises(PermissionError):
        os.rename(cat_root / "NQ_FAKE", cat_root / "NQ_FAKE_moved")
    assert part.read_bytes() == b"irreplaceable\n"


def test_a_new_catalog_can_still_be_built_beside_protected_ones(live):
    cat_root, _, _ = live
    new = cat_root / "NEW_BUILD" / "data"
    new.mkdir(parents=True)
    (new / "x.parquet").write_bytes(b"x")
    assert (new / "x.parquet").exists()


def test_raw_files_cannot_be_deleted_or_modified_but_new_raw_can_be_added(live):
    _, raw, _ = live
    f = raw / "NQ_v0_1s_2022.parquet"
    with pytest.raises(PermissionError):
        f.unlink()
    with pytest.raises(PermissionError):
        f.write_bytes(b"tampered")
    (raw / "NQ_v0_1s_2027.parquet").write_bytes(b"new year")
    assert f.read_bytes() == b"raw\n"


def test_incident_reproduction_forced_worktree_removal_through_junction_loses_nothing(live, tmp_path):
    """The exact 2026-10-08 sequence against a protected sandbox catalog."""
    cat_root, _, _ = live
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a, cwd=repo: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)  # noqa: E731
    g("init", "-q")
    (repo / "f.txt").write_text("x")
    g("add", "f.txt")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    wt = tmp_path / "repo-tmp_worktree"
    assert g("worktree", "add", "--detach", str(wt)).returncode == 0
    (wt / "data" / "catalog").mkdir(parents=True)
    link = wt / "data" / "catalog" / "NQ_FAKE"
    _junction(link, cat_root / "NQ_FAKE")

    g("worktree", "remove", "--force", str(wt))  # the incident command; outcome irrelevant, data must survive

    assert (cat_root / "NQ_FAKE" / "data" / "bar" / "part.parquet").read_bytes() == b"irreplaceable\n"
    assert (cat_root / "NQ_FAKE" / "dataset_manifest.json").exists()
    if link.exists():
        os.rmdir(link)  # remove the junction itself, non-recursively


def test_control_without_protection_the_incident_sequence_destroys_the_catalog(tmp_path):
    """Proves the reproduction above is faithful: unprotected, the same commands delete through the junction."""
    target = tmp_path / "unprotected" / "NQ_FAKE"
    (target / "data").mkdir(parents=True)
    (target / "data" / "part.parquet").write_bytes(b"irreplaceable\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)  # noqa: E731
    g("init", "-q")
    (repo / "f.txt").write_text("x")
    g("add", "f.txt")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    wt = tmp_path / "repo-tmp_worktree"
    assert g("worktree", "add", "--detach", str(wt)).returncode == 0
    (wt / "data" / "catalog").mkdir(parents=True)
    _junction(wt / "data" / "catalog" / "NQ_FAKE", target)
    g("worktree", "remove", "--force", str(wt))
    assert not (target / "data" / "part.parquet").exists(), "git no longer deletes through junctions; revisit tests"


def test_remove_lifts_protection(tmp_path):
    root = tmp_path / "c"
    (root / "DS").mkdir(parents=True)
    (root / "DS" / "f").write_bytes(b"x")
    args = ["--catalog-root", str(root), "--state", str(tmp_path / "s.json")]
    assert P.main(["apply", *args]) == 0
    assert P.main(["remove", *args]) == 0
    shutil.rmtree(root / "DS")
    assert not (root / "DS").exists()


def test_apply_is_idempotent(live):
    _, _, args = live
    assert P.main(["apply", *args]) == 0
    assert P.main(["verify", *args]) == 0
