"""``research`` -- the single operator CLI over the governed platform.

Every command prints one compact JSON card on stdout; verbose output goes to disk.

    research data manifest <dataset_id> [--catalog <dir>]   write <catalog>/dataset_manifest.json, print digest
    research data verify <dataset_id>                        resolve through configured roots and verify digest
    research data roots                                      show the machine-local root configuration
    research cap list [kind] | describe <id> | search <text>  generated capability registry (zero tokens)
    research cap propose <yaml> | scaffold <id> | promote <id> --parity <json>   capability addition flow
    research study new <id> [--from-question <file>]         branch + sibling worktree + lease + v2 skeleton
    research study compile --study <dir>                     static compile -> compiled_plan.json | typed CapabilityGap
    research study status --study <dir>                      non-mutating controller state card
    research study run --study <dir> --through <stage> ...   the governed controller (v1 or v2 by grammar)
    research audit ingest --study <dir> --type causal|contract --report <md> [--author <id>]
    research bench [--series host_c,host_a,golden]           host performance measurement vs bench/baseline_v0.json
    research ws list [--reclaim]                             branches, worktrees, owners, leases (live/stale/dead/released), dirty state
    research ws release <study_id>                            explicitly release a writer lease you own
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _card(payload: dict, *, ok: bool = True) -> int:
    print(json.dumps({"STATUS": "OK" if ok else "FAIL", **payload}, indent=None, sort_keys=True, default=str))
    return 0 if ok else 2


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def cmd_data_roots(_: argparse.Namespace) -> int:
    from research_workflow.roots import load_config
    return _card({"roots": load_config().as_dict()})


def cmd_data_manifest(ns: argparse.Namespace) -> int:
    from research_workflow.roots import committed_dataset_spec_path, load_config, write_dataset_manifest
    import yaml
    spec_path = committed_dataset_spec_path(ns.dataset_id, ROOT)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) if spec_path.is_file() else {}
    if ns.catalog:
        catalog = Path(ns.catalog).resolve()
    else:
        cfg = load_config()
        candidates = [r / ns.dataset_id for r in cfg.catalog_roots if (r / ns.dataset_id).is_dir()]
        catalog = candidates[0] if candidates else (ROOT / str(spec.get("catalog_rel_path", f"data/catalog/{ns.dataset_id}"))).resolve()
    manifest = write_dataset_manifest(catalog, ns.dataset_id, spec.get("instrument_id"))
    committed = spec.get("logical_digest")
    return _card({"dataset_id": ns.dataset_id, "catalog": str(catalog), "logical_digest": manifest["logical_digest"],
                  "file_count": manifest["file_count"], "total_bytes": manifest["total_bytes"],
                  "committed_digest": committed, "matches_committed": (committed == manifest["logical_digest"]) if committed else None,
                  "next": None if committed == manifest["logical_digest"] else f"set logical_digest in {spec_path.relative_to(ROOT).as_posix()} and commit"})


def cmd_data_verify(ns: argparse.Namespace) -> int:
    from research_workflow.roots import compute_catalog_digest, resolve_dataset
    try:
        r = resolve_dataset(ns.dataset_id, ROOT)
    except Exception as exc:
        return _card({"dataset_id": ns.dataset_id, "error": f"{type(exc).__name__}: {exc}"}, ok=False)
    payload = {"dataset_id": r.dataset_id, "resolution": r.resolution, "logical_digest": r.logical_digest}
    if ns.recompute:
        actual = compute_catalog_digest(r.catalog_path)["logical_digest"]
        payload.update({"recomputed_digest": actual, "bytes_match_manifest": actual == r.logical_digest})
        return _card(payload, ok=actual == r.logical_digest)
    return _card(payload)


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------

def cmd_cap(ns: argparse.Namespace) -> int:
    if ns.cmd in ("propose", "scaffold", "promote"):
        from research_workflow.capability_flow import CapabilityFlowError, promote, propose, scaffold
        try:
            if ns.cmd == "propose":
                out = propose(Path(ns.proposal))
            elif ns.cmd == "scaffold":
                out = scaffold(ns.capability_id)
            else:
                out = promote(ns.capability_id, parity_artifact=Path(ns.parity) if ns.parity else None, run_tests=not ns.no_tests)
        except CapabilityFlowError as exc:
            return _card({"error": str(exc)}, ok=False)
        status = out.pop("STATUS", "OK")
        return _card({"flow": status, **out}, ok=status in {"PROPOSED", "SCAFFOLDED", "PROMOTED"})
    from research_workflow.capabilities import cli as cap_cli
    return cap_cli(ns)


# ---------------------------------------------------------------------------
# studies
# ---------------------------------------------------------------------------

def cmd_study_new(ns: argparse.Namespace) -> int:
    from research_workflow.workspace import study_new
    return _card(study_new(ns.study_id, repo_root=ROOT, question_file=ns.from_question, dataset_id=ns.dataset))


def cmd_study_compile(ns: argparse.Namespace) -> int:
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.lifecycle_v2 import is_v2_study
    from research_workflow.policy import OLD_RUNTIME_POLICY
    study = Path(ns.study).resolve()
    if not is_v2_study(study):
        return _card({"study": str(study), "blocker_code": "OLD_RUNTIME_LEGACY_ONLY", "policy": OLD_RUNTIME_POLICY,
                      "error": "not a Platform V2 study.yaml (v1 grammar); new research must use the v2 grammar -- see WORKFLOW.md and docs/RESEARCH_YAML_REFERENCE.md"}, ok=False)
    out = compile_study(load_spec(study), repo_root=ROOT)
    if not out.ok:
        return _card({"study": str(study), **out.gaps.to_dict()}, ok=False)
    if not ns.dry_run:
        out.plan.write(study / "compiled_plan.json")
    return _card({"study": str(study), **out.plan.card(), "written": not ns.dry_run})


def cmd_study_status(ns: argparse.Namespace) -> int:
    from research_workflow.governed_controller import compact_card
    from research_workflow.governed_controller_v2 import controller_for
    card = controller_for(ns.study).run(through="close", inspect=True)
    print(compact_card(card, as_json=True))
    return 0


def cmd_study_run(ns: argparse.Namespace, extra: list[str]) -> int:
    cmd = [sys.executable, str(ROOT / "scripts" / "run_governed_study.py"), *extra]
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def cmd_audit_ingest(ns: argparse.Namespace) -> int:
    from research_workflow.lifecycle_v2 import LifecycleV2Error, ingest_audit_report, is_v2_study
    study = Path(ns.study).resolve()
    if not is_v2_study(study):
        return _card({"error": "v1 studies ingest through scripts/run_preexec_audits.py --ingest"}, ok=False)
    try:
        out = ingest_audit_report(study, ns.type, Path(ns.report), ns.author)
    except Exception as exc:
        return _card({"error": f"{type(exc).__name__}: {exc}"}, ok=False)
    status = out.pop("STATUS")
    return _card({"ingest": status, **out}, ok=status == "OK")


def cmd_bench(ns: argparse.Namespace) -> int:
    cmd = [sys.executable, str(ROOT / "scripts" / "bench_host.py"), "--series", ns.series, "--repeats", str(ns.repeats)]
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def cmd_ws_list(ns: argparse.Namespace) -> int:
    from research_workflow.workspace import ws_list
    return _card(ws_list(repo_root=ROOT, reclaim=bool(getattr(ns, "reclaim", False))))


def cmd_ws_release(ns: argparse.Namespace) -> int:
    from research_workflow.workspace import current_owner, release_lease
    return _card(release_lease(ns.study_id, owner=current_owner()))


# ---------------------------------------------------------------------------
# model store
# ---------------------------------------------------------------------------

def cmd_model_list(_: argparse.Namespace) -> int:
    from research_workflow.model_store import list_store
    rows = list_store()
    return _card({"count": len(rows), "by_tier": {t: sum(1 for r in rows if r["tier"] == t) for t in ("registry", "ledger")}, "models": rows[:50]})


def cmd_model_validate(ns: argparse.Namespace) -> int:
    from research_workflow.model_store import validate_golden
    try:
        return _card(validate_golden(ns.model_id))
    except Exception as exc:
        return _card({"model_id": ns.model_id, "error": f"{type(exc).__name__}: {exc}"}, ok=False)


def cmd_model_export(ns: argparse.Namespace) -> int:
    from research_workflow.model_store import add_export
    rec = add_export(ns.model_id, ns.format)
    return _card({"model_id": ns.model_id, "export": {k: rec.get(k) for k in ("format", "status", "byte_sha256", "error")}, "equivalence": rec.get("equivalence")}, ok=rec.get("status") == "verified")


def cmd_model_migrate(ns: argparse.Namespace) -> int:
    import pandas as pd
    from research_workflow.model_migration import migrate_legacy_records, selected_configs_from_phase_d_report
    study_dir = ROOT / "studies" / ns.study
    report_path = study_dir / "artifacts" / "phase_d" / "phase_d_modeling_report.json"
    selected = selected_configs_from_phase_d_report(report_path) if report_path.is_file() else {}
    frame = pd.read_parquet(ns.train_frame) if ns.train_frame else None
    report = migrate_legacy_records(study_id=ns.study, registry_root=ROOT / "studies" / "model_registry", bytes_root=Path(ns.bytes_root) / "studies",
                                    train_frame=frame, selected=selected, exports=tuple(ns.export or ()), limit=ns.limit)
    out = study_dir / "artifacts" / "model_store_migration.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return _card({"report": str(out), **{k: report[k] for k in ("records", "migrated", "already_present", "tiers", "exports")}, "failed": len(report["failed"]), "first_failures": report["failed"][:3]}, ok=not report["failed"])


def build_parser() -> argparse.ArgumentParser:
    """The full CLI parser (importable for documentation tests)."""
    ap = argparse.ArgumentParser(prog="research", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="group", required=True)

    data = sub.add_parser("data").add_subparsers(dest="cmd", required=True)
    data.add_parser("roots").set_defaults(fn=cmd_data_roots)
    m = data.add_parser("manifest"); m.add_argument("dataset_id"); m.add_argument("--catalog"); m.set_defaults(fn=cmd_data_manifest)
    v = data.add_parser("verify"); v.add_argument("dataset_id"); v.add_argument("--recompute", action="store_true"); v.set_defaults(fn=cmd_data_verify)

    cap = sub.add_parser("cap").add_subparsers(dest="cmd", required=True)
    c = cap.add_parser("list"); c.add_argument("kind", nargs="?"); c.add_argument("--status"); c.set_defaults(fn=cmd_cap)
    c = cap.add_parser("describe"); c.add_argument("capability_id"); c.set_defaults(fn=cmd_cap)
    c = cap.add_parser("search"); c.add_argument("text"); c.set_defaults(fn=cmd_cap)
    c = cap.add_parser("generate"); c.add_argument("--check", action="store_true"); c.set_defaults(fn=cmd_cap)
    c = cap.add_parser("propose"); c.add_argument("proposal"); c.set_defaults(fn=cmd_cap)
    c = cap.add_parser("scaffold"); c.add_argument("capability_id"); c.set_defaults(fn=cmd_cap)
    c = cap.add_parser("promote"); c.add_argument("capability_id"); c.add_argument("--parity"); c.add_argument("--no-tests", action="store_true"); c.set_defaults(fn=cmd_cap)

    study = sub.add_parser("study").add_subparsers(dest="cmd", required=True)
    n = study.add_parser("new"); n.add_argument("study_id"); n.add_argument("--from-question"); n.add_argument("--dataset", default="NQ_v0_2020_2026"); n.set_defaults(fn=cmd_study_new)
    sc = study.add_parser("compile"); sc.add_argument("--study", required=True); sc.add_argument("--dry-run", action="store_true"); sc.set_defaults(fn=cmd_study_compile)
    ss = study.add_parser("status"); ss.add_argument("--study", required=True); ss.set_defaults(fn=cmd_study_status)
    r = study.add_parser("run"); r.set_defaults(fn=cmd_study_run, passthrough=True)

    audit = sub.add_parser("audit").add_subparsers(dest="cmd", required=True)
    ai = audit.add_parser("ingest"); ai.add_argument("--study", required=True); ai.add_argument("--type", required=True, choices=["causal", "contract"])
    ai.add_argument("--report", required=True); ai.add_argument("--author"); ai.set_defaults(fn=cmd_audit_ingest)

    b = sub.add_parser("bench"); b.add_argument("--series", default="host_c,host_a,golden"); b.add_argument("--repeats", type=int, default=3); b.set_defaults(fn=cmd_bench)

    model = sub.add_parser("model").add_subparsers(dest="cmd", required=True)
    model.add_parser("list").set_defaults(fn=cmd_model_list)
    mv = model.add_parser("validate"); mv.add_argument("model_id"); mv.set_defaults(fn=cmd_model_validate)
    me = model.add_parser("export"); me.add_argument("model_id"); me.add_argument("--format", default="joblib"); me.set_defaults(fn=cmd_model_export)
    mm = model.add_parser("migrate"); mm.add_argument("--study", required=True); mm.add_argument("--bytes-root", required=True, help="repo/worktree root holding studies/<id>/artifacts/models bytes")
    mm.add_argument("--train-frame", help="parquet of TRAIN rows for real-row golden frames"); mm.add_argument("--export", action="append"); mm.add_argument("--limit", type=int); mm.set_defaults(fn=cmd_model_migrate)

    ws = sub.add_parser("ws").add_subparsers(dest="cmd", required=True)
    wl = ws.add_parser("list"); wl.add_argument("--reclaim", action="store_true", help="delete stale/dead/released writer leases; live leases are never touched")
    wl.set_defaults(fn=cmd_ws_list)
    wr = ws.add_parser("release"); wr.add_argument("study_id"); wr.set_defaults(fn=cmd_ws_release)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    ns, extra = ap.parse_known_args(argv)
    if getattr(ns, "passthrough", False):
        return ns.fn(ns, extra)
    if extra:
        ap.error(f"unrecognized arguments: {extra}")
    return ns.fn(ns)


if __name__ == "__main__":
    raise SystemExit(main())
