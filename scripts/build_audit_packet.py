import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def calculate_sha256(filepath: Path) -> str:
    """Calculates the SHA256 of the specified file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_git_diff(study_dir: Path) -> str:
    """Gets the unstaged and staged git diff for files inside the study directory."""
    try:
        # Run git diff for changes in this directory
        res = subprocess.run(
            ["git", "diff", "HEAD", "--", str(study_dir)],
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout
    except Exception as e:
        return f"Error getting git diff: {e}"


def get_git_changed_files(study_dir: Path) -> list:
    """Gets the list of changed files inside the study directory."""
    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", str(study_dir)],
            capture_output=True,
            text=True,
            check=True
        )
        return [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", type=str, required=True, help="Path to study folder (e.g. studies/nt_reduced_f3_top25_population_parity_smoke)")
    args = ap.parse_args()

    study_dir = Path(args.study)
    if not study_dir.exists():
        print(f"Error: Study directory '{study_dir}' does not exist.")
        return

    audit_dir = study_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    packet_path = audit_dir / "audit_packet.json"

    print(f"Building audit packet for {study_dir}...")

    # 1. Collect SPEC
    spec_path = study_dir / "SPEC.md"
    spec_content = ""
    if spec_path.exists():
        spec_content = spec_path.read_text(encoding="utf-8")
    else:
        print("Warning: SPEC.md not found in study directory.")

    # 2. Collect file list and compute hashes
    code_files = []
    for root, _, files in os.walk(study_dir):
        # Skip work, cache, and audit directories
        if "_work" in root or "cache" in root or "audit" in root or ".pytest_cache" in root:
            continue
        for file in files:
            if file.endswith(".py") or file.endswith(".yaml") or file.endswith(".json"):
                filepath = Path(root) / file
                rel_path = filepath.relative_to(study_dir)
                code_files.append({
                    "file": str(rel_path),
                    "sha256": calculate_sha256(filepath)
                })

    # 3. Get Git diff & list of changed files
    git_diff = get_git_diff(study_dir)
    changed_files = get_git_changed_files(study_dir)

    # 4. Gather test results if present
    test_results = {}
    test_log = study_dir / "results" / "test_report.json"
    if test_log.exists():
        try:
            with open(test_log, "r", encoding="utf-8") as f:
                test_results = json.load(f)
        except Exception:
            test_results = {"error": "could not parse test_report.json"}

    # 5. Assemble packet
    packet = {
        "study_name": study_dir.name,
        "study_id": study_dir.name,
        "spec_content": spec_content,
        "code_files": code_files,
        "changed_files": changed_files,
        "git_diff_content": git_diff,
        "test_results": test_results
    }

    # Write packet atomically
    tmp_path = packet_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=4)
    os.replace(tmp_path, packet_path)

    print(f"Successfully generated audit packet: {packet_path}")


if __name__ == "__main__":
    main()
