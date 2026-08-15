from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog


class CausalDataLoader:
    """Implements process-local caching of decoded bars from ParquetDataCatalog."""

    # Global process-level cache
    _cache_bars: Dict[Tuple[str, pd.Timestamp, pd.Timestamp], List[Any]] = {}

    def __init__(self, catalog_path: Path):
        self.catalog_path = Path(catalog_path)
        self.catalog = ParquetDataCatalog(str(self.catalog_path))

    def load_bars(self, bar_type: str, start: pd.Timestamp, end: pd.Timestamp) -> List[Any]:
        """Loads bars from catalog, caching them locally in the worker process."""
        cache_key = (bar_type, start, end)
        if cache_key in self._cache_bars:
            return self._cache_bars[cache_key]

        bars = self.catalog.bars(
            bar_types=[bar_type],
            start=start,
            end=end
        )
        # Cache the result
        self._cache_bars[cache_key] = bars
        return bars

    @classmethod
    def clear_cache(cls) -> None:
        """Clears the process-local cache."""
        cls._cache_bars.clear()
