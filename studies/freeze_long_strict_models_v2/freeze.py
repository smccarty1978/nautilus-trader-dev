from pathlib import Path
import hashlib, json, shutil

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"studies"/"long_rth_strict_symmetric_retrain"/"artifacts"/"models"
DST=Path(__file__).resolve().parent/"artifacts"
MODELS={"LONG_STRICT_top25_gbt_v2":"FROZEN_CHALLENGER","LONG_STRICT_top103_gbt_v2":"PRODUCTION"}
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    DST.mkdir(parents=True,exist_ok=True); catalog={}
    for model_id,status in MODELS.items():
        src=SRC/model_id; dst=DST/model_id
        if dst.exists(): raise RuntimeError(f"refusing overwrite: {dst}")
        shutil.copytree(src,dst)
        files={p.name:sha(p) for p in sorted(dst.iterdir()) if p.is_file()}
        manifest=json.loads((dst/"manifest.json").read_text())
        freeze={"model_id":model_id,"deployment_status":status,"source_path":str(src),"source_model_hash":manifest["model_hash"],"files":files,"immutable":True}
        (dst/"freeze_manifest.json").write_text(json.dumps(freeze,indent=2)+"\n")
        catalog[model_id]=freeze
    (Path(__file__).resolve().parent/"production_catalog.json").write_text(json.dumps({"production_model":"LONG_STRICT_top103_gbt_v2","challenger_model":"LONG_STRICT_top25_gbt_v2","models":catalog},indent=2)+"\n")
if __name__=="__main__": main()
