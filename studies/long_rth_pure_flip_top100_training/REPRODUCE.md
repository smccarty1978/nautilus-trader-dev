# Reproduce

This study halted at the data-availability gate. Only the frozen feature-list
resolution and the blocker verification are reproducible; there is no training
run.

## 1. Reproduce the frozen top-100 list + manifest

```bash
python - <<'PY'
import csv, hashlib, json, collections
src='studies/runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv'
rows=list(csv.DictReader(open(src,newline='',encoding='utf-8')))
assert len(rows)==100
names=[r['feature_name'] for r in rows]
ser=('\n'.join(names)+'\n').encode()
print('feature_source_sha256', hashlib.sha256(open(src,'rb').read()).hexdigest())
print('ordered_feature_list_sha256', hashlib.sha256(ser).hexdigest())
print('families', collections.Counter(r['family'] for r in rows))
PY
```

Expected:
- `feature_source_sha256 = 6c6ceba7d3520e91b0feaed00cd6ab320230e8404e840894190b1cc7e70bc619`
- `ordered_feature_list_sha256 = f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992`
- families: 44 / 29 / 27 (center-slope / ohlcv-delta / price-level)

## 2. Reproduce the blocker (no long-side surface exists)

```bash
# Short-side surface: bearish target, direction==1 population
python -c "import pyarrow.parquet as pq; \
print([n for n in pq.read_schema('studies/short_rth_pure_flip_prediction_enriched/_work/prepared_2025.parquet').names \
if 'flip_within' in n or 'direction' in n])"

# Funnel drops direction != 1
sed -n '69,72p' studies/short_rth_entry_surface_backfill/entry_surface.py

# No bullish label anywhere
grep -rl "bullish_regime_flip_within_300s" studies --include=*.parquet   # returns nothing
```

If a properly-built long-side surface (`direction == -1` population +
`bullish_regime_flip_within_300s` label, 2021–2026) is later produced, the
frozen top-100 list above can be applied to it under train 2021–2024 / dev 2025
/ sealed 2026 with logreg + `HistGradientBoostingClassifier(max_depth=3,
learning_rate=0.05, max_iter=200, random_state=42)`.
