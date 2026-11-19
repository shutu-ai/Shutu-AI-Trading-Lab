# Runnable variant of docs/getting_started/backtest_low_level.py (clone @ 8a4ac22, nautilus_trader 2.0.0rc9).
# ONLY delta vs the verbatim copy (backtest_low_level_copy.py):
#   - the three report calls are wrapped in print(...) because this is run as a plain
#     script (the docs example targets Jupyter where the last expression is displayed).
#   - engine.reset()/engine.dispose() calls are no-ops kept verbatim.
# Data: TEST_DATA_ROOT_PATH env var points TestDataProvider at the local clone's
# test_data/ directory so the run is offline and deterministic.
from decimal import Decimal

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LogLevel
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import ExecutionAlgorithmConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.config import StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import AccountType
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import Currency
from nautilus_trader.model import ExecAlgorithmId
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import Money
from nautilus_trader.model import OmsType
from nautilus_trader.model import OrderSide
from nautilus_trader.model import TraderId
from nautilus_trader.model import Venue
from nautilus_trader.testkit.providers import TestDataProvider
from nautilus_trader.testkit.providers import TestInstrumentProvider
from nautilus_trader.trading import Strategy


# Load data
ETHUSDT_BINANCE = TestInstrumentProvider.ethusdt_binance()

ticks = TestDataProvider.trades_from_binance_csv(
    ETHUSDT_BINANCE,
    "binance/ethusdt-trades.csv",
)

# Initialize the engine
config = BacktestEngineConfig(
    trader_id=TraderId("BACKTESTER-001"),
    logging=LoggerConfig(stdout_level=LogLevel.ERROR),
)

engine = BacktestEngine(config=config)

# Add a venue
BINANCE = Venue("BINANCE")
engine.add_venue(
    venue=BINANCE,
    oms_type=OmsType.NETTING,
    account_type=AccountType.CASH,  # Spot CASH account (not for perpetuals or futures)
    base_currency=None,  # Multi-currency account
    starting_balances=[
        Money(1_000_000.0, Currency.from_str("USDT")),
        Money(10.0, Currency.from_str("ETH")),
    ],
    fee_model=MakerTakerFeeModel(
        maker_rate=Decimal("0.0001"),
        taker_rate=Decimal("0.0001"),
    ),
)

# Add data
engine.add_instrument(ETHUSDT_BINANCE)
engine.add_data(ticks)


# Add strategies
class EMACrossTWAPConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        trade_size: Decimal,
        fast_ema_period: int = 10,
        slow_ema_period: int = 20,
        twap_horizon_secs: float = 10.0,
        twap_interval_secs: float = 2.5,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.trade_size = trade_size
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.twap_horizon_secs = twap_horizon_secs
        self.twap_interval_secs = twap_interval_secs


class EMACrossTWAP(Strategy):
    def __init__(self, config: EMACrossTWAPConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(config.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_ema_period)
        self.exec_algorithm_id = ExecAlgorithmId("TWAP")

        self.exec_algorithm_params = {
            "horizon_secs": str(config.twap_horizon_secs),
            "interval_secs": str(config.twap_interval_secs),
        }

    def on_start(self) -> None:
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, _bar: Bar) -> None:
        if not self.indicators_initialized():
            return

        if self.fast_ema.value >= self.slow_ema.value:
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.buy()
            elif self.portfolio.is_net_short(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.buy()
        elif self.fast_ema.value < self.slow_ema.value:
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.sell()
            elif self.portfolio.is_net_long(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.sell()

    def buy(self) -> None:
        self.submit_twap_order(OrderSide.BUY)

    def sell(self) -> None:
        self.submit_twap_order(OrderSide.SELL)

    def submit_twap_order(self, side: OrderSide) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        order = self.order_factory.market(
            self.config.instrument_id,
            side,
            instrument.make_qty(self.config.trade_size),
            exec_algorithm_id=self.exec_algorithm_id,
            exec_algorithm_params=self.exec_algorithm_params,
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)


strategy_config = EMACrossTWAPConfig(
    instrument_id=ETHUSDT_BINANCE.id,
    bar_type=BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL"),
    trade_size=Decimal("0.10"),
    fast_ema_period=10,
    slow_ema_period=20,
    twap_horizon_secs=10.0,
    twap_interval_secs=2.5,
)

strategy = EMACrossTWAP(config=strategy_config)
engine.add_strategy(strategy=strategy)

# Add the native TWAP execution algorithm
engine.add_native_exec_algorithm(
    "TwapAlgorithm",
    ExecutionAlgorithmConfig(exec_algorithm_id=ExecAlgorithmId("TWAP")),
)

# Run the engine (from start to end of data)
import time as _time

_t0 = _time.perf_counter()
engine.run()
_wall = _time.perf_counter() - _t0

# Post-run analysis (printed for non-Jupyter capture)
print("=== account report ===")
print(engine.generate_account_report(BINANCE))
print("=== order fills report ===")
print(engine.generate_order_fills_report())
print("=== positions report ===")
print(engine.generate_positions_report())
print(f"=== engine.run() wall time: {_wall:.3f}s ===")

engine.reset()
engine.dispose()
