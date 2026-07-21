from nautilus_trader.config import StrategyConfig

class ExcursionValidationConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    position_size: int = 1
