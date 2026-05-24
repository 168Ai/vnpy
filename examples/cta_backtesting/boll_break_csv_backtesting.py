"""
CTA strategy backtesting example - load bar data from CSV.

This script shows how to:
1. Load historical K-line data from a CSV file.
2. Run a Bollinger breakout CTA strategy.
3. Print detailed trade records after backtesting.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, TickData
from vnpy_ctastrategy import ArrayManager, CtaTemplate
from vnpy_ctastrategy.backtesting import BacktestingEngine


class BollBreakCsvStrategy(CtaTemplate):
    """Bollinger breakout strategy for CSV backtesting."""

    author = "VeighNa"

    boll_window = 20
    boll_dev = 2.0
    fixed_size = 1
    price_add = 1

    boll_up = 0.0
    boll_mid = 0.0
    boll_down = 0.0

    parameters = ["boll_window", "boll_dev", "fixed_size", "price_add"]
    variables = ["boll_up", "boll_mid", "boll_down"]

    def __init__(self, cta_engine, strategy_name: str, vt_symbol: str, setting: dict) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.am = ArrayManager(size=max(self.boll_window + 5, 100))

    def on_init(self) -> None:
        """Callback when strategy is initialized."""
        self.write_log("Strategy initialized")

    def on_start(self) -> None:
        """Callback when strategy is started."""
        self.write_log("Strategy started")

    def on_stop(self) -> None:
        """Callback when strategy is stopped."""
        self.write_log("Strategy stopped")

    def on_tick(self, tick: TickData) -> None:
        """Tick data callback."""
        return

    def on_bar(self, bar: BarData) -> None:
        """Bar data callback."""
        self.cancel_all()

        self.am.update_bar(bar)
        if not self.am.inited:
            return

        close_array = self.am.close
        up_array, down_array = self.am.boll(self.boll_window, self.boll_dev, array=True)
        mid_array = self.am.sma(self.boll_window, array=True)

        self.boll_up = up_array[-1]
        self.boll_mid = mid_array[-1]
        self.boll_down = down_array[-1]

        long_signal = close_array[-2] <= up_array[-2] and close_array[-1] > up_array[-1]
        short_signal = close_array[-2] >= down_array[-2] and close_array[-1] < down_array[-1]
        long_exit = close_array[-2] >= mid_array[-2] and close_array[-1] < mid_array[-1]
        short_exit = close_array[-2] <= mid_array[-2] and close_array[-1] > mid_array[-1]

        buy_price = bar.close_price + self.price_add
        sell_price = bar.close_price - self.price_add

        if self.pos == 0:
            if long_signal:
                self.buy(buy_price, self.fixed_size)
            elif short_signal:
                self.short(sell_price, self.fixed_size)
        elif self.pos > 0:
            if short_signal:
                self.sell(sell_price, abs(self.pos))
                self.short(sell_price, self.fixed_size)
            elif long_exit:
                self.sell(sell_price, abs(self.pos))
        else:
            if long_signal:
                self.cover(buy_price, abs(self.pos))
                self.buy(buy_price, self.fixed_size)
            elif short_exit:
                self.cover(buy_price, abs(self.pos))

        self.put_event()


def load_csv_data(
    file_path: str | Path,
    vt_symbol: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[BarData]:
    """
    Load historical bar data from CSV and convert it to BarData objects.

    The CSV file must contain datetime, open, high, low, close and volume columns.
    If the file contains a hold column, it will be used as open_interest.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    df = pd.read_csv(path)

    required_columns = {"datetime", "open", "high", "low", "close", "volume"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"CSV missing required columns: {missing}")

    symbol, exchange_str = vt_symbol.rsplit(".", 1)
    exchange = Exchange(exchange_str)

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")

    if start:
        df = df[df["datetime"] >= start]
    if end:
        df = df[df["datetime"] <= end]

    bars: list[BarData] = []
    for _, row in df.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["datetime"].to_pydatetime(),
            interval=Interval.MINUTE,
            volume=float(row["volume"]),
            open_interest=float(row["hold"]) if "hold" in df.columns else 0,
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            gateway_name="CSV",
        )
        bars.append(bar)

    return bars


def print_trading_records(engine: BacktestingEngine) -> None:
    """Print all trade records generated by the backtest."""
    print("\n" + "=" * 88)
    print("Trade Records")
    print("=" * 88)

    if not engine.trades:
        print("No trade records")
        return

    print(f"{'No.':<6} {'Time':<22} {'Direction':<10} {'Offset':<10} {'Price':<10} {'Volume':<8} {'Amount':<12}")
    print("-" * 88)

    direction_map = {"多": "Buy", "空": "Sell"}
    offset_map = {"开": "Open", "平": "Close", "平今": "CloseToday", "平昨": "CloseYesterday"}

    total_amount = 0.0
    for index, trade in enumerate(engine.trades.values(), 1):
        direction = direction_map.get(trade.direction.value, trade.direction.value)
        offset = offset_map.get(trade.offset.value, trade.offset.value)
        amount = trade.price * trade.volume * engine.size
        total_amount += amount

        print(
            f"{index:<6} "
            f"{str(trade.datetime):<22} "
            f"{direction:<10} "
            f"{offset:<10} "
            f"{trade.price:<10.2f} "
            f"{trade.volume:<8.0f} "
            f"{amount:<12.2f}"
        )

    print("=" * 88)
    print(f"Total trades: {len(engine.trades)}")
    print(f"Total amount: {total_amount:.2f}")
    print("=" * 88 + "\n")


if __name__ == "__main__":
    engine = BacktestingEngine()

    vt_symbol = "RB0.SHFE"
    start = datetime(2026, 4, 28)
    end = datetime(2026, 5, 22)

    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.MINUTE,
        start=start,
        end=end,
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100_000,
    )

    strategy_setting = {
        "boll_window": 20,
        "boll_dev": 2.0,
        "fixed_size": 1,
        "price_add": 1,
    }
    engine.add_strategy(BollBreakCsvStrategy, strategy_setting)

    csv_path = Path(__file__).resolve().parents[1] / "data_recorder" / "RB0_5min.csv"
    bars = load_csv_data(csv_path, vt_symbol, start, end)
    if not bars:
        raise RuntimeError("No historical bars loaded from CSV")

    engine.history_data = bars

    engine.run_backtesting()
    engine.calculate_result()
    engine.calculate_statistics()
    print_trading_records(engine)
