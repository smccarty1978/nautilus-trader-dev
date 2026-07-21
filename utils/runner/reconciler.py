import math
from typing import Any, Dict, List, Tuple


class ParityReconciler:
    """Reconciles outputs (features, scores, orders) between offline models and NT strategy."""

    def __init__(self, float_tolerance: float = 1e-6):
        self.float_tolerance = float_tolerance
        self.discrepancies: List[Dict[str, Any]] = []

    def compare_dicts(self, step_id: Any, actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
        """Compares actual vs expected dictionaries. Returns True if matched, False if mismatch."""
        mismatch = {}
        for key, val in expected.items():
            if key not in actual:
                mismatch[key] = {"expected": val, "actual": "missing"}
                continue
            
            act_val = actual[key]
            if isinstance(val, float) and isinstance(act_val, (int, float)):
                if not math.isclose(val, act_val, abs_tol=self.float_tolerance):
                    mismatch[key] = {"expected": val, "actual": act_val}
            elif val != act_val:
                mismatch[key] = {"expected": val, "actual": act_val}

        if mismatch:
            self.discrepancies.append({
                "step_id": step_id,
                "mismatch": mismatch
            })
            return False
        return True

    def get_summary(self) -> str:
        """Returns a string summary of the parity checks."""
        if not self.discrepancies:
            return "PARITY PASS: 100% agreement"
        
        summary = [f"PARITY FAIL: Found {len(self.discrepancies)} discrepancies."]
        for disc in self.discrepancies[:5]:  # Print first 5
            summary.append(f"  Mismatch at Step {disc['step_id']}:")
            for k, diff in disc['mismatch'].items():
                summary.append(f"    - '{k}': expected {diff['expected']}, got {diff['actual']}")
        if len(self.discrepancies) > 5:
            summary.append(f"  ... and {len(self.discrepancies) - 5} more discrepancies.")
        return "\n".join(summary)
