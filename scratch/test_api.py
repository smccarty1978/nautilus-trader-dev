import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.visualizer import app

def test_endpoints():
    client = TestClient(app)
    
    print("Testing GET /api/backtests...")
    res = client.get("/api/backtests")
    print(f"Status: {res.status_code}")
    
    data = res.json()
    backtests = data.get("backtests", [])
    print(f"Found {len(backtests)} backtest directories.")
    
    if backtests:
        first_bt = backtests[0]
        print(f"\nTesting GET /api/backtests/{first_bt['id']}/trades...")
        res_trades = client.get(f"/api/backtests/{first_bt['id']}/trades")
        print(f"Status: {res_trades.status_code}")
        trades_data = res_trades.json()
        trades = trades_data.get("trades", [])
        print(f"Loaded {len(trades)} trades.")
        
        if trades:
            first_trade = trades[0]
            print(f"\nTesting GET /api/backtests/{first_bt['id']}/trades/{first_trade['id']}/candles...")
            res_candles = client.get(f"/api/backtests/{first_bt['id']}/trades/{first_trade['id']}/candles?resolution=5s&padding=15")
            print(f"Status: {res_candles.status_code}")
            candles_data = res_candles.json()
            candles = candles_data.get("candles", [])
            print(f"Loaded {len(candles)} candles.")
            print("Indicators available:", list(candles_data.get("indicators", {}).keys()))

if __name__ == "__main__":
    test_endpoints()
