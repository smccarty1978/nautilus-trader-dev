"""Same as monthly_n20 but with N=40 features (next 20 added).

Tests whether features ranked 21-40 add information that's lost at
N=20 but harmful at N=90 (full).
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "n20",
    "studies/v_a_excursion_regime/ml_va_walkforward_bar1plus30s_monthly_n20.py")
n20 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n20)
n20.N_FEATURES = 40


if __name__ == "__main__":
    print(f"Override: N_FEATURES = {n20.N_FEATURES}")
    n20.main()
