@echo off
set ERRORLEVEL=0

echo Running cluster_regime_dna.py...
python backtests\studies\regime_dna_knn\cluster_regime_dna.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo Running build_dna_live_states.py...
python backtests\studies\regime_dna_knn\build_dna_live_states.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo Running score_dna_knn.py...
python backtests\studies\regime_dna_knn\score_dna_knn.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo Running policy_dna_gate.py...
python backtests\studies\regime_dna_knn\policy_dna_gate.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo Pipeline completed successfully!
