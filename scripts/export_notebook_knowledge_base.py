"""
NautilusTrader Research Knowledge Base & Gemini Notebook / NotebookLM Exporter
==============================================================================
Scrapes, synthesizes, and exports all 83+ studies, 110+ features, strategies,
metrics, and causal audit history across the repository into a CONSOLIDATED
single-file master document + CSV database optimized for Google NotebookLM.

Leaves ~48 of your 50 NotebookLM source slots completely free for research
papers, PDFs, books, and external sources!

Output Files:
  1. NAUTILUS_RESEARCH_BRAIN_MASTER.md  (Complete, single-file untruncated master encyclopedia)
  2. studies_master_metrics.csv         (Living structured quantitative spreadsheet)
  3. features_master_catalog.json       (Machine-readable feature registry contract)

Usage:
    python scripts/export_notebook_knowledge_base.py
    python scripts/export_notebook_knowledge_base.py --output-dir "G:/My Drive/Nautilus_Research_Notebook"
"""

import os
import sys
import re
import csv
import json
import shutil
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Base repository root
REPO_ROOT = Path(__file__).resolve().parent.parent

def read_text_safe(path: Optional[Path]) -> str:
    """Safely read text file handling various encodings."""
    if not path or not path.exists():
        return ""
    for enc in ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception:
        return ""

def classify_study(study_name: str, spec_text: str, report_text: str) -> str:
    """Classify study into logical thematic pillar."""
    name_lower = study_name.lower()
    
    if any(k in name_lower for k in ['train', 'walkforward', 'walk_forward', 'retrain', 'model_b', 'mirrored', 'top100', 'top50', 'top25', 'ml_5m']):
        return "ML / Walk-Forward Retrain"
    elif any(k in name_lower for k in ['w4', 'fable5', 'fade', 'weakness', 'countertrade', 'delayed_entry']):
        return "W4 & Fable 5 Fade Strategies"
    elif any(k in name_lower for k in ['exit', 'mfe', 'monetization', 'ratchet', 'retracement', 'giveback', 'recovery', 'runner', 'bracket', 'forward_opportunity']):
        return "Exit Management & Monetization"
    elif any(k in name_lower for k in ['flip', 'regime', 'pre_flip', 'chop', 'impulse', 'rl_regime']):
        return "Regime & Pre-Flip Signals"
    elif any(k in name_lower for k in ['feature', 'f3', 'volume_level', 'price_level', 'morphology']):
        return "Feature Engineering & Reduction"
    elif any(k in name_lower for k in ['root_cause', 'deterioration', 'residual', 'audit', 'diagnostic', 'discontinuity', 'isolation']):
        return "Diagnostics & Root Cause"
    elif any(k in name_lower for k in ['infra', 'canonical', 'store', 'schedule', 'builder', 'checkpoint']):
        return "Infrastructure & Canonical Stores"
    elif any(k in name_lower for k in ['null', 'benchmark', 'random', 'race']):
        return "Benchmarks & Null Controls"
    else:
        return "Strategy Exploration"

def determine_status_and_verdict(study_id: str, spec_text: str, report_text: str, audit_text: str) -> Tuple[str, str, str]:
    """Determine lifecycle status (ACCEPTED, FALSIFIED, DISCARDED, EXPLORATORY, BENCHMARK),
    the outcome verdict, and the reason for rejection/discard if applicable."""
    combined = (report_text + "\n" + spec_text).lower()
    
    status = "EXPLORATORY"
    verdict = ""
    discard_reason = ""
    
    for line in report_text.split('\n'):
        line_clean = line.strip()
        if line_clean.lower().startswith('**verdict:**') or line_clean.lower().startswith('## verdict') or line_clean.lower().startswith('**decision:**') or line_clean.lower().startswith('## decision'):
            verdict = line_clean.replace('**', '').replace('##', '').strip()
            break
        elif line_clean.lower().startswith('**status:**') or line_clean.lower().startswith('## status'):
            if not verdict:
                verdict = line_clean.replace('**', '').replace('##', '').strip()
                
    if not verdict:
        meaningful_lines = [l.strip() for l in report_text.split('\n') if l.strip() and not l.startswith('#')]
        if meaningful_lines:
            verdict = meaningful_lines[0][:150]
        else:
            meaningful_lines_spec = [l.strip() for l in spec_text.split('\n') if l.strip() and not l.startswith('#')]
            verdict = meaningful_lines_spec[0][:150] if meaningful_lines_spec else "Study completed."

    verdict_lower = verdict.lower() + " " + combined
    if any(k in verdict_lower for k in ['explained_by', 'no_policy_improvement', 'pt_runner_fails', 'reentry_adds_churn', 'bracket_race_unstable', 'falsified', 'discovery_negative', 'no_monetizable_weakness_fade']):
        status = "FALSIFIED" if 'falsified' in verdict_lower or 'explained_by' in verdict_lower else "DISCARDED"
    elif "verdict: accepted" in combined or "accepted" in report_text[:300].lower() or "accepted" in spec_text[:300].lower():
        status = "ACCEPTED"
    elif "benchmark" in study_id.lower() or "null" in study_id.lower():
        status = "BENCHMARK"
    elif "diagnostic" in study_id.lower() or "investigation" in combined:
        status = "COMPLETED"

    if status in ["FALSIFIED", "DISCARDED"]:
        for pattern in [
            r'(?:why|reason|falsified because|failed because|negative because|drawback|flaw)[\s\:\-]+([^\.\n]+(?:\.[^\.\n]+)?)',
            r'(?:no positive|zero alpha|cannot establish|drag exceeded|overfit|leakage|loss attribution)[\s\:\-]+([^\.\n]+)',
            r'## (?:Failure Modes|Root Cause|Drawbacks|Bottom line)\s*\n([^\n]+)'
        ]:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                discard_reason = match.group(1).strip()
                break
        if not discard_reason:
            discard_reason = verdict
        discard_reason = discard_reason.strip('| \t\r\n')
        if len(discard_reason) < 3:
            discard_reason = "Hypothesis closed as explained by baseline confirmation quality / negative alpha."

    return status, verdict, discard_reason

def extract_metrics_fast(study_dir: Path, report_text: str, json_files: List[Path]) -> Dict[str, Any]:
    """Extract quantitative performance metrics quickly from key JSONs and report text."""
    metrics = {
        'profit_factor': None,
        'win_rate_pct': None,
        'total_trades': None,
        'net_pnl_or_atr': None,
        'max_drawdown': None,
        'sharpe_ratio': None,
        'sample_period': None,
        'timeframe': None,
    }
    
    for json_file in json_files[:5]:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                if 'pf' in data and metrics['profit_factor'] is None:
                    metrics['profit_factor'] = round(float(data['pf']), 3)
                if 'profit_factor' in data and metrics['profit_factor'] is None:
                    metrics['profit_factor'] = round(float(data['profit_factor']), 3)
                if 'win_rate' in data and metrics['win_rate_pct'] is None:
                    metrics['win_rate_pct'] = round(float(data['win_rate']) * (100 if float(data['win_rate']) <= 1.0 else 1), 2)
                if 'trades' in data and metrics['total_trades'] is None:
                    metrics['total_trades'] = int(data['trades'])
                if 'n_trades' in data and metrics['total_trades'] is None:
                    metrics['total_trades'] = int(data['n_trades'])
                if 'total_trades' in data and metrics['total_trades'] is None:
                    metrics['total_trades'] = int(data['total_trades'])
                if 'net_pnl' in data and metrics['net_pnl_or_atr'] is None:
                    metrics['net_pnl_or_atr'] = data['net_pnl']
                if 'dd' in data and metrics['max_drawdown'] is None:
                    metrics['max_drawdown'] = data['dd']
                if 'max_dd' in data and metrics['max_drawdown'] is None:
                    metrics['max_drawdown'] = data['max_dd']
                if 'sharpe' in data and metrics['sharpe_ratio'] is None:
                    metrics['sharpe_ratio'] = round(float(data['sharpe']), 3)
                if 'sample_period' in data and metrics['sample_period'] is None:
                    metrics['sample_period'] = data['sample_period']
                if 'primary_table' in data and isinstance(data['primary_table'], list) and metrics['total_trades'] is None:
                    n_vals = [item['value'] for item in data['primary_table'] if item.get('metric') == 'n_confirmed' and item.get('population_definition') == 'TRANSITION']
                    if n_vals:
                        metrics['total_trades'] = int(sum(n_vals))
        except Exception:
            pass

    if metrics['profit_factor'] is None:
        m = re.search(r'(?:PF|Profit Factor)[\s\:\=\|]+([0-9]+\.[0-9]+)', report_text, re.IGNORECASE)
        if m:
            try:
                metrics['profit_factor'] = float(m.group(1))
            except ValueError:
                pass
                
    if metrics['win_rate_pct'] is None:
        m = re.search(r'(?:WR|Win Rate|Win %)[\s\:\=\|]+([0-9]+(?:\.[0-9]+)?)\s*\%?', report_text, re.IGNORECASE)
        if m:
            try:
                metrics['win_rate_pct'] = float(m.group(1))
            except ValueError:
                pass

    if metrics['total_trades'] is None:
        m = re.search(r'(?:Trades|N Trades|Trade Count|N=)[\s\:\=\|]+([0-9\,]+)', report_text, re.IGNORECASE)
        if m:
            try:
                metrics['total_trades'] = int(m.group(1).replace(',', ''))
            except ValueError:
                pass

    if metrics['max_drawdown'] is None:
        m = re.search(r'(?:Max DD|Max Drawdown|Drawdown)[\s\:\=\|]+(\-?[0-9]+(?:\.[0-9]+)?(?:\s*ATR|\s*\%|\s*\$)?)', report_text, re.IGNORECASE)
        if m:
            metrics['max_drawdown'] = m.group(1).strip()

    for tf in ['1s', '5s', '30s', '1m', '5m']:
        if tf in study_dir.name.lower():
            metrics['timeframe'] = tf
            break
    if not metrics['timeframe']:
        m = re.search(r'\b(1s|5s|30s|1m|5m|15m|1h)\b', report_text, re.IGNORECASE)
        if m:
            metrics['timeframe'] = m.group(1).lower()
        else:
            metrics['timeframe'] = "1s/1m"

    m_yr = re.findall(r'\b(202[0-6])\b', report_text + " " + study_dir.name)
    if m_yr:
        yrs = sorted(list(set(m_yr)))
        metrics['sample_period'] = f"{yrs[0]}-{yrs[-1]}" if len(yrs) > 1 else yrs[0]
    else:
        metrics['sample_period'] = "2021-2025 RTH"

    return metrics

def harvest_all_studies(studies_dir: Path) -> List[Dict[str, Any]]:
    """Scan and parse all study folders capturing complete full text of specs, reports, and audits."""
    studies = []
    
    for s_dir in sorted(studies_dir.iterdir()):
        if not s_dir.is_dir() or s_dir.name.startswith('.') or s_dir.name == '__pycache__':
            continue
            
        study_id = s_dir.name
        
        md_files = []
        py_files = []
        json_files = []
        csv_files = []
        parquet_files = []
        
        for item in s_dir.iterdir():
            if item.is_file():
                ext = item.suffix.lower()
                if ext == '.md': md_files.append(item)
                elif ext == '.py': py_files.append(item)
                elif ext == '.json': json_files.append(item)
                elif ext == '.csv': csv_files.append(item)
                elif ext == '.parquet': parquet_files.append(item)
                
        res_dir = s_dir / "results"
        if res_dir.is_dir():
            for item in res_dir.iterdir():
                if item.is_file():
                    ext = item.suffix.lower()
                    if ext == '.md': md_files.append(item)
                    elif ext == '.json': json_files.append(item)
                    elif ext == '.csv': csv_files.append(item)
                    elif ext == '.parquet': parquet_files.append(item)
                    
        audit_dir = s_dir / "audit"
        if audit_dir.is_dir():
            for item in audit_dir.iterdir():
                if item.is_file():
                    ext = item.suffix.lower()
                    if ext == '.md': md_files.append(item)
                    elif ext == '.json': json_files.append(item)

        report_file = None
        for candidate in ['report.md', 'study_report.md', 'final_report.md', 'build_report.md', 'summary.md', 'readme.md']:
            for mf in md_files:
                if mf.name.lower() == candidate:
                    report_file = mf
                    break
            if report_file:
                break
                
        if not report_file:
            report_file = next((f for f in md_files if any(k in f.name.lower() for k in ['report', 'final', 'summary']) and 'spec' not in f.name.lower() and 'audit' not in str(f).lower()), None)
            
        spec_file = next((f for f in md_files if 'spec' in f.name.lower()), None)
        if not report_file:
            report_file = spec_file or (md_files[0] if md_files else None)
            
        audit_file = next((f for f in md_files if 'audit' in str(f).lower() or 'pass_' in f.name.lower()), None)
        
        valid_pys = [f for f in py_files if not f.name.startswith('__')]
        entrypoint_py = None
        for pref in ['run_study.py', 'run_nt.py', 'run_isolation.py', 'run_all_analysis.py', 'finalize_preserved_stage2.py', 'strategy.py']:
            for pf in valid_pys:
                if pf.name.lower() == pref:
                    entrypoint_py = pf
                    break
            if entrypoint_py:
                break
        if not entrypoint_py and valid_pys:
            entrypoint_py = next((f for f in valid_pys if 'run' in f.name.lower() or 'study' in f.name.lower() or 'strat' in f.name.lower()), valid_pys[0])
        
        spec_text = read_text_safe(spec_file) if spec_file else ""
        report_text = read_text_safe(report_file) if report_file else ""
        audit_text = read_text_safe(audit_file) if audit_file else ""
        
        category = classify_study(study_id, spec_text, report_text)
        status, verdict, discard_reason = determine_status_and_verdict(study_id, spec_text, report_text, audit_text)
        metrics = extract_metrics_fast(s_dir, report_text, json_files)
        
        title_match = re.search(r'#\s*(.+)', report_text or spec_text)
        title = title_match.group(1).strip() if title_match else study_id.replace('_', ' ').title()
        title = title.replace('— Frozen Specification', '').replace('— Report', '').replace('– Report', '').strip()
        
        hypothesis = ""
        for pattern in [
            r'## (?:Decision|Hypothesis|Objective|Goal|Purpose|Bottom line)[\s\:\-]*\n([^\n#]+)',
            r'\*\*(?:Decision|Hypothesis|Objective|Goal|Verdict)\:\*\*\s*([^\n#]+)',
            r'#+\s*(?:Hypothesis|Objective)\s*\n([^\n#]+)'
        ]:
            match = re.search(pattern, report_text or spec_text, re.IGNORECASE)
            if match:
                hypothesis = match.group(1).strip()
                break
        if not hypothesis:
            lines = [l.strip() for l in (spec_text or report_text).split('\n') if l.strip() and not l.startswith('#')]
            hypothesis = lines[0][:150] if lines else "Evaluate trading/regime model variation."

        audit_status = "Not Audited"
        status_json_file = next((f for f in json_files if f.name == 'status.json'), None)
        if status_json_file:
            try:
                with open(status_json_file, 'r', encoding='utf-8') as f:
                    sj = json.load(f)
                crit = sj.get('critical', 0)
                warn = sj.get('warning', 0)
                verd = sj.get('verdict', 'PASS')
                gates_info = ""
                if 'validation_gates' in sj and isinstance(sj['validation_gates'], dict):
                    passed_g = sj['validation_gates'].get('passed', 0)
                    total_g = sj['validation_gates'].get('total', 0)
                    gates_info = f", {passed_g}/{total_g} Gates"
                audit_status = f"Audit {verd} ({crit} Crit, {warn} Warn{gates_info})"
            except Exception:
                audit_status = "Audit Status JSON Recorded"
        elif audit_file:
            if "critical: 0" in audit_text.lower() or "verdict: pass" in audit_text.lower() or "passed" in audit_text.lower():
                audit_status = "Audit Clean / Passed"
            else:
                audit_status = "Audited (Report Present)"
                
        features_referenced = set()
        for py_f in (valid_pys[:3] if valid_pys else py_files[:3]):
            py_code = read_text_safe(py_f)
            f_matches = re.findall(r"['\"]([a-z0-9\_]+(?:atr|vel|rsi|ema|vol|swing|delta|pressure|zone|cross|ratio)[a-z0-9\_]*)['\"]", py_code)
            for fm in f_matches:
                features_referenced.add(fm)

        studies.append({
            'study_id': study_id,
            'title': title,
            'category': category,
            'status': status,
            'verdict': verdict,
            'hypothesis': hypothesis,
            'discard_reason': discard_reason,
            'metrics': metrics,
            'audit_status': audit_status,
            'features_referenced': sorted(list(features_referenced))[:12],
            'files_count': {
                'md': len(md_files),
                'py': len(py_files),
                'json': len(json_files),
                'csv': len(csv_files),
                'parquet': len(parquet_files)
            },
            'paths': {
                'spec': str(spec_file.relative_to(REPO_ROOT)) if spec_file else "",
                'report': str(report_file.relative_to(REPO_ROOT)) if report_file else "",
                'audit': str(audit_file.relative_to(REPO_ROOT)) if audit_file else "",
                'entrypoint': str(entrypoint_py.relative_to(REPO_ROOT)) if entrypoint_py else "",
                'dir': str(s_dir.relative_to(REPO_ROOT))
            },
            'spec_full_text': spec_text,
            'report_full_text': report_text,
            'audit_full_text': audit_text,
        })
        
    return studies

def harvest_features() -> Dict[str, Any]:
    """Parse features/registry.py and features/FEATURES.md to get complete feature dictionary."""
    registry_path = REPO_ROOT / "features" / "registry.py"
    features_md_path = REPO_ROOT / "features" / "FEATURES.md"
    
    registry_text = read_text_safe(registry_path)
    features_md_text = read_text_safe(features_md_path)
    
    features_dict = {}
    pattern = r"['\"]([a-zA-Z0-9\_]+)['\"]\s*\:\s*FeatureDefinition\((.*?)\)"
    matches = re.findall(pattern, registry_text, re.DOTALL)
    
    for name, body in matches:
        def_info = {
            'name': name,
            'status': 'verified',
            'family': '',
            'stateful': True,
            'source_timeframe': '1s',
            'update_anchor': 'after_1s_close',
            'warmup': None,
            'window': None,
            'window_unit': None,
            'normalizer': 'study_contract',
            'implementation': ''
        }
        for field in ['status', 'family', 'source_timeframe', 'update_anchor', 'snapshot_anchor', 'normalizer', 'dtype', 'implementation', 'window_unit', 'reset_policy']:
            m = re.search(rf"{field}\s*=\s*['\"]([^'\"]+)['\"]", body)
            if m:
                def_info[field] = m.group(1)
        for num_field in ['warmup', 'window']:
            m = re.search(rf"{num_field}\s*=\s*([0-9]+(?:\.[0-9]+)?)", body)
            if m:
                def_info[num_field] = float(m.group(1)) if '.' in m.group(1) else int(m.group(1))
        m_state = re.search(r"stateful\s*=\s*(True|False)", body)
        if m_state:
            def_info['stateful'] = m_state.group(1) == 'True'
            
        features_dict[name] = def_info
        
    table_rows = re.findall(r'\|\s*`([a-zA-Z0-9\_]+)`\s*\|\s*([^\|]+)\|\s*([^\|]+)\|', features_md_text)
    for feat_name, desc, units_or_range in table_rows:
        feat_name = feat_name.strip()
        desc = desc.strip()
        units_or_range = units_or_range.strip()
        if feat_name in features_dict:
            features_dict[feat_name]['description'] = desc
            features_dict[feat_name]['units_or_range'] = units_or_range
        else:
            features_dict[feat_name] = {
                'name': feat_name,
                'description': desc,
                'units_or_range': units_or_range,
                'status': 'verified',
                'stateful': True,
                'source_timeframe': '1s/1m',
                'family': 'general'
            }
            
    return features_dict

def harvest_strategies() -> List[Dict[str, Any]]:
    """Harvest strategies and execution engines from strategies/."""
    strategies = []
    strat_dir = REPO_ROOT / "strategies"
    
    for f in strat_dir.rglob("*.py"):
        if f.name.startswith("__"):
            continue
        code = read_text_safe(f)
        docstring_match = re.search(r'"""(.*?)"""', code, re.DOTALL)
        docstring = docstring_match.group(1).strip() if docstring_match else ""
        class_match = re.search(r'class\s+([A-Za-z0-9_]+)\b', code)
        class_name = class_match.group(1) if class_match else f.stem
        
        strategies.append({
            'file_name': f.name,
            'class_name': class_name,
            'path': str(f.relative_to(REPO_ROOT)),
            'docstring': docstring,
            'line_count': len(code.split('\n')),
            'full_code': code
        })
        
    return strategies

def generate_master_metrics_csv(studies: List[Dict[str, Any]], out_path: Path):
    """Generate the structured living CSV database file with graceful lock handling."""
    fieldnames = [
        'study_id',
        'study_name',
        'category',
        'status',
        'sample_period',
        'timeframe',
        'profit_factor',
        'win_rate_pct',
        'total_trades',
        'max_drawdown',
        'net_pnl_or_atr',
        'sharpe_ratio',
        'key_hypothesis',
        'outcome_verdict',
        'discard_or_failure_reason',
        'audit_status',
        'primary_features',
        'spec_path',
        'report_path',
        'entrypoint_script'
    ]
    
    target = out_path
    try:
        f = open(target, 'w', newline='', encoding='utf-8')
    except PermissionError:
        target = out_path.parent / (out_path.stem + "_updated" + out_path.suffix)
        print(f"    [!] Warning: '{out_path.name}' is currently locked by another application (e.g. Excel).", flush=True)
        print(f"        Writing to '{target.name}' instead. Close the locking application to overwrite the original.", flush=True)
        f = open(target, 'w', newline='', encoding='utf-8')

    with f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for s in studies:
            m = s['metrics']
            writer.writerow({
                'study_id': s['study_id'],
                'study_name': s['title'],
                'category': s['category'],
                'status': s['status'],
                'sample_period': m.get('sample_period', ''),
                'timeframe': m.get('timeframe', ''),
                'profit_factor': m.get('profit_factor', ''),
                'win_rate_pct': m.get('win_rate_pct', ''),
                'total_trades': m.get('total_trades', ''),
                'max_drawdown': m.get('max_drawdown', ''),
                'net_pnl_or_atr': m.get('net_pnl_or_atr', ''),
                'sharpe_ratio': m.get('sharpe_ratio', ''),
                'key_hypothesis': s['hypothesis'],
                'outcome_verdict': s['verdict'],
                'discard_or_failure_reason': s['discard_reason'],
                'audit_status': s['audit_status'],
                'primary_features': ", ".join(s['features_referenced'][:8]),
                'spec_path': s['paths']['spec'],
                'report_path': s['paths']['report'],
                'entrypoint_script': s['paths']['entrypoint'],
            })
    return target

def generate_consolidated_master_brain_md(studies: List[Dict[str, Any]], features: Dict[str, Any], strategies: List[Dict[str, Any]], out_path: Path):
    """Generate a single unified master living markdown encyclopedia combining all dossiers, metrics, features, discarded ideas, and specs."""
    md = []
    
    # HEADER
    md.append("# NAUTILUS TRADER QUANTITATIVE RESEARCH BRAIN — MASTER REPOSITORY COMPENDIUM")
    md.append("\n> **Comprehensive, living, single-document knowledge base containing 100% full-text research specifications, reports, quantitative metrics, feature definitions, strategy architectures, discarded ideas, and causal audit history.**")
    md.append("\n*Generated for Google Gemini / Google NotebookLM (Consolidated single-source edition).*")
    md.append("\n---\n")
    
    # TABLE OF CONTENTS
    md.append("## TABLE OF CONTENTS\n")
    md.append("1. [Executive Overview & Chronological Milestones](#part-1-executive-overview--chronology)")
    md.append("2. [Master Quantitative Studies Index Table (All 83 Studies)](#part-2-master-studies-index-table)")
    md.append("3. [Discarded Ideas, Falsified Hypotheses & Resurrectability Atlas](#part-3-discarded-ideas-and-negative-results-atlas)")
    md.append("4. [Central Feature Engineering Registry (110 Features)](#part-4-feature-engineering-registry)")
    md.append("5. [Strategy Architectures & Execution Compendium](#part-5-strategy-architectures-and-code)")
    md.append("6. [Anti-Lookahead Causal Governance & Audit Rules](#part-6-causal-governance-and-audit-checklist)")
    md.append("7. [Complete Full-Text Study Dossiers (All 83 Studies)](#part-7-complete-study-dossiers)\n")
    md.append("\n---\n")
    
    # PART 1: EXECUTIVE OVERVIEW
    total_studies = len(studies)
    status_counts = {}
    cat_counts = {}
    for s in studies:
        status_counts[s['status']] = status_counts.get(s['status'], 0) + 1
        cat_counts[s['category']] = cat_counts.get(s['category'], 0) + 1
        
    md.append("## <a id=\"part-1-executive-overview--chronology\"></a> PART 1: Executive Overview & Chronology\n")
    md.append(f"- **Total Studies Documented:** `{total_studies}`")
    md.append(f"- **Total Features Registered:** `{len(features)}`")
    md.append(f"- **Strategy Classes Cataloged:** `{len(strategies)}`")
    md.append(f"- **Status Breakdown:** " + ", ".join([f"`{k}: {v}`" for k, v in sorted(status_counts.items())]))
    md.append(f"- **Thematic Pillars:** " + ", ".join([f"`{k}: {v}`" for k, v in sorted(cat_counts.items())]))
    md.append("""
### Chronological Research Progression:
1. **Phase 1 (Parity & Zero Look-Ahead):** Databento 1s catalog ingestion, Central Time timestamp alignment, and strict event-loop isolation.
2. **Phase 2 (Regime Flips & Pre-Flip Signals):** Canonical regime complete store creation, pre-flip reversal detection, and baseline flip parity.
3. **Phase 3 (ML Retraining & Fanning Models):** Top 100/50/25 LightGBM models trained on pure flips, quarterly walk-forward stability testing.
4. **Phase 4 (W4 Fade Engine & Policy A):** Counter-trend regime weakness fade, arrival velocity deceleration, entry threshold morphology, and confirmation timeout clocks.
5. **Phase 5 (Exit Management & Monetization):** Excursion mapping, giveback recovery analysis, runner monetizations, and asymmetric trailing stops.
""")
    md.append("\n---\n")
    
    # PART 2: MASTER TABLE
    md.append("## <a id=\"part-2-master-studies-index-table\"></a> PART 2: Master Studies Index Table\n")
    md.append("| # | Study ID | Pillar | Status | TF | Trades | PF | Win % | Verdict / Core Finding |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(studies, 1):
        m = s['metrics']
        pf = f"{m['profit_factor']:.2f}" if m.get('profit_factor') is not None else "-"
        wr = f"{m['win_rate_pct']:.1f}%" if m.get('win_rate_pct') is not None else "-"
        tr = f"{m['total_trades']}" if m.get('total_trades') is not None else "-"
        tf = m.get('timeframe', '1s/1m')
        clean_verdict = s['verdict'].replace('|', '/').replace('\n', ' ')[:75]
        md.append(f"| {i} | [`{s['study_id']}`](#dossier-{s['study_id'].lower().replace('_', '-')}) | {s['category']} | `{s['status']}` | {tf} | {tr} | {pf} | {wr} | {clean_verdict} |")
    md.append("\n---\n")
    
    # PART 3: DISCARDED IDEAS ATLAS
    discarded = [s for s in studies if s['status'] in ['FALSIFIED', 'DISCARDED', 'BENCHMARK'] or s['discard_reason']]
    md.append("## <a id=\"part-3-discarded-ideas-and-negative-results-atlas\"></a> PART 3: Discarded Ideas, Falsified Hypotheses & Resurrectability Atlas\n")
    md.append("> **In quantitative trading, negative results represent the strongest guard against overfitting. Discarded ideas often fail due to specific constraints (spread size, queue latency, coarse timeframes) rather than fundamentally flawed logic. This atlas records why each failed and what conditions would justify re-evaluating it.**\n")
    md.append("### Failure Mode Taxonomy:")
    md.append("1. **Failure Mode A: Frictional & Execution Drag (The 1-Second Trap):** Signals with 60%+ win rates in bar simulation that failed on 1s ticks due to 1-tick bid-ask spread ($5.00/NQ) and queue latency (e.g., `p90_conditional_losing_5s_exit`).")
    md.append("2. **Failure Mode B: Premature Monetization (The Profit Ratchet Paradox):** Locking in early profits on confirmed regimes cut large multi-R runner trades short, destroying net strategy edge (e.g., `post_confirm_profit_ratchet`, `top10_post_confirmation_mfe_monetization`).")
    md.append("3. **Failure Mode C: Confounded Regime Alignment (Confirmation Quality vs Horizon):** Higher-timeframe (5m) alignment appeared to improve returns in unstratified data, but 8-way stratification proved the lift was 100% explained by confirmation-time trade quality, not 5m regime persistence (`post_confirm_5m_forward_opportunity`).")
    md.append("\n| Discarded Study | Original Thesis | Why Discarded | Conditions to Re-Evaluate |")
    md.append("|---|---|---|---|")
    for s in discarded:
        hyp = s['hypothesis'][:75].replace('|', '/')
        reason = (s['discard_reason'] or s['verdict'])[:85].replace('|', '/')
        revisit = "Re-evaluate if sub-second queue prediction or lower commission tier available."
        if "ratchet" in s['study_id'] or "profit" in s['study_id']:
            revisit = "Test only with volatility-scaled wide trailing stops in high-momentum regimes."
        elif "null" in s['study_id'] or "random" in s['study_id']:
            revisit = "Benchmark control only; do not trade."
        elif "5m" in s['study_id'] or "forward_opportunity" in s['study_id']:
            revisit = "5m alignment does not add alpha over confirmation quality; do not hold longer for 5m alignment alone."
        md.append(f"| [`{s['study_id']}`](#dossier-{s['study_id'].lower().replace('_', '-')}) | {hyp} | {reason} | {revisit} |")
    md.append("\n---\n")
    
    # PART 4: FEATURE REGISTRY
    md.append("## <a id=\"part-4-feature-engineering-registry\"></a> PART 4: Central Feature Engineering Registry\n")
    md.append(f"> **110 registered indicators and stateful feature trackers in `features/registry.py` and `features/library.py`.**\n")
    md.append("| Feature Name | Family | TF | Stateful | Warmup | Description / Units |")
    md.append("|---|---|---|---|---|---|")
    for name, data in sorted(features.items()):
        fam = data.get('family', 'general')
        tf = data.get('source_timeframe', '1s')
        st = "Yes" if data.get('stateful', True) else "No"
        wu = f"{data.get('warmup')} bars" if data.get('warmup') else "-"
        desc = data.get('description') or data.get('units_or_range') or data.get('implementation', '').split('.')[-1] or '-'
        md.append(f"| `{name}` | `{fam}` | `{tf}` | {st} | {wu} | {desc} |")
    md.append("\n---\n")
    
    # PART 5: STRATEGY ARCHITECTURES
    md.append("## <a id=\"part-5-strategy-architectures-and-code\"></a> PART 5: Strategy Architectures & Execution Compendium\n")
    for s in strategies:
        md.append(f"### Strategy Class: `{s['class_name']}` (`{s['file_name']}`)")
        md.append(f"- **Path:** [`{s['path']}`]({s['path']}) | **Total Lines:** `{s['line_count']}`")
        if s['docstring']:
            md.append(f"- **Docstring:**\n> {s['docstring']}\n")
        md.append(f"\n```python\n{s['full_code']}\n```\n")
        md.append("\n---\n")
        
    # PART 6: CAUSAL GOVERNANCE
    md.append("## <a id=\"part-6-causal-governance-and-audit-checklist\"></a> PART 6: Anti-Lookahead Causal Governance & Audit Rules\n")
    md.append(read_text_safe(REPO_ROOT / "docs" / "CAUSAL_CHECKLIST.md"))
    md.append("\n\n---\n")
    
    # PART 7: COMPLETE DOSSIERS
    md.append("## <a id=\"part-7-complete-study-dossiers\"></a> PART 7: Complete Full-Text Study Dossiers (All 83 Studies)\n")
    
    categories = sorted(list(set(s['category'] for s in studies)))
    for cat in categories:
        cat_studies = [s for s in studies if s['category'] == cat]
        md.append(f"\n### Pillar: {cat} ({len(cat_studies)} Studies)\n")
        
        for s in cat_studies:
            m = s['metrics']
            md.append(f"#### <a id=\"dossier-{s['study_id'].lower().replace('_', '-')}\"></a> {s['title']} (`{s['study_id']}`)\n")
            md.append(f"- **Category:** {s['category']} | **Status:** `{s['status']}` | **Audit State:** {s['audit_status']}")
            md.append(f"- **Files:** Report: [`{s['paths']['report']}`]({s['paths']['report']}) | SPEC: [`{s['paths']['spec']}`]({s['paths']['spec']}) | Code: [`{s['paths']['entrypoint']}`]({s['paths']['entrypoint']})")
            md.append("\n**Quantitative Metrics Card:**")
            md.append("| Metric | Value | Metric | Value |")
            md.append("|---|---|---|---|")
            md.append(f"| Profit Factor | `{m.get('profit_factor', 'N/A')}` | Win Rate | `{m.get('win_rate_pct', 'N/A')}%` |")
            md.append(f"| Total Trades | `{m.get('total_trades', 'N/A')}` | Max Drawdown | `{m.get('max_drawdown', 'N/A')}` |")
            md.append(f"| Sample Period | `{m.get('sample_period', 'N/A')}` | Primary Timeframe | `{m.get('timeframe', '1s/1m')}` |")
            
            md.append(f"\n**Core Hypothesis / Objective:**\n> {s['hypothesis']}\n")
            md.append(f"**Outcome & Verdict:**\n> {s['verdict']}\n")
            if s['discard_reason']:
                md.append(f"**Failure Mode / Discard Reason:**\n> *{s['discard_reason']}*\n")
                
            if s['features_referenced']:
                md.append(f"**Features Utilized:** " + ", ".join([f"`{f}`" for f in s['features_referenced']]))
                
            if s['report_full_text']:
                md.append(f"\n##### 1. Complete Study Report (`{s['paths']['report']}`)\n")
                md.append(s['report_full_text'])
                md.append("\n")
                
            if s['spec_full_text'] and s['spec_full_text'] != s['report_full_text']:
                md.append(f"\n##### 2. Complete Frozen Specification (`{s['paths']['spec']}`)\n")
                md.append(s['spec_full_text'])
                md.append("\n")
                
            if s['audit_full_text']:
                md.append(f"\n##### 3. Causal Audit Report (`{s['paths']['audit']}`)\n")
                md.append(s['audit_full_text'])
                md.append("\n")
                
            md.append("\n---\n")
            
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

def generate_features_master_catalog_md(features: Dict[str, Any], studies: List[Dict[str, Any]], out_path: Path):
    """Generate comprehensive human and LLM-readable Markdown feature catalog."""
    feature_to_studies = {}
    for s in studies:
        for f in s['features_referenced']:
            if f not in feature_to_studies:
                feature_to_studies[f] = []
            feature_to_studies[f].append(s['study_id'])
            
    for f_name, f_data in features.items():
        f_data['utilized_in_studies'] = feature_to_studies.get(f_name, [])

    md = []
    md.append("# NautilusTrader Feature Engineering Master Catalog")
    md.append("\n> **Comprehensive authoritative specification of all 110 registered indicators, stateful trackers, and multi-timeframe feature calculations in the NautilusTrader event-loop ecosystem.**")
    md.append("\n---\n")
    
    families = sorted(list(set(f.get('family', 'general') for f in features.values())))
    md.append(f"## 1. Feature Registry Overview ({len(features)} Total Features)\n")
    md.append("| Feature Name | Family | Timeframe | Stateful | Warmup | Normalizer | Description / Units |")
    md.append("|---|---|---|---|---|---|---|")
    for name, data in sorted(features.items()):
        fam = data.get('family', 'general')
        tf = data.get('source_timeframe', '1s')
        st = "Yes" if data.get('stateful', True) else "No"
        wu = f"{data.get('warmup')} bars" if data.get('warmup') else "-"
        norm = data.get('normalizer', 'study_contract')
        desc = data.get('description') or data.get('units_or_range') or data.get('implementation', '').split('.')[-1] or '-'
        md.append(f"| `{name}` | `{fam}` | `{tf}` | {st} | {wu} | `{norm}` | {desc} |")
        
    md.append("\n---\n")
    md.append("## 2. Detailed Mathematical Contracts by Feature Family\n")
    
    for fam in families:
        fam_feats = {k: v for k, v in features.items() if v.get('family', 'general') == fam}
        md.append(f"\n### Family: `{fam}` ({len(fam_feats)} Features)\n")
        
        for name, data in sorted(fam_feats.items()):
            md.append(f"#### Feature: `{name}`")
            md.append(f"- **Status:** `{data.get('status', 'verified')}` | **Stateful:** `{data.get('stateful', True)}` | **Timeframe:** `{data.get('source_timeframe', '1s')}`")
            md.append(f"- **Update Anchor:** `{data.get('update_anchor', 'after_1s_close')}` | **Snapshot Anchor:** `{data.get('snapshot_anchor', 'caller_defined')}`")
            md.append(f"- **Normalization:** `{data.get('normalizer', 'study_contract')}` | **Dtype:** `{data.get('dtype', 'float64')}`")
            
            params = []
            if data.get('warmup'): params.append(f"Warmup: `{data.get('warmup')}` bars")
            if data.get('window'): params.append(f"Window: `{data.get('window')}` {data.get('window_unit', 'bars')}")
            if data.get('reset_policy') and data.get('reset_policy') != 'none': params.append(f"Reset: `{data.get('reset_policy')}`")
            if params:
                md.append(f"- **Parameters:** " + " | ".join(params))
                
            if data.get('implementation'):
                md.append(f"- **Implementation Class:** `{data.get('implementation')}`")
            if data.get('description'):
                md.append(f"- **Description:** {data['description']}")
            if data.get('units_or_range'):
                md.append(f"- **Units / Valid Range:** `{data['units_or_range']}`")
            if data.get('utilized_in_studies'):
                md.append(f"- **Utilized in Studies:** " + ", ".join([f"`{s}`" for s in data['utilized_in_studies'][:8]]))
            md.append("")
            
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Export Consolidated NautilusTrader Research Knowledge Base for NotebookLM")
    parser.add_argument("--output-dir", type=str, default="exports/gemini_notebook", help="Output directory path (e.g., local folder or Google Drive path)")
    args = parser.parse_args()
    
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Clean up any leftover subdirectories to keep Google Drive minimal
    for sub in ['all_study_dossiers', 'modular_sources']:
        sub_path = out_dir / sub
        if sub_path.is_dir():
            shutil.rmtree(sub_path, ignore_errors=True)
            
    # Clean up redundant legacy files or JSONs
    for old_file in ['STUDIES_MASTER_CATALOG.md', 'discarded_ideas_and_falsified_hypotheses_atlas.md', 'strategies_and_architecture_compendium.md', 'README_GEMINI_NOTEBOOK_SETUP.md', 'features_master_catalog.json']:
        old_path = out_dir / old_file
        if old_path.is_file():
            try:
                old_path.unlink()
            except Exception:
                pass
    
    print(f"[*] [1/4] Harvesting all studies from {REPO_ROOT / 'studies'}...", flush=True)
    studies = harvest_all_studies(REPO_ROOT / "studies")
    print(f"    Found {len(studies)} valid study directories with full text.", flush=True)
    
    print(f"[*] [2/4] Harvesting feature registry from {REPO_ROOT / 'features'}...", flush=True)
    features = harvest_features()
    print(f"    Found {len(features)} registered feature definitions.", flush=True)
    
    print(f"[*] [3/4] Harvesting strategy classes from {REPO_ROOT / 'strategies'}...", flush=True)
    strategies = harvest_strategies()
    print(f"    Found {len(strategies)} strategy architecture files.", flush=True)
    
    print(f"[*] [4/4] Generating Consolidated Master Brain Artifacts...", flush=True)
    
    # 1. Master CSV
    csv_path = out_dir / "studies_master_metrics.csv"
    generate_master_metrics_csv(studies, csv_path)
    print(f"    -> Generated: {csv_path}", flush=True)
    
    # 2. Master Features Markdown
    feat_md_path = out_dir / "features_master_catalog.md"
    generate_features_master_catalog_md(features, studies, feat_md_path)
    print(f"    -> Generated: {feat_md_path}", flush=True)
    
    # 3. Consolidated Master Markdown Brain
    master_md_path = out_dir / "NAUTILUS_RESEARCH_BRAIN_MASTER.md"
    generate_consolidated_master_brain_md(studies, features, strategies, master_md_path)
    print(f"    -> Generated: {master_md_path}", flush=True)
    
    print("\n[SUCCESS] Consolidated Research Knowledge Base generated in:")
    print(f"    {out_dir}")
    print(f"    Total files: 3 supported files (2 Markdown + 1 CSV)")
    print(f"    Takes only 2-3 source slots in NotebookLM, leaving ~47 slots free for your research papers!")

if __name__ == "__main__":
    main()
