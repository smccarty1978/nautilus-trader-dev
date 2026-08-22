from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog


class CausalDataLoader:
    """Implements process-local caching of decoded bars from ParquetDataCatalog."""

    # Global process-level cache, keyed by resolved catalog identity + bar_type/start/end.
    # A2.3: the key previously omitted catalog identity entirely -- (bar_type, start, end)
    # -- so two loaders opened against different physical catalogs but queried with the
    # same bar_type/start/end would silently share cached bars from whichever catalog
    # populated the cache first. Keying on the resolved catalog path closes that.
    _cache_bars: Dict[Tuple[str, str, pd.Timestamp, pd.Timestamp], List[Any]] = {}

    def __init__(self, catalog_path: Path):
        self.catalog_path = Path(catalog_path).resolve()
        self.catalog = ParquetDataCatalog(str(self.catalog_path))

    def load_bars(self, bar_type: str, start: pd.Timestamp, end: pd.Timestamp) -> List[Any]:
        """Loads bars from catalog, caching them locally in the worker process."""
        cache_key = (self.catalog_path.as_posix(), bar_type, start, end)
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
