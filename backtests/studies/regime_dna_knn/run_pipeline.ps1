$ErrorActionPreference = "Stop"

Write-Host "Running cluster_regime_dna.py..."
python cluster_regime_dna.py

Write-Host "`nRunning build_dna_live_states.py..."
python build_dna_live_states.py

Write-Host "`nRunning score_dna_knn.py..."
python score_dna_knn.py

Write-Host "`nRunning policy_dna_gate.py..."
python policy_dna_gate.py

Write-Host "`nPipeline completed successfully!"
