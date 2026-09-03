
import hashlib, json, sys, time
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, sys.argv[3])
from research_workflow.model_store import ModelLineage, store_model
from research.analysis.modeling import _build_estimator
MR = Path(sys.argv[1]); barrier = float(sys.argv[2])
rng = np.random.default_rng(5)
FE = ["f_a", "f_b"]
fr = pd.DataFrame({c: rng.normal(size=300) for c in FE})
y = (fr["f_a"] > 0).astype(int)
est = _build_estimator("lightgbm", 42, {"n_estimators": 15, "max_depth": 2, "num_leaves": 4, "learning_rate": 0.1, "verbosity": -1})
est.fit(fr[FE], y)
lin = ModelLineage(study_id="race", cell_id="c", direction="both", target_arm="a", fold_id="final", config_id="C00",
                   seed=42, ordered_inputs=list(FE),
                   feature_contract_sha256=hashlib.sha256(json.dumps(list(FE)).encode()).hexdigest(),
                   preprocessing_contract_sha256="identity", target_contract_sha256="t"*64,
                   target_frame_identity="p"*64, training_population_identity="p"*64,
                   train_years=[2029], validation_years=[], hyperparameters={}, family="lightgbm", model_role="primary")
mid = hashlib.sha256(json.dumps(lin.__dict__, sort_keys=True, default=str).encode()).hexdigest()
while time.time() < barrier:
    pass
try:
    m = store_model(model_id=mid, estimator=est, lineage=lin, tier="registry", selection_status="selected",
                    metrics={}, golden_train_frame=fr[FE], model_root=MR, golden_rows=300)
    print(json.dumps({"ok": True, "model_id": mid, "byte": m["canonical"]["byte_sha256"]}))
except Exception as exc:
    print(json.dumps({"ok": False, "err": type(exc).__name__ + ": " + str(exc)[:150]}))
