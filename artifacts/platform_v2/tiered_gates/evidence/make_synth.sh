#!/usr/bin/env bash
# Synthetic ADDITIVE_CAPABILITY fixtures on a disposable worktree (tmp/*), one commit each, plus a batch.
set -e
ROOT="/c/Users/Scott McCarty/Projects/Nautilus Trader"
WT="/c/Users/Scott McCarty/Projects/Nautilus Trader-tiered_synth"
S="/c/Users/SCOTTM~1/AppData/Local/Temp/claude/C--Users-Scott-McCarty-Projects-Nautilus-Trader/eeea52b1-dd42-4df6-bc88-7900595bed85/scratchpad"
BASE=68e0722a
export PYTHONIOENCODING=utf-8
cd "$ROOT"
[ -d "$WT" ] || git worktree add "$WT" -b tmp/tiered_synth $BASE >/dev/null 2>&1
cd "$WT"
git checkout -q -B tmp/synthA $BASE

# ---------------- Fixture A: new tracker through the sanctioned flow + TRACKER_BINDINGS insertion
cat > "$S/proposal_A.yaml" <<'EOF'
kind: tracker
name: tracker.synth.bar_count
semantics: |
  Synthetic fixture for the tiered-gate proof: counts completed source bars since the last regime flip.
availability_rule: value at T reflects bars with ts_init <= T only
parameters:
  window: 20
serves_studies: [synth_study_one, synth_study_two]
closest_existing:
  id: tracker.regime.excursion
  why_not: it tracks price excursion, not a bar count
composition_attempted:
  spec_fragment: "features: [{feature: bar_count, window: 20}]"
  compiler_gap: "MISSING_CAPABILITY: no feature identity bar_count"
reset_policy: event_start
null_policy: allow
gap_policy: carry
inputs: {bars: stream}
fields: [count]
events: []
update_cadence: per_source_bar
EOF
python scripts/research.py cap propose "$S/proposal_A.yaml" | tail -c 300; echo
python scripts/research.py cap scaffold tracker.synth.bar_count | tail -c 400; echo
python - <<'EOF'
from pathlib import Path
p = Path("features/trackers/host_bindings.py"); s = p.read_text(encoding="utf-8")
s = s.replace("TRACKER_BINDINGS: Dict[str, type] = {", "from features.trackers.synth_bar_count import SynthBarCountBinding\n\nTRACKER_BINDINGS: Dict[str, type] = {", 1)
s = s.replace("    FrozenExternalScoreBinding.CAPABILITY: FrozenExternalScoreBinding,\n}", "    FrozenExternalScoreBinding.CAPABILITY: FrozenExternalScoreBinding,\n    SynthBarCountBinding.CAPABILITY: SynthBarCountBinding,\n}", 1)
p.write_text(s, encoding="utf-8")
# make the scaffold importable at runtime (the template raises NotImplementedError only when called)
EOF
python scripts/research.py cap generate | tail -c 200; echo
git add features/trackers/synth_bar_count.py features/tests/test_synth_bar_count.py features/trackers/host_bindings.py \
        research_workflow/capabilities_index.yaml research_workflow/capabilities/registry.json research_workflow/capabilities/proposals/tracker.synth.bar_count.yaml
git commit -q -m "synth A: new tracker via cap propose/scaffold + TRACKER_BINDINGS insertion"
echo "A=$(git rev-parse --short HEAD)"

# ---------------- Fixture B: new feature definition (existing provider) = one _add(...) in features/registry.py
git checkout -q -B tmp/synthB $BASE
python - <<'EOF'
from pathlib import Path
p = Path("features/registry.py"); s = p.read_text(encoding="utf-8")
s = s.replace("del _n, _w, _m, _lvl, _suffix, _band\n",
 "# synthetic fixture: a new rolling window metric served by the existing OHLCV/delta provider\n_add('synth_vol_sum_45s', 'ohlcv_est_delta', 'rolling_window', _OHLCV_DELTA_IMPL, _OHLCV_TESTS,\n    null_policy='allow', window=45, window_unit='seconds', reset_policy='none')\n\ndel _n, _w, _m, _lvl, _suffix, _band\n", 1)
p.write_text(s, encoding="utf-8")
EOF
python scripts/research.py cap generate | tail -c 200; echo
git add features/registry.py research_workflow/capabilities/registry.json
git commit -q -m "synth B: new feature definition (_add) served by an existing provider"
echo "B=$(git rev-parse --short HEAD)"

# ---------------- Fixture B2: new provider family = new tracker module + adapter ClassDef + ADAPTER_REGISTRY insertion + _add
git checkout -q -B tmp/synthB2 $BASE
cat > features/trackers/generic_synth_pressure.py <<'EOF'
"""Synthetic fixture provider for the tiered-gate proof (not a real feature)."""
from __future__ import annotations


class GenericSynthPressureProvider:
    canonical_provider = "features.trackers.generic_synth_pressure.GenericSynthPressureProvider"

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = int(window_seconds)
        self._last = None

    def on_completed_1s(self, ts: int, high: float, low: float, close: float) -> None:
        self._last = (ts, close)

    def snapshot(self, decision_ts: int) -> dict:
        return {"synth_pressure": (self._last[1] if self._last else None)}
EOF
python - <<'EOF'
from pathlib import Path
p = Path("research_workflow/provider_host.py"); s = p.read_text(encoding="utf-8")
cls = '''

class SynthPressureAdapter(RuntimeProviderAdapter):
    """Synthetic fixture adapter (tiered-gate proof)."""
    canonical_provider = "features.trackers.generic_synth_pressure.GenericSynthPressureProvider"

    def __init__(self, instances):
        from features.trackers.generic_synth_pressure import GenericSynthPressureProvider
        self.instances = list(instances)
        self._provider = GenericSynthPressureProvider()

    def on_event(self, event_type, event, episode_state=None):
        if event_type == STREAM_COMPLETED_1S:
            self._provider.on_completed_1s(int(event["ts_init"]), float(event["high"]), float(event["low"]), float(event["close"]))

    def snapshot(self, decision_ts, episode_state, atr):
        snap = self._provider.snapshot(int(decision_ts))
        return {inst.physical_alias: snap.get("synth_pressure") for inst in self.instances}

'''
s = s.replace("\n# canonical provider class path -> adapter factory.", cls + "\n# canonical provider class path -> adapter factory.", 1)
s = s.replace("    OHLCVDeltaAdapter.canonical_provider: OHLCVDeltaAdapter,\n}", "    OHLCVDeltaAdapter.canonical_provider: OHLCVDeltaAdapter,\n    SynthPressureAdapter.canonical_provider: SynthPressureAdapter,\n}", 1)
p.write_text(s, encoding="utf-8")
p = Path("features/registry.py"); s = p.read_text(encoding="utf-8")
s = s.replace("del _n, _w, _m, _lvl, _suffix, _band\n",
 "_add('synth_pressure', 'synth_pressure', 'scalar', 'features.trackers.generic_synth_pressure.GenericSynthPressureProvider', ('features/tests/test_generic_synth_pressure.py',),\n    null_policy='allow', reset_policy='none')\n\ndel _n, _w, _m, _lvl, _suffix, _band\n", 1)
p.write_text(s, encoding="utf-8")
Path("features/tests/test_generic_synth_pressure.py").write_text('from features.trackers.generic_synth_pressure import GenericSynthPressureProvider\n\n\ndef test_snapshot_is_last_close():\n    p = GenericSynthPressureProvider()\n    p.on_completed_1s(1, 2.0, 1.0, 1.5)\n    assert p.snapshot(1)["synth_pressure"] == 1.5\n', encoding="utf-8")
EOF
python scripts/research.py cap generate | tail -c 200; echo
git add features/trackers/generic_synth_pressure.py features/tests/test_generic_synth_pressure.py features/registry.py research_workflow/provider_host.py research_workflow/capabilities/registry.json
git commit -q -m "synth B2: new provider family (module + adapter ClassDef + ADAPTER_REGISTRY insertion + _add)"
echo "B2=$(git rev-parse --short HEAD)"

# ---------------- Fixture C: new analysis op = new function + OPS/OP_INPUTS insertion
git checkout -q -B tmp/synthC $BASE
python - <<'EOF'
from pathlib import Path
p = Path("research/analysis/diagnostic_ops.py"); s = p.read_text(encoding="utf-8")
fn = '''

def synth_row_count(rows: pd.DataFrame, *, inputs=None, params=None, context=None) -> Dict[str, Any]:
    """Synthetic fixture op (tiered-gate proof): payload carries the row count."""
    return {"frame": rows, "payload": {"rows": int(len(rows))}}

'''
s = s.replace("\n# --------------------------------------------------------------------------- #\n# registry\n", fn + "\n# --------------------------------------------------------------------------- #\n# registry\n", 1)
s = s.replace('    "analysis.gate.arm_delta_integrity": arm_delta_integrity_gate,\n}', '    "analysis.gate.arm_delta_integrity": arm_delta_integrity_gate,\n    "analysis.synth.row_count": synth_row_count,\n}', 1)
s = s.replace('    "analysis.gate.arm_delta_integrity": (),\n}', '    "analysis.gate.arm_delta_integrity": (),\n    "analysis.synth.row_count": (),\n}', 1)
p.write_text(s, encoding="utf-8")
EOF
python scripts/research.py cap generate | tail -c 200; echo
git add research/analysis/diagnostic_ops.py research_workflow/capabilities/registry.json
git commit -q -m "synth C: new analysis op (function + OPS/OP_INPUTS insertion)"
echo "C=$(git rev-parse --short HEAD)"

# ---------------- Batch: A + B + B2 + C merged as one candidate (registry.json regenerated after the merge)
git checkout -q -B tmp/synthBatch tmp/synthA
for b in tmp/synthB tmp/synthB2 tmp/synthC; do
  git merge --no-ff -q -m "batch: $b" $b || { git checkout --theirs research_workflow/capabilities/registry.json 2>/dev/null; git checkout --theirs features/registry.py 2>/dev/null; git add research_workflow/capabilities/registry.json features/registry.py; git -c core.editor=true merge --continue; }
done
python scripts/research.py cap generate | tail -c 120; echo
git add research_workflow/capabilities/registry.json; git commit -q -m "batch: regenerate registry" || true
echo "BATCH=$(git rev-parse --short HEAD)"
python scripts/research.py cap generate --check | tail -c 150; echo
git log --oneline $BASE..HEAD | head
