import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Any, Dict, Optional


class DailyStateCheckpointer:
    """Manages atomic state serialization and manifest verification for resumes."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.checkpoint_dir / "resume_manifest.json"

    @staticmethod
    def calculate_file_sha256(filepath: Path) -> str:
        """Calculates the SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def get_git_commit_hash(self) -> str:
        """Retrieves the current git commit hash if in a git repo."""
        import subprocess
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True
            )
            return res.stdout.strip()
        except Exception:
            return "unknown"

    def write_manifest(
        self,
        current_date_str: str,
        strategy_config: Dict[str, Any],
        model_paths: Dict[str, Path]
    ) -> None:
        """Writes the resume manifest JSON file atomically."""
        model_hashes = {}
        for name, path in model_paths.items():
            if os.path.exists(path):
                model_hashes[name] = self.calculate_file_sha256(Path(path))
            else:
                model_hashes[name] = "missing"

        manifest = {
            "last_processed_date": current_date_str,
            "git_commit": self.get_git_commit_hash(),
            "strategy_config": strategy_config,
            "model_hashes": model_hashes
        }

        tmp_path = self.manifest_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4)
        os.replace(tmp_path, self.manifest_path)

    def verify_manifest(
        self,
        strategy_config: Dict[str, Any],
        model_paths: Dict[str, Path]
    ) -> Optional[str]:
        """Verifies if the manifest exists and matches current configs. Returns the last date if valid."""
        if not self.manifest_path.exists():
            return None

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Check config matches
            if manifest.get("strategy_config") != strategy_config:
                return None

            # Check model hashes match
            for name, path in model_paths.items():
                if not os.path.exists(path):
                    return None
                actual_hash = self.calculate_file_sha256(Path(path))
                if manifest.get("model_hashes", {}).get(name) != actual_hash:
                    return None

            return manifest.get("last_processed_date")
        except Exception:
            return None

    def save_checkpoint(self, day_str: str, state: Dict[str, Any]) -> None:
        """Saves a day's strategy state checkpoint atomically."""
        checkpoint_path = self.checkpoint_dir / f"checkpoint_{day_str}.pkl"
        tmp_path = checkpoint_path.with_suffix(".pkl.tmp")

        with open(tmp_path, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, checkpoint_path)

    def load_checkpoint(self, day_str: str) -> Dict[str, Any]:
        """Loads a state checkpoint for the specified day."""
        checkpoint_path = self.checkpoint_dir / f"checkpoint_{day_str}.pkl"
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        with open(checkpoint_path, "rb") as f:
            return pickle.load(f)
