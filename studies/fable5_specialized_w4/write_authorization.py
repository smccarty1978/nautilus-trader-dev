"""Record the pre-execution authorization binding audit + code hashes.

Run ONLY after the lookahead pre-execution audit is a verified clean PASS on
the current file contents. Any later edit to SPEC/code invalidates the
authorization (require_authorization re-checks all hashes).
"""
from __future__ import annotations

import json
import re

import fable5_common as C


def main() -> None:
    text = C.PRE_AUDIT.read_text(encoding="utf-8")
    if not (re.search(r"^\*\*Status:\*\*\s+\*\*PASS", text, re.MULTILINE)
            and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                          text, re.MULTILINE)):
        raise RuntimeError("audit is not a clean PASS; refusing to authorize")
    payload = {
        "status": "PASS",
        "audit_sha256": C.sha256_file(C.PRE_AUDIT),
        "spec_sha256": C.sha256_file(C.STUDY / "SPEC.md"),
        "common_sha256": C.sha256_file(C.STUDY / "fable5_common.py"),
        "build_dataset_sha256": C.sha256_file(C.STUDY / "build_dataset.py"),
        "train_models_sha256": C.sha256_file(C.STUDY / "train_models.py"),
        "replay_selection_sha256": C.sha256_file(C.STUDY / "replay_selection.py"),
    }
    C.PRE_AUTH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
