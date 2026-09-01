"""Run the generic post-collection first-P90 descriptive artifact producer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.analysis.first_p90_warning_horizon import produce_first_p90_warning_horizon


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(produce_first_p90_warning_horizon(study_dir=args.study, run_dir=args.run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
