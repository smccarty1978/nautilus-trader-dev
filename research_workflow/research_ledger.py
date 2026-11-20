"""Research ledger: immutable attempts, cross-study data exposure, computed claim level, result card (autonomous_explore).

One mechanism answers "what was tested, on which data, with which variants, and what did we see" ACROSS studies, so a
new study id can never make already-examined data look unseen.

Storage -- append-only, write-once event files (``O_CREAT|O_EXCL``; an existing event is never rewritten):

* machine ledger   ``<ledger_dir>/events/<event_id>.json``. ``ledger_dir`` = ``$NT_RESEARCH_LEDGER`` or
                   ``ledger_dir:`` in ``~/.nt_research/config.yaml`` or ``~/.nt_research/ledger`` (next to frames/leases).
* study mirror     ``studies/<id>/artifacts/ledger/<event_id>.json`` -- the same bytes, committed with the study, so
                   the history is in git on the study branch even if the machine directory is lost.
                   ``rebuild_from_mirrors`` re-imports mirrors (idempotent). BACKUP LIMITATION: the machine directory is
                   not itself backed up; it is recoverable only from committed study branches.

Events: ``exposure`` (written BEFORE the first outcome-bearing row of an attempt is produced: dataset, intervals,
outcome columns, scientific-definition sha, prior attempts visible in the family) and ``result`` (verdict, numbers,
computed claim level). The attempt identity is a hash of the scientific plan (which includes the code closure), the
dataset identity and the analysis identity; a changed analysis is a new attempt and never overwrites the old one.

Claim levels are evidence classifications, not profitability labels:
EXPLORATORY < HISTORICAL_REPLICATION / CHRONOLOGICAL_ROBUSTNESS < CONFIRMATORY < EXECUTION_VALIDATED.
CONFIRMATORY needs windows inside a researcher-declared RESERVED set, never exposed before, under a governed sealed
plan; EXECUTION_VALIDATED only comes from the execution-validation lane. Neither is reachable from tier: explore.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
LEDGER_ENV = "NT_RESEARCH_LEDGER"
CLAIM_LEVELS = ("EXPLORATORY", "HISTORICAL_REPLICATION", "CHRONOLOGICAL_ROBUSTNESS", "CONFIRMATORY", "EXECUTION_VALIDATED")
VERDICTS = ("SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE")
RECOMMENDATION = {"SUPPORTED": "ESCALATE_FOR_INDEPENDENT_REVIEW_THEN_CONFIRM", "UNSUPPORTED": "STOP", "INCONCLUSIVE": "REFINE"}


class LedgerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _config() -> Dict[str, Any]:
    from research_workflow.roots import config_path
    p = config_path()
    if p is None:
        return {}
    import yaml
    try:
        return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def ledger_dir() -> Path:
    env = os.environ.get(LEDGER_ENV)
    if env:
        return Path(env)
    cfg = _config()
    if cfg.get("ledger_dir"):
        return Path(os.path.expanduser(str(cfg["ledger_dir"])))
    from research_workflow.roots import DEFAULT_CONFIG_DIR
    return Path(DEFAULT_CONFIG_DIR) / "ledger"


def reserved_windows() -> List[Dict[str, str]]:
    """Researcher-declared RESERVED confirmation data: ``reserved_windows: [{dataset, start, end}]`` in the config.
    Nothing declared -> nothing is reserved -> CONFIRMATORY is unreachable (never assume data is untouched)."""
    return [dict(w) for w in (_config().get("reserved_windows") or []) if isinstance(w, Mapping)]


# --------------------------------------------------------------------------- identities
def _tracker_identity(t: Mapping[str, Any], closure_files: Mapping[str, str]) -> Dict[str, Any]:
    impl = str(t.get("implementation") or "")
    if impl.startswith("study_local:"):
        # a study-local observer is identified by its CODE, not by the study id embedded in its ref
        path = impl[len("study_local:"):].partition(":")[2].rpartition(":")[0]
        impl = f"study_local@{closure_files.get(path, path)}"
    return {"id": t.get("id"), "implementation": impl, "params": {k: v for k, v in (t.get("params") or {}).items() if k != "studies_root"},
            "inputs": t.get("inputs")}


def definition_sha256(plan: Mapping[str, Any]) -> str:
    """The SCIENTIFIC definition independent of study id, wording and chronology: candidate generation (streams,
    trackers incl. observer code, population, triggers), features/columns, outcome, analysis and decision rule. Two
    studies with equal definition_sha256 test the same thing; equal definitions on other data are replication."""
    files = (plan.get("closure") or {}).get("files") or {}
    body = {"streams": [{k: s.get(k) for k in ("instrument", "timeframe", "role", "derived_from", "aggregation")} for s in plan.get("streams") or []],
            "trackers": [_tracker_identity(t, files) for t in plan.get("trackers") or []],
            "population": plan.get("population"), "triggers": plan.get("triggers"), "outcome": plan.get("outcome"),
            "columns": plan.get("columns"), "features": plan.get("features"), "analysis": plan.get("analysis"),
            "result": (plan.get("explore") or {}).get("result"), "session": {k: (plan.get("session") or {}).get(k) for k in ("session", "kind")}}
    return _sha(body)


def plan_intervals(plan: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Dataset date intervals the plan reads for its TRAIN role (inclusive ISO dates), per dataset id."""
    ch = plan.get("chronology") or {}
    datasets = sorted({str(v.get("dataset_id")) for v in (plan.get("instruments") or {}).values() if v.get("dataset_id")}) or ["?"]
    spans: List[Tuple[str, str]] = []
    windows = [w for w in (ch.get("windows") or []) if isinstance(w, Mapping) and w.get("role", "train") == "train"]
    if windows:
        spans = [(str(w["start"]), str(w["end"])) for w in windows if w.get("start") and w.get("end")]
    elif ch.get("authorized_dates"):
        spans = [(str(d), str(d)) for d in ch["authorized_dates"]]
    else:
        spans = [(f"{int(y)}-01-01", f"{int(y)}-12-31") for y in ch.get("train") or []]
    return [{"dataset": d, "start": a, "end": b} for d in datasets for a, b in sorted(spans)]


def _overlap(a: Mapping[str, str], b: Mapping[str, str]) -> bool:
    return a.get("dataset") == b.get("dataset") and str(a["start"]) <= str(b["end"]) and str(b["start"]) <= str(a["end"])


def attempt_id(plan: Mapping[str, Any], dataset_digests: Mapping[str, Any], analysis_identity: Optional[str] = None) -> str:
    return _sha({"plan_sha256": plan.get("plan_sha256"), "datasets": dict(sorted(dataset_digests.items())),
                 "intervals": plan_intervals(plan), "analysis_identity": analysis_identity})[:24]


# --------------------------------------------------------------------------- storage
def _write_once(path: Path, body: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(body, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        if path.read_bytes() != data:
            raise LedgerError("LEDGER_EVENT_IMMUTABLE", f"{path.name} exists with different content; events are write-once")
        return False
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return True


def append(event: Mapping[str, Any], *, study: Optional[Path] = None) -> Dict[str, Any]:
    """Write one event (machine ledger + study mirror). The event id is the hash of its content without timestamps, so
    an identical deterministic re-run is recognised (``new: False``) instead of erasing or duplicating history."""
    body = {k: v for k, v in event.items() if k not in ("event_id", "recorded_at_utc")}
    eid = f"{body['kind']}_{_sha(body)[:20]}"
    existing = ledger_dir() / "events" / f"{eid}.json"
    full = json.loads(existing.read_text(encoding="utf-8")) if existing.is_file() else {**body, "event_id": eid, "recorded_at_utc": _now(),
                                                                                         "schema_version": SCHEMA_VERSION}
    new = _write_once(existing, full)
    if study is not None:
        _write_once(Path(study) / "artifacts" / "ledger" / f"{eid}.json", full)
    return {"event_id": eid, "new": new, "event": full}


def events(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    root = ledger_dir() / "events"
    out = []
    for p in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            e = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if kind is None or e.get("kind") == kind:
            out.append(e)
    return sorted(out, key=lambda e: (e.get("recorded_at_utc") or "", e.get("event_id") or ""))


def rebuild_from_mirrors(studies_root: Path) -> int:
    n = 0
    for p in sorted(Path(studies_root).glob("*/artifacts/ledger/*.json")):
        n += int(_write_once(ledger_dir() / "events" / p.name, json.loads(p.read_text(encoding="utf-8"))))
    return n


# --------------------------------------------------------------------------- exposure + claim
def prior_exposure(intervals: Sequence[Mapping[str, str]], *, exclude_attempt: Optional[str] = None) -> List[Dict[str, Any]]:
    hits = []
    for e in events("exposure"):
        if e.get("attempt_id") == exclude_attempt:
            continue
        for iv in e.get("intervals") or []:
            if any(_overlap(iv, mine) for mine in intervals):
                hits.append({"attempt_id": e.get("attempt_id"), "study_id": e.get("study_id"), "family": e.get("family"),
                             "definition_sha256": e.get("definition_sha256"), "interval": iv})
    return hits


def check_reserved(plan: Mapping[str, Any]) -> None:
    """S5: an exploratory plan may not read researcher-reserved confirmation data."""
    for iv in plan_intervals(plan):
        for r in reserved_windows():
            if _overlap(iv, r):
                raise LedgerError("RESERVED_DATA_REFUSED", f"{iv} overlaps reserved confirmation window {r}; tier: explore never reads it")


def record_exposure(study: Path, plan: Mapping[str, Any], dataset_digests: Mapping[str, Any]) -> Dict[str, Any]:
    """Written before collection produces any outcome-bearing row. Records the attempt and what was already visible."""
    check_reserved(plan)
    explore = plan.get("explore") or {}
    aid = attempt_id(plan, dataset_digests)
    intervals = plan_intervals(plan)
    family = explore.get("family")
    prior_family = sorted({e["attempt_id"] for e in events("exposure") if family and e.get("family") == family and e.get("attempt_id") != aid})
    prior = prior_exposure(intervals, exclude_attempt=aid)
    return append({"kind": "exposure", "attempt_id": aid, "study_id": (plan.get("study") or {}).get("id"), "family": family,
                   "tier": explore.get("tier", "governed"), "plan_sha256": plan.get("plan_sha256"),
                   "definition_sha256": definition_sha256(plan), "datasets": dict(dataset_digests), "intervals": intervals,
                   "outcome_columns": sorted(_label_columns(plan)), "outcome_sha256": _sha(plan.get("outcome")),
                   "prior_attempts_in_family": prior_family,
                   "prior_exposure_of_these_intervals": len(prior),
                   "pre_registered_rule_sha256": _sha(explore.get("result")) if explore.get("result") else None}, study=study)


def _label_columns(plan: Mapping[str, Any]) -> List[str]:
    o = plan.get("outcome") or {}
    cols = set(o.get("label_columns") or [])
    if o.get("label_column"):
        cols.add(o["label_column"])
    return list(cols)


def claim_level(plan: Mapping[str, Any], *, attempt: str, execution_validated: bool = False) -> Tuple[str, str]:
    """Computed, never declared. Returns (level, reason)."""
    if execution_validated:
        return "EXECUTION_VALIDATED", "live-NT execution validation evidence"
    tier = (plan.get("explore") or {}).get("tier", "governed")
    intervals = plan_intervals(plan)
    prior = prior_exposure(intervals, exclude_attempt=attempt)
    mine = definition_sha256(plan)
    earlier_same_def = [e for e in events("result") if e.get("definition_sha256") == mine and e.get("attempt_id") != attempt]
    if tier != "explore":
        reserved = reserved_windows()
        inside = all(any(_overlap(iv, r) and r["start"] <= iv["start"] and iv["end"] <= r["end"] for r in reserved) for iv in intervals)
        if reserved and inside and not prior:
            return "CONFIRMATORY", "reserved windows, never exposed before, governed sealed plan"
    if earlier_same_def:
        seen = [iv for e in earlier_same_def for iv in (e.get("intervals") or [])]
        if any(_overlap(a, b) for a in intervals for b in seen):
            return "HISTORICAL_REPLICATION", f"same scientific definition re-run on data it already saw ({len(earlier_same_def)} earlier result(s))"
        return "CHRONOLOGICAL_ROBUSTNESS", "same scientific definition on intervals it had not seen (previously examined by other work)" if prior \
            else "same scientific definition on intervals it had not seen"
    return "EXPLORATORY", (f"tier: {tier}; {len(prior)} prior exposure(s) of these intervals in the ledger" if prior
                           else f"tier: {tier}; no reserved data; new scientific definition")


# --------------------------------------------------------------------------- verdict + card
def evaluate(rule: Mapping[str, Any], artifacts_dir: Path) -> Dict[str, Any]:
    """Apply the PRE-REGISTERED rule to the declared clustered-difference artifact."""
    p = rule["primary"]
    path = Path(artifacts_dir) / p["artifact"]
    if not path.is_file():
        raise LedgerError("RESULT_ARTIFACT_MISSING", f"{p['artifact']} was not produced by the analysis")
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = _find_differences(doc)
    row = next((r for r in rows if r.get("name") == p["difference"] and (not p.get("column") or r.get("column") == p["column"])), None)
    if row is None:
        raise LedgerError("RESULT_DIFFERENCE_MISSING", f"no difference {p['difference']!r} in {p['artifact']}")
    est, lo, hi = row.get("estimate"), row.get("ci_low"), row.get("ci_high")
    ncl = int(row.get("n_clusters") or 0)
    sign = 1.0 if rule["expected_sign"] == "positive" else -1.0
    me = float(rule.get("min_effect") or 0.0)
    if est is None or lo is None or hi is None or ncl < int(rule.get("min_clusters", 20)):
        verdict, why = "INCONCLUSIVE", f"no interval or too few session clusters ({ncl} < {rule.get('min_clusters', 20)})"
    else:
        s_lo, s_hi = sorted((sign * lo, sign * hi))           # interval in the expected direction
        if s_lo > 0:
            verdict, why = "SUPPORTED", "CI excludes 0 in the expected direction"
        elif s_hi < 0:
            verdict, why = "UNSUPPORTED", "CI excludes 0 in the OPPOSITE direction"
        elif s_hi < me:
            verdict, why = "UNSUPPORTED", f"CI excludes the minimum meaningful effect {me}"
        else:
            verdict, why = "INCONCLUSIVE", "CI straddles 0 and admits the minimum meaningful effect"
    return {"verdict": verdict, "reason": why, "estimate": est, "ci_low": lo, "ci_high": hi, "n_clusters": ncl,
            "n_rows": row.get("n_rows"), "n_rows_a": row.get("n_rows_a"), "n_rows_b": row.get("n_rows_b"),
            "a": row.get("a"), "b": row.get("b"), "column": row.get("column"), "difference": p["difference"],
            "artifact": p["artifact"], "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _find_differences(doc: Any) -> List[Dict[str, Any]]:
    if isinstance(doc, Mapping):
        if isinstance(doc.get("differences"), list):
            return [d for d in doc["differences"] if isinstance(d, Mapping)]
        for v in doc.values():
            got = _find_differences(v)
            if got:
                return got
    return []


def write_result(study: Path, plan: Mapping[str, Any], *, dataset_digests: Mapping[str, Any], analysis_identity: Optional[str],
                 population: Mapping[str, Any], validation: Mapping[str, Any]) -> Dict[str, Any]:
    """artifacts/result.json + RESULT_CARD.md + one ledger `result` event. Called by the explore close."""
    study = Path(study)
    explore = plan.get("explore") or {}
    rule = explore["result"]
    exposure_aid = attempt_id(plan, dataset_digests)
    aid = attempt_id(plan, dataset_digests, analysis_identity)
    outcome = evaluate(rule, study / "artifacts")
    level, level_why = claim_level(plan, attempt=exposure_aid)
    intervals = plan_intervals(plan)
    record = {"schema_version": SCHEMA_VERSION, "kind": "explore_result", "study_id": (plan.get("study") or {}).get("id"),
              "attempt_id": aid, "exposure_attempt_id": exposure_aid, "family": explore.get("family"),
              "plan_sha256": plan.get("plan_sha256"), "definition_sha256": definition_sha256(plan),
              "execution_composite_sha256": (plan.get("closure") or {}).get("composite_sha256"),
              "analysis_identity_sha256": analysis_identity, "datasets": dict(dataset_digests), "intervals": intervals,
              "population": dict(population), "hypothesis": rule["hypothesis"], "control": rule["control"],
              "pre_registered_rule": rule, "result": outcome, "claim_level": level, "claim_reason": level_why,
              "validation": dict(validation), "recommendation": RECOMMENDATION[outcome["verdict"]],
              "isolation": "CLOSED_ISOLATED",
              "not_implied": ["shared-code promotion", "platform merge", "production readiness", "permission to trade"],
              "exposure_history": {"prior_attempts_in_family": sorted({e["attempt_id"] for e in events("exposure")
                                                                         if e.get("family") == explore.get("family") and e.get("attempt_id") != exposure_aid}),
                                   "prior_exposure_of_these_intervals": len(prior_exposure(intervals, exclude_attempt=exposure_aid))}}
    (study / "artifacts").mkdir(parents=True, exist_ok=True)
    (study / "artifacts" / "result.json").write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    card = render_card(record, plan)
    (study / "RESULT_CARD.md").write_text(card, encoding="utf-8")
    ev = append({"kind": "result", "attempt_id": aid, "exposure_attempt_id": exposure_aid, "study_id": record["study_id"],
                 "family": record["family"], "plan_sha256": record["plan_sha256"], "definition_sha256": record["definition_sha256"],
                 "analysis_identity_sha256": analysis_identity, "intervals": intervals, "verdict": outcome["verdict"],
                 "estimate": outcome["estimate"], "ci_low": outcome["ci_low"], "ci_high": outcome["ci_high"],
                 "n_clusters": outcome["n_clusters"], "claim_level": level, "recommendation": record["recommendation"],
                 "result_artifact_sha256": outcome["artifact_sha256"]}, study=study)
    record["ledger_event"] = ev["event_id"]
    return record


def _fmt(v: Any) -> str:
    return "n/a" if v is None else (f"{v:+.4f}" if isinstance(v, float) else str(v))


def render_card(rec: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    r = rec["result"]
    pop = rec.get("population") or {}
    iv = rec.get("intervals") or []
    span = f"{iv[0]['start']} .. {iv[-1]['end']}" if iv else "n/a"
    lim = list((rec.get("validation") or {}).get("limitations") or [])
    first = next(iter(events()), {}).get("recorded_at_utc", "")[:10] or "today"
    lim += [f"Claim level {rec['claim_level']}: {rec['claim_reason']}.",
            f"Ledger history begins {first}: exposure from earlier (pre-ledger) research is NOT recorded, so '0 prior exposures' "
            "never means the data are unseen.",
            "Exploratory evidence on previously examined data; not out-of-sample confirmation.",
            "Predictive research only: no orders, fills, costs or execution validation."]
    lines = [
        f"# RESULT CARD -- {rec['study_id']}",
        "",
        f"**Result: {r['verdict']}** ({r['reason']}).  **Recommendation: {rec['recommendation']}.**  "
        f"Claim level: **{rec['claim_level']}**.  Status: **{rec['isolation']}** (no merge, no promotion, no trading permission).",
        "",
        f"- **Hypothesis:** {rec['hypothesis']}",
        f"- **Question:** {(plan.get('study') or {}).get('question')}",
        f"- **Population:** {pop.get('description', '')} -- {pop.get('rows', 'n/a')} candidate rows, {pop.get('sessions', 'n/a')} sessions; "
        f"exclusions: {pop.get('exclusions', 'n/a')}",
        f"- **Dataset / interval:** {', '.join(sorted(rec['datasets']))} {span}",
        f"- **Primary outcome:** `{r['column']}` -- difference `{r['difference']}` = mean(a {r['a']}) - mean(b {r['b']})",
        f"- **Control:** {rec['control']} (n_a={r['n_rows_a']}, n_b={r['n_rows_b']})",
        f"- **Estimate:** {_fmt(r['estimate'])}, 95% session-clustered CI [{_fmt(r['ci_low'])}, {_fmt(r['ci_high'])}], "
        f"{r['n_clusters']} session clusters",
        f"- **Pre-registered rule:** expected {rec['pre_registered_rule']['expected_sign']}, min_effect "
        f"{rec['pre_registered_rule'].get('min_effect', 0.0)}, min_clusters {rec['pre_registered_rule'].get('min_clusters', 20)} "
        f"(frozen in plan `{str(rec['plan_sha256'])[:12]}` before any outcome existed)",
        f"- **Scientific validity:** " + ", ".join(f"{k}={v}" for k, v in sorted((rec.get('validation') or {}).items()) if k != "limitations"),
        f"- **Exposure history:** family `{rec['family']}` prior attempts {len(rec['exposure_history']['prior_attempts_in_family'])}; "
        f"prior ledger exposures of these intervals {rec['exposure_history']['prior_exposure_of_these_intervals']}",
        f"- **Attempt:** `{rec['attempt_id']}` (definition `{str(rec['definition_sha256'])[:12]}`, analysis `{str(rec['analysis_identity_sha256'])[:12]}`)",
        "",
        "## Limitations",
        *[f"- {x}" for x in lim],
        "",
    ]
    return "\n".join(lines)


def summary(limit: int = 20) -> List[Dict[str, Any]]:
    return [{k: e.get(k) for k in ("recorded_at_utc", "study_id", "family", "verdict", "estimate", "ci_low", "ci_high", "claim_level",
                                   "recommendation", "attempt_id")} for e in events("result")][-limit:]


__all__ = ["LedgerError", "CLAIM_LEVELS", "VERDICTS", "ledger_dir", "reserved_windows", "definition_sha256", "plan_intervals",
           "attempt_id", "append", "events", "rebuild_from_mirrors", "prior_exposure", "check_reserved", "record_exposure",
           "claim_level", "evaluate", "write_result", "render_card", "summary"]
