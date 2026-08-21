#!/usr/bin/env python3
"""Describe Study Diff CLI Tool.
=============================
Performs semantic contract comparison between two studies and outputs
a high-signal comparison card instead of low-level line diffs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import yaml

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from research.schemas.study_spec import StudySpec


def load_spec(path_str: str) -> StudySpec:
    p = Path(path_str)
    if p.is_dir():
        yaml_path = p / "study.yaml"
    else:
        yaml_path = p

    if not yaml_path.exists():
        raise FileNotFoundError(f"study.yaml not found at: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return StudySpec.model_validate(data)


def describe_diff(spec_a: StudySpec, spec_b: StudySpec) -> str:
    diffs = []

    # 1. Study Metadata
    if spec_a.study.type != spec_b.study.type:
        diffs.append(f"  Type: {spec_a.study.type} -> {spec_b.study.type}")
    if spec_a.study.risk_tier != spec_b.study.risk_tier:
        diffs.append(f"  Risk Tier: {spec_a.study.risk_tier} -> {spec_b.study.risk_tier}")

    # 2. Population
    pop_a, pop_b = spec_a.population, spec_b.population
    if pop_a.prevailing_regime != pop_b.prevailing_regime:
        diffs.append(f"  Prevailing Regime: {pop_a.prevailing_regime} -> {pop_b.prevailing_regime}")
    if pop_a.session != pop_b.session:
        diffs.append(f"  Session: {pop_a.session} -> {pop_b.session}")
    if pop_a.qualification != pop_b.qualification:
        diffs.append(f"  Qualification: {pop_a.qualification} -> {pop_b.qualification}")

    # 3. Target
    t_a, t_b = spec_a.target, spec_b.target
    if t_a.direction != t_b.direction:
        diffs.append(f"  Target Direction: {t_a.direction} -> {t_b.direction}")
    if t_a.horizon_seconds != t_b.horizon_seconds:
        diffs.append(f"  Target Horizon: {t_a.horizon_seconds}s -> {t_b.horizon_seconds}s")

    # 4. Features
    f_a, f_b = spec_a.features, spec_b.features
    feats_a = set(f_a.feature_list or []) if f_a else set()
    feats_b = set(f_b.feature_list or []) if f_b else set()
    if f_a and f_b and f_a.source_key != f_b.source_key:
        diffs.append(f"  Feature Source Key: {f_a.source_key} -> {f_b.source_key}")
    if len(feats_a) != len(feats_b):
        diffs.append(f"  Feature Count: {len(feats_a)} -> {len(feats_b)}")
    added_feats = feats_b - feats_a
    removed_feats = feats_a - feats_b
    if added_feats:
        diffs.append(f"  Added Features ({len(added_feats)}): {sorted(list(added_feats))[:5]}")
    if removed_feats:
        diffs.append(f"  Removed Features ({len(removed_feats)}): {sorted(list(removed_feats))[:5]}")

    # 5. Model
    m_a, m_b = spec_a.model, spec_b.model
    if m_a and m_b:
        if m_a.family != m_b.family:
            diffs.append(f"  Model Family: {m_a.family} -> {m_b.family}")
        if m_a.artifact_path != m_b.artifact_path:
            diffs.append(f"  Model Artifact: {m_a.artifact_path} -> {m_b.artifact_path}")

    # 6. Chronology
    c_a, c_b = spec_a.chronology, spec_b.chronology
    if c_a and c_b:
        if c_a.train != c_b.train:
            diffs.append(f"  Train Chronology: {c_a.train} -> {c_b.train}")
        if c_a.dev != c_b.dev:
            diffs.append(f"  Dev Chronology: {c_a.dev} -> {c_b.dev}")
        if c_a.prohibited != c_b.prohibited:
            diffs.append(f"  Prohibited Chronology: {c_a.prohibited} -> {c_b.prohibited}")

    # 7. Execution
    if spec_a.execution.strategy_class != spec_b.execution.strategy_class:
        diffs.append(f"  Strategy Class: {spec_a.execution.strategy_class} -> {spec_b.execution.strategy_class}")

    lines = [
        "=" * 70,
        f"SEMANTIC STUDY DIFF: '{spec_a.study.id}' vs '{spec_b.study.id}'",
        "=" * 70,
    ]
    if not diffs:
        lines.append("  [IDENTICAL CONTRACTS] No semantic differences found.")
    else:
        lines.extend(diffs)
    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Describe semantic diff between two studies")
    parser.add_argument("study_a", type=str, help="First study directory or study.yaml")
    parser.add_argument("study_b", type=str, help="Second study directory or study.yaml")
    args = parser.parse_args()

    try:
        spec_a = load_spec(args.study_a)
        spec_b = load_spec(args.study_b)
        print(describe_diff(spec_a, spec_b))
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
