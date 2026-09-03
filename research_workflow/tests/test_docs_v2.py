"""Documentation checks: the operator manuals cannot silently drift from the platform.

* every documented `python scripts/research.py ...` example parses against the real CLI parser;
* every documented `scripts/run_governed_study.py` flag exists;
* docs/examples/*.yaml compile (the registry-blind draft must return typed gaps);
* every canonical path in WORKFLOW.md's repository map exists;
* capability ids used in the examples are registered;
* the generated YAML reference and the capability registry are current;
* no manual tells a new study to use the legacy runtime or a historical study as a template.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

MANUALS = ["WORKFLOW.md", "docs/QUICKSTART.md", "docs/AI_AGENTS.md", "docs/RESEARCH_DISCUSSION_TO_YAML.md", "GEMINI.md", "README.md"]
EXAMPLES = ["checkpoint_classifier", "watch_trigger", "multi_arm_outcome", "ml_tuning"]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _cli_lines():
    for rel in MANUALS:
        for line in _text(rel).splitlines():
            s = line.strip()
            if s.startswith("nohup "):
                s = s[len("nohup "):]
            if s.startswith("python scripts/research.py ") or s.startswith("python -u scripts/research.py ") or s.startswith("python scripts/run_governed_study.py ") or s.startswith("python -u scripts/run_governed_study.py "):
                yield rel, s


def test_manuals_exist_and_point_to_workflow_first():
    for rel in MANUALS:
        assert (ROOT / rel).is_file(), rel
    assert "Read `WORKFLOW.md` first" in _text("AGENTS.md") or "Read WORKFLOW.md first" in _text("AGENTS.md")
    assert "WORKFLOW.md" in _text("CLAUDE.md") and "WORKFLOW.md" in _text("CODEX.md") and "WORKFLOW.md" in _text("GEMINI.md")
    assert 100 < len(_text("WORKFLOW.md").splitlines()) < 2000
    assert len(_text("docs/QUICKSTART.md").splitlines()) <= 250


def test_documented_research_cli_examples_parse():
    import importlib.util
    spec = importlib.util.spec_from_file_location("research_cli_for_docs", ROOT / "scripts" / "research.py")
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    parser = cli.build_parser()
    checked = 0
    for rel, line in _cli_lines():
        if "research.py" not in line:
            continue
        cmd = line.split("#", 1)[0].split("|", 1)[0].split("&&", 1)[0].split(">", 1)[0].strip()
        if "<" in cmd:
            continue                     # illustrative placeholder
        argv = shlex.split(cmd)[2:]
        if argv and argv[0] == "study" and argv[1] == "run":
            continue                     # pass-through to run_governed_study
        ns, extra = parser.parse_known_args(argv)
        assert not extra, (rel, line, extra)
        checked += 1
    assert checked >= 15


def test_documented_run_governed_study_flags_exist():
    src = _text("scripts/run_governed_study.py")
    flags = set(re.findall(r'"(--[a-z][a-z0-9-]*)"', src))
    checked = 0
    for rel, line in _cli_lines():
        if "run_governed_study.py" not in line:
            continue
        for flag in re.findall(r"(--[a-z][a-z0-9-]*)", line):
            assert flag in flags, (rel, flag)
            checked += 1
    assert checked >= 10


def test_examples_compile_and_registry_blind_draft_returns_typed_gaps():
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.grammar.gaps import GapKind
    for name in EXAMPLES:
        out = compile_study(load_spec(ROOT / "docs" / "examples" / f"{name}.yaml"), repo_root=ROOT)
        assert out.ok, (name, out.card())
        assert out.plan.card()["catalog_opened"] is False
    out = compile_study(load_spec(ROOT / "docs" / "examples" / "registry_blind_draft.yaml"), repo_root=ROOT)
    assert not out.ok
    kinds = {g.kind for g in out.gaps.gaps}
    assert GapKind.MISSING_CAPABILITY in kinds
    assert any("unresolved" in (g.message or "") or "unresolved" in str(g.where) or g.kind == GapKind.MISSING_CAPABILITY for g in out.gaps.gaps)


def test_example_capability_ids_are_registered():
    import yaml
    reg = json.loads(_text("research_workflow/capabilities/registry.json"))
    trackers = {e["id"] for e in reg["kinds"]["trackers"]}
    features = {e["id"] for e in reg["kinds"]["features"]} | {a for e in reg["kinds"]["features"] for a in (e.get("aliases") or [])}
    feature_names = {i.split(".", 1)[-1] for i in features} | features
    datasets = {e["id"] for e in reg["kinds"]["datasets"]}
    for name in EXAMPLES:
        spec = yaml.safe_load((ROOT / "docs" / "examples" / f"{name}.yaml").read_text(encoding="utf-8"))
        for s in spec["streams"]:
            assert f"dataset.{s['dataset']}" in datasets, (name, s["dataset"])
        for ctx_name, ctx in (spec.get("context") or {}).items():
            assert f"tracker.{ctx['tracker']}" in trackers, (name, ctx_name, ctx["tracker"])
        for inst in (spec.get("features") or {}).get("instances") or []:
            assert inst["feature"] in feature_names, (name, inst["feature"])


def test_repository_map_paths_exist():
    text = _text("WORKFLOW.md")
    section = text.split("## C.", 1)[1].split("## D.", 1)[0]
    paths = set(re.findall(r"`([A-Za-z0-9_./-]+)`", section))
    top = {d.name for d in ROOT.iterdir()}
    missing, checked = [], 0
    for p in sorted(paths):
        if any(ch in p for ch in "<>*~{") or p.startswith(("..", "-")):
            continue
        q = p.rstrip("/")
        first = q.split("/", 1)[0]
        if first not in top:
            continue                      # shorthand relative to the row's canonical directory, not a repo path
        checked += 1
        if not (ROOT / q).exists():
            missing.append(q)
    assert checked >= 40 and not missing, (checked, missing)


def test_generated_reference_and_registry_are_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_yaml_reference.py"), "--check"], cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"), "cap", "generate", "--check"], cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0 and '"STATUS": "OK"' in r.stdout, r.stdout + r.stderr


def test_manuals_never_route_new_research_to_the_legacy_runtime():
    for rel in ("WORKFLOW.md", "docs/QUICKSTART.md", "docs/RESEARCH_DISCUSSION_TO_YAML.md", "GEMINI.md"):
        t = _text(rel)
        assert "strategy_class:" not in t and "type: flip_prediction" not in t and "GenericStudyCollector" not in t, rel
    assert "Historical studies are references, not templates" in _text("WORKFLOW.md")
    q = _text("docs/QUICKSTART.md")
    for hist in ("clean_maturity_flip_model", "deep_pullback_5s_reacceleration_model", "regime_transition_target_before_stop_v1"):
        assert hist not in q, hist
    assert "LEGACY_ONLY_FOR_NEW_RESEARCH" in _text("WORKFLOW.md")


def test_copy_paste_prompt_is_present_and_matches_the_template():
    doc = _text("docs/RESEARCH_DISCUSSION_TO_YAML.md")
    assert "## COPY THIS INTO ANY AI CHAT" in doc and "<!-- PROMPT_START -->" in doc
    tpl = _text("research_workflow/templates/research_discussion_to_yaml_prompt.md")
    for phrase in ("Do not invent scientific assumptions", "Do not invent repository capability IDs", "EXECUTIVE RESEARCH CONTRACT", "UNRESOLVED DECISIONS",
                   "PLATFORM V2 YAML", "CAPABILITIES NEEDED", "VALIDATION PLAN", "PROHIBITED / LOCKED DATA", "horizon_end_rule", "same_bar_rule", "unresolved:"):
        assert phrase in doc and phrase in tpl, phrase
