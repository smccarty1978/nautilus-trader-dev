"""Shared fixture: build a tmp V2 study from fixtures/golden/study_barrier.yaml."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
GOLDEN = ROOT / "fixtures" / "golden"


def build_study(tmp: Path, sid: str = "adv_v2_flow") -> Path:
    study = Path(tmp) / "studies" / sid
    study.mkdir(parents=True, exist_ok=True)
    spec = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")
    spec = spec.replace("id: golden_barrier", f"id: {sid}")
    spec = spec.replace(
        "chronology: {train: [2030], dev: [], prohibited: []}",
        "chronology: {train: [2029, 2030], dev: [2031], prohibited: [2032], authorized_dates: ['2030-01-01']}")
    spec = spec.replace(
        "model: none",
        "model:\n  family: lightgbm\n  params: {n_estimators: 20, max_depth: 2, num_leaves: 4, learning_rate: 0.1, verbosity: -1}\n"
        "  validation: {protocol: model_selection.random, tuning_years: [2029, 2030], final_train_validation_years: []}")
    (study / "study.yaml").write_text(spec, encoding="utf-8")
    return study


def lifecycle(study: Path, *, execute: bool = False):
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    import json
    bars_json = GOLDEN / "bars.json"
    if not bars_json.is_file():
        import subprocess
        subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads(bars_json.read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    NS = 1_000_000_000
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=execute, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets",
                     extra_bindings=SYNTHETIC_BINDINGS, bar_source=lambda s, e: bars,
                     session_table_spec=session, in_process_partitions=True,
                     closure={"outcome": "SYNTHETIC_FLOW_COMPLETE", "terminal_decision": "PLATFORM_V2_FLOW_PROVEN"})
    return V2Lifecycle(study, repo_root=ROOT, options=opts)
