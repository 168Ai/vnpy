"""
底部两连策略回测脚本，只处理5分钟K线数据

策略规则：
1. 最近N根K线整体下跌，MA20向下，且总体跌幅大于2%
2. 最近3根K线中，前两根为实体阳线，第三根为实体阴线
3. 第二根K线的开盘、收盘、最高、最低都高于第一根K线
4. 第三根K线收盘价高于第一根K线开盘价，最低价高于第一根K线最低价
5. 第三根K线量能小于前两根K线最大量能
6. MACD位于零轴下方，且绿柱缩短
7. 信号确认后，下一根5分钟K线开盘做多

止损：最近3根K线最低价
止盈：固定盈亏比1:3
"""

from pathlib import Path

import pandas as pd

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, OrderData, TickData, TradeData
from vnpy_ctastrategy import ArrayManager, BarGenerator, CtaTemplate, StopOrder
from vnpy_ctastrategy.backtesting import BacktestingEngine


class ConservativeBacktestingEngine(BacktestingEngine):
    """先撮合停止单，再撮合限价单，避免止盈止损同K线触发时先按止盈成交。"""

    def new_bar(self, bar: BarData) -> None:
        """K线回放"""
        self.bar = bar
        self.datetime = bar.datetime

        self.cross_stop_order()
        self.cross_limit_order()
        self.strategy.on_bar(bar)

        self.update_daily_close(bar.close_price)


class DibuLianglianStrategy(CtaTemplate):
    """底部止跌确认做多策略"""

    author = "VeighNa"

    drop_window = 20
    drop_threshold = 0.02
    ma_window = 20
    macd_fast = 12
    macd_slow = 26
    macd_signal = 9
    risk_reward = 3
    fixed_size = 1

    entry_price = 0.0
    stop_loss_price = 0.0
    take_profit_price = 0.0
    signal_low = 0.0

    parameters = [
        "drop_window",
        "drop_threshold",
        "ma_window",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "risk_reward",
        "fixed_size",
    ]
    variables = [
        "entry_price",
        "stop_loss_price",
        "take_profit_price",
        "signal_low",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=60)

    def on_init(self) -> None:
        """策略初始化"""
        self.write_log("策略初始化")
        self.load_bar(10)

    def on_start(self) -> None:
        """策略启动"""
        self.write_log("策略启动")

    def on_stop(self) -> None:
        """策略停止"""
        self.write_log("策略停止")

    def on_tick(self, tick: TickData) -> None:
        """Tick数据回调"""
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        """K线数据回调"""
        if self.pos == 0:
            self.cancel_all()

        self.am.update_bar(bar)
        if not self.am.inited:
            return

        if self.pos == 0 and self.check_long_signal():
            self.send_long_order(bar)

        self.put_event()

    def check_long_signal(self) -> bool:
        """检查底部两连确认做多信号"""
        am = self.am

        if not self.check_downtrend():
            return False

        open1, open2, open3 = am.open[-3], am.open[-2], am.open[-1]
        close1, close2, close3 = am.close[-3], am.close[-2], am.close[-1]
        high1, high2 = am.high[-3], am.high[-2]
        low1, low2, low3 = am.low[-3], am.low[-2], am.low[-1]

        if close1 <= open1 or close2 <= open2:
            return False

        if close3 >= open3:
            return False

        if not (open2 > open1 and close2 > close1 and high2 > high1 and low2 > low1):
            return False

        if close3 <= open1:
            return False

        if low3 <= low1:
            return False

        if close2 <= am.close[-4]:
            return False

        if am.volume[-1] >= max(am.volume[-2], am.volume[-3]):
            return False

        if not self.check_macd():
            return False

        return True

    def check_downtrend(self) -> bool:
        """检查最近N根整体下跌、跌幅达标且均线向下"""
        am = self.am
        start_close = am.close[-self.drop_window]
        end_close = am.close[-1]

        if start_close <= 0:
            return False

        drop_rate = (start_close - end_close) / start_close
        if drop_rate < self.drop_threshold:
            return False

        ma_array = am.sma(self.ma_window, array=True)
        if ma_array[-1] >= ma_array[-2]:
            return False

        return True

    def check_macd(self) -> bool:
        """检查MACD零轴下方、绿柱缩短"""
        macd, _signal, hist = self.am.macd(
            self.macd_fast,
            self.macd_slow,
            self.macd_signal,
            array=True,
        )

        if macd[-1] >= 0:
            return False

        if pd.isna(macd[-1]) or pd.isna(hist[-1]) or pd.isna(hist[-2]):
            return False

        if hist[-1] >= 0:
            return False

        if hist[-1] <= hist[-2]:
            return False

        return True

    def send_long_order(self, bar: BarData) -> None:
        """信号确认后提交买单，回测中会在下一根K线开盘撮合"""
        self.signal_low = min(self.am.low[-3], self.am.low[-2], self.am.low[-1])
        self.stop_loss_price = self.signal_low

        # 使用足够高的限价单，确保下一根K线以开盘价成交。
        buy_price = bar.close_price * 1.1
        self.buy(buy_price, self.fixed_size)

    def on_order(self, order: OrderData) -> None:
        """委托回调"""
        pass

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        if trade.offset.value == "开":
            self.entry_price = trade.price
            risk = self.entry_price - self.stop_loss_price
            self.take_profit_price = self.entry_price + risk * self.risk_reward

            if risk <= 0:
                self.sell(trade.price * 0.9, trade.volume)
                self.write_log(
                    f"开多成交后止损无效，等待平仓：{self.entry_price:.2f}, "
                    f"止损：{self.stop_loss_price:.2f}"
                )
                self.put_event()
                return

            self.sell(self.stop_loss_price, trade.volume, stop=True)
            self.sell(self.take_profit_price, trade.volume)
            self.write_log(
                f"开多成交：{self.entry_price:.2f}, "
                f"止损：{self.stop_loss_price:.2f}, "
                f"止盈：{self.take_profit_price:.2f}"
            )
        else:
            self.cancel_all()
            self.reset_trade_vars()

        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """停止单回调"""
        pass

    def reset_trade_vars(self) -> None:
        """重置交易变量"""
        self.entry_price = 0.0
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.signal_low = 0.0


def load_csv_data(file_path: Path, vt_symbol: str) -> pd.DataFrame:
    """读取CSV数据并规范列格式"""
    df = pd.read_csv(file_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")
    df = df.set_index("datetime")
    return df[["open", "high", "low", "close", "volume"]]


def dataframe_to_bars(df: pd.DataFrame, vt_symbol: str) -> list[BarData]:
    """将DataFrame转换为BarData列表"""
    symbol, exchange_str = vt_symbol.split(".")
    exchange = Exchange(exchange_str)
    bars: list[BarData] = []

    for dt, row in df.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=dt.to_pydatetime(),
            interval=Interval.MINUTE,
            volume=row["volume"],
            open_price=row["open"],
            high_price=row["high"],
            low_price=row["low"],
            close_price=row["close"],
            gateway_name="CSV_5m",
        )
        bars.append(bar)

    return bars


def print_trading_records(engine: BacktestingEngine) -> None:
    """打印交易记录"""
    print("\n" + "=" * 88)
    print("5分钟K线交易记录")
    print("=" * 88)

    if not engine.trades:
        print("没有成交记录")
        return

    print(f"{'序号':<6} {'时间':<22} {'方向':<6} {'开平':<6} {'价格':<10} {'数量':<8}")
    print("-" * 88)

    for index, trade in enumerate(engine.trades.values(), 1):
        direction = "买入" if trade.direction.value == "多" else "卖出"
        offset = "开仓" if trade.offset.value == "开" else "平仓"
        print(
            f"{index:<6} {str(trade.datetime):<22} "
            f"{direction:<6} {offset:<6} {trade.price:<10.2f} {trade.volume:<8}"
        )


def run_backtesting(source_df: pd.DataFrame) -> None:
    """执行5分钟K线回测"""
    vt_symbol = "RB0.SHFE"
    bars = dataframe_to_bars(source_df, vt_symbol)

    engine = ConservativeBacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.MINUTE,
        start=bars[0].datetime,
        end=bars[-1].datetime,
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100_000,
    )

    engine.add_strategy(
        DibuLianglianStrategy,
        {
            "drop_window": 20,
            "drop_threshold": 0.02,
            "ma_window": 20,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "risk_reward": 3,
            "fixed_size": 1,
        },
    )
    engine.history_data = bars

    print(f"\n开始执行5分钟K线回测，共{len(bars)}根K线")
    engine.run_backtesting()
    engine.calculate_result()
    engine.calculate_statistics()
    print_trading_records(engine)


if __name__ == "__main__":
    csv_path = Path(__file__).resolve().parents[1] / "data_recorder" / "RB0_5min.csv"
    source_data = load_csv_data(csv_path, "RB0.SHFE")
    run_backtesting(source_data)
