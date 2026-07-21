from pathlib import Path

def print_context(path, keyword):
    p = Path(path)
    if not p.exists():
        return
    content = p.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if keyword in line:
            print(f"\n--- Context in {path} Line {i+1} ---")
            start = max(0, i - 10)
            end = min(len(lines), i + 15)
            for j in range(start, end):
                prefix = "-> " if j == i else "   "
                clean_line = lines[j].encode("ascii", "replace").decode("ascii")
                print(f"{prefix}{j+1}: {clean_line}")

print_context("studies/1m_regime_collector_v2/collector.py", "bar1_confirmed_hh_ll")
print_context("studies/1m_regime_collector_v2/contract/generate_feature_contract_v2.py", "bar1_confirmed_hh_ll")
