import os
import sys

def run(cmd):
    print(f"Running: {cmd}")
    ret = os.system(cmd)
    if ret != 0:
        print(f"Command failed with exit code {ret}")
        sys.exit(ret)

def main():
    run("python cluster_regime_dna.py")
    run("python build_dna_live_states.py")
    run("python score_dna_knn.py")
    run("python policy_dna_gate.py")
    print("Pipeline completed successfully!")

if __name__ == "__main__":
    main()
