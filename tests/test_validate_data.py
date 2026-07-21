import pytest
import pandas as pd
from pathlib import Path
from scripts.validate_data import validate_raw_ohlcv

@pytest.fixture
def temp_parquet_file(tmp_path):
    """Fixture to generate a temporary path for a parquet file."""
    return tmp_path / "test_ohlcv.parquet"

def test_validate_raw_ohlcv_valid(temp_parquet_file):
    # Create a valid DataFrame (lowercase columns)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-07-18", periods=5, freq="1s"),
        "open": [100.0, 101.0, 102.0, 103.0, 104.0],
        "high": [105.0, 106.0, 107.0, 108.0, 109.0],
        "low": [95.0, 96.0, 97.0, 98.0, 99.0],
        "close": [101.0, 102.0, 103.0, 104.0, 105.0],
        "volume": [10, 20, 30, 40, 50]
    })
    df.to_parquet(temp_parquet_file)
    
    results = validate_raw_ohlcv(temp_parquet_file)
    assert len(results["issues"]) == 0
    assert results["rows"] == 5
    assert "open" in results["columns"]

def test_validate_raw_ohlcv_missing_columns(temp_parquet_file):
    # Missing Volume column
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-07-18", periods=2, freq="1s"),
        "open": [100.0, 101.0],
        "high": [105.0, 106.0],
        "low": [95.0, 96.0],
        "close": [101.0, 102.0]
    })
    df.to_parquet(temp_parquet_file)
    
    results = validate_raw_ohlcv(temp_parquet_file)
    assert any("Missing columns" in issue for issue in results["issues"])

def test_validate_raw_ohlcv_invalid_hl(temp_parquet_file):
    # Row 1 has High < Low (104.0 < 105.0)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-07-18", periods=2, freq="1s"),
        "open": [100.0, 101.0],
        "high": [105.0, 104.0],
        "low": [95.0, 105.0],
        "close": [101.0, 102.0],
        "volume": [10, 20]
    })
    df.to_parquet(temp_parquet_file)
    
    results = validate_raw_ohlcv(temp_parquet_file)
    assert any("High < Low" in issue for issue in results["issues"])

def test_validate_raw_ohlcv_invalid_open_close(temp_parquet_file):
    # Row 0: Open is higher than High (106.0 > 105.0)
    # Row 1: Close is lower than Low (94.0 < 96.0)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-07-18", periods=2, freq="1s"),
        "open": [106.0, 101.0],
        "high": [105.0, 106.0],
        "low": [95.0, 96.0],
        "close": [101.0, 94.0],
        "volume": [10, 20]
    })
    df.to_parquet(temp_parquet_file)
    
    results = validate_raw_ohlcv(temp_parquet_file)
    assert any("Open outside H/L" in issue for issue in results["issues"])
    assert any("Close outside H/L" in issue for issue in results["issues"])

def test_validate_raw_ohlcv_null_values(temp_parquet_file):
    # Close has a null value
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-07-18", periods=2, freq="1s"),
        "open": [100.0, 101.0],
        "high": [105.0, 106.0],
        "low": [95.0, 96.0],
        "close": [101.0, None],
        "volume": [10, 20]
    })
    df.to_parquet(temp_parquet_file)
    
    results = validate_raw_ohlcv(temp_parquet_file)
    assert any("Null values" in issue for issue in results["issues"])
