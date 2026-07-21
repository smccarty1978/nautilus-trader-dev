"""Combined report across all 8 analyses.

Runs each analysis in sequence, captures stdout, concatenates into
a single markdown file at results/report.md.
"""

import subprocess
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ANALYSES = [
    ("1-2: Bar+1 Close Features", "bar1_close_analysis.py"),
    ("3: Multi-Timeframe Alignment", "mtf_alignment.py"),
    ("4: Volume at Flip + Bar+1", "volume_analysis.py"),
    ("5: Pre-Flip Compression", "compression_analysis.py"),
    ("6: 5s Micro-Context", "micro_context.py"),
    ("7: Cohen's d Full Scan", "cohens_d_full.py"),
    ("8: Feature Interactions", "feature_interactions.py"),
]


def run_script(script: str) -> str:
    path = Path(__file__).parent / script
    result = subprocess.run(
        [sys.executable, "-u", str(path)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    out = result.stdout
    if result.stderr and result.returncode != 0:
        out += f"\n\n!!! stderr:\n{result.stderr}\n"
    return out


def main():
    out_path = Path("studies/1m_mtf_context/results/report.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# MTF Context Collector — Full Analysis Report\n")
    lines.append(f"\nGenerated from `studies/1m_mtf_context/analysis/*.py`\n\n")

    for title, script in ANALYSES:
        print(f"[report] Running {script}...", flush=True)
        output = run_script(script)
        lines.append(f"\n## Analysis {title}\n\n```\n{output}\n```\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[report] Saved: {out_path}")


if __name__ == "__main__":
    main()
