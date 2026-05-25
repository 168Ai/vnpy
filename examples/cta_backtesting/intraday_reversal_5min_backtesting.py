"""
5分钟K线日内反转交易策略回测脚本

策略说明：
1. 只在5分钟K线上运行，默认读取 examples/data_recorder/RB0_5min.csv。
2. 做多：连续快速下跌 -> 止跌K线 -> 向上突破 -> 回踩不破 -> 二次启动开多。
3. 做空：连续快速上涨 -> 滞涨K线 -> 向下突破 -> 回踩不破 -> 二次下跌开空。
4. 入场后使用保护止损、1R减半止盈、剩余仓位用前高/前低或固定盈亏比止盈。
5. 回测结束后打印策略信号日志和全部成交记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from math import floor, isnan
import os
from pathlib import Path

import pandas as pd

# vn.py默认会在当前目录或用户目录下创建.vntrader目录。
# 这里提前在当前运行目录创建，便于脚本在受限环境或示例目录中直接运行。
SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(SCRIPT_DIR)
SCRIPT_DIR.joinpath(".vntrader").mkdir(exist_ok=True)

from vnpy.trader.constant import Direction, Exchange, Interval, Offset
from vnpy.trader.object import BarData, OrderData, TickData, TradeData
from vnpy.trader.utility import round_to
from vnpy_ctastrategy import ArrayManager, CtaTemplate, StopOrder
from vnpy_ctastrategy.backtesting import BacktestingEngine


@dataclass
class BarSnapshot:
    """保存形态识别时的K线信息，避免后续数组滚动影响判断。"""

    datetime: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float


def snapshot_bar(bar: BarData) -> BarSnapshot:
    """把vn.py的BarData转成轻量快照。"""

    return BarSnapshot(
        datetime=bar.datetime,
        open_price=bar.open_price,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
        volume=bar.volume,
    )


class ConservativeBacktestingEngine(BacktestingEngine):
    """先撮合停止单再撮合限价单，避免同一根K线内先止盈后止损的乐观结果。"""

    def new_bar(self, bar: BarData) -> None:
        """K线回放。"""

        self.bar = bar
        self.datetime = bar.datetime

        self.cross_stop_order()
        self.cross_limit_order()
        self.strategy.on_bar(bar)

        self.update_daily_close(bar.close_price)


class IntradayReversal5MinStrategy(CtaTemplate):
    """5分钟K线日内反转策略。"""

    author = "Codex"

    # ---- 信号参数 ----
    fixed_size = 2                   # 默认2手，便于实现50%分批止盈
    max_size = 2                     # 风险控制后的最大下单手数
    risk_percent = 0.01              # 单笔理论风险不超过初始资金1%
    trend_window = 20                # 判断明显趋势的观察窗口
    trend_threshold = 0.002          # 窗口内涨跌幅阈值，0.2%
    ma_window = 20                   # 趋势过滤均线周期
    ma_slope_bars = 3                # 均线斜率比较间隔
    atr_window = 14                  # ATR波动率周期
    min_atr = 1.0                    # ATR过低视为横盘
    max_atr_pct = 0.02               # ATR/价格过高视为异常波动
    min_range_atr = 1.5              # 最近区间振幅至少达到ATR倍数，过滤窄幅震荡

    min_sequence_bars = 2            # 连续阴线/阳线最少根数
    max_sequence_bars = 4            # 连续阴线/阳线最多根数
    min_body_ratio = 0.45            # 趋势K线实体至少占整根K线比例
    min_body_ticks = 1               # 趋势K线实体至少几个tick
    sequence_atr_multiple = 0.8      # 连续K线累计推进至少达到ATR倍数

    small_body_ratio = 0.25          # 小实体/十字星阈值
    shadow_ratio = 0.45              # 长影线阈值
    breakout_wait_bars = 2           # 止跌/滞涨后，最多等待几根K线突破
    pullback_wait_bars = 5           # 突破后，最多等待几根K线回踩和二次启动
    breakout_by_close = True         # 突破确认是否要求收盘价突破
    second_breakout_by_close = True  # 二次启动是否要求收盘价突破
    require_body_half_hold = False   # 回踩是否强制不破突破实体一半

    # ---- 交易参数 ----
    stop_buffer_ticks = 1            # 止损价外扩tick
    entry_price_add_ticks = 5        # 入场限价相对信号收盘价的追价tick
    exit_price_add_ticks = 5         # 主动平仓追价tick
    first_target_rr = 1.0            # 第一目标：1R减仓
    first_target_ratio = 0.5         # 第一目标减仓比例
    final_target_rr = 2.0            # 前高/前低不足时，剩余仓位用2R目标
    target_lookback = 30             # 前高/前低观察窗口
    max_consecutive_losses = 3       # 当天连续亏损达到该次数后停止开仓
    cooldown_bars = 6                # 一次信号结束后冷却K线数量
    force_exit_times = "14:50,22:55" # 日内强平信号时间，订单会在下一根K线成交
    day_no_open_after = "14:45"      # 日盘尾段禁止新开仓
    night_no_open_after = "22:50"    # 夜盘尾段禁止新开仓，默认适配RB到23:00

    # ---- 策略变量 ----
    setup_state = "等待信号"
    entry_price = 0.0
    stop_loss_price = 0.0
    first_target_price = 0.0
    final_target_price = 0.0
    remaining_volume = 0
    consecutive_loss_count = 0
    cooldown_left = 0
    entry_bar_datetime = ""

    parameters = [
        "fixed_size",
        "max_size",
        "risk_percent",
        "trend_window",
        "trend_threshold",
        "ma_window",
        "ma_slope_bars",
        "atr_window",
        "min_atr",
        "max_atr_pct",
        "min_range_atr",
        "min_sequence_bars",
        "max_sequence_bars",
        "min_body_ratio",
        "min_body_ticks",
        "sequence_atr_multiple",
        "small_body_ratio",
        "shadow_ratio",
        "breakout_wait_bars",
        "pullback_wait_bars",
        "breakout_by_close",
        "second_breakout_by_close",
        "require_body_half_hold",
        "stop_buffer_ticks",
        "entry_price_add_ticks",
        "exit_price_add_ticks",
        "first_target_rr",
        "first_target_ratio",
        "final_target_rr",
        "target_lookback",
        "max_consecutive_losses",
        "cooldown_bars",
        "force_exit_times",
        "day_no_open_after",
        "night_no_open_after",
    ]

    variables = [
        "setup_state",
        "entry_price",
        "stop_loss_price",
        "first_target_price",
        "final_target_price",
        "remaining_volume",
        "consecutive_loss_count",
        "cooldown_left",
        "entry_bar_datetime",
    ]

    def __init__(self, cta_engine, strategy_name: str, vt_symbol: str, setting: dict) -> None:
        """策略初始化。"""

        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        array_size = max(self.trend_window, self.ma_window, self.target_lookback, self.atr_window) + 50
        self.am = ArrayManager(size=array_size)

        self.price_tick = 1.0
        self.contract_size = 1.0
        self.current_date = None
        self.trade_pnl = 0.0
        self.entry_volume = 0
        self.first_target_volume = 0
        self.final_target_reference = 0.0
        self.first_target_done = False
        self.active_side = ""
        self.entry_bar_datetime = ""

        self.stop_bar: BarSnapshot | None = None
        self.breakout_bar: BarSnapshot | None = None
        self.pullback_bar: BarSnapshot | None = None
        self.sequence_start_bar: BarSnapshot | None = None
        self.sequence_end_bar: BarSnapshot | None = None
        self.bars_after_stop = 0
        self.bars_after_breakout = 0

    def on_init(self) -> None:
        """策略初始化回调。"""

        self.price_tick = self.get_pricetick()
        self.contract_size = self.get_size()
        self.write_log("策略初始化")

    def on_start(self) -> None:
        """策略启动回调。"""

        self.write_log("策略启动")

    def on_stop(self) -> None:
        """策略停止回调。"""

        self.write_log("策略停止")

    def on_tick(self, tick: TickData) -> None:
        """本策略只处理5分钟K线，Tick回调留空。"""

        return

    def on_bar(self, bar: BarData) -> None:
        """每根5分钟K线收盘后执行一次策略逻辑。"""

        self.am.update_bar(bar)
        self.update_daily_risk_state(bar)

        if not self.am.inited:
            return

        if self.cooldown_left > 0:
            self.cooldown_left -= 1

        # 日内策略：在收盘前一根K线发出平仓单，下一根K线成交。
        if self.is_force_exit_time(bar):
            self.force_flatten(bar, "日内强制平仓")
            self.put_event()
            return

        # 已有持仓时，只管理出场，不再寻找新入场。
        if self.pos != 0:
            if self.entry_bar_datetime == str(bar.datetime):
                self.put_event()
                return
            self.manage_open_position(bar)
            self.put_event()
            return

        # 如果上一根K线发出的入场限价单没有成交，在本根K线收盘后撤掉。
        self.cancel_all()

        if self.trading_stopped_for_day():
            self.reset_setup("连续亏损达到限制，停止当天开仓")
            self.put_event()
            return

        if self.cooldown_left > 0 or self.is_no_open_time(bar):
            self.reset_setup()
            self.put_event()
            return

        self.update_setup_state(bar)
        self.put_event()

    # ----------------------------------------------------------------------
    # 信号识别

    def update_setup_state(self, bar: BarData) -> None:
        """按状态机识别止跌/突破/回踩/二次启动。"""

        if self.setup_state == "等待信号":
            self.check_new_setup(bar)
        elif self.setup_state == "等待向上突破":
            self.check_long_breakout(bar)
        elif self.setup_state == "等待向下突破":
            self.check_short_breakout(bar)
        elif self.setup_state == "等待做多回踩":
            self.check_long_pullback_and_entry(bar)
        elif self.setup_state == "等待做空回踩":
            self.check_short_pullback_and_entry(bar)

    def check_new_setup(self, bar: BarData) -> None:
        """从等待状态开始寻找新的多空反转雏形。"""

        long_sequence = self.find_down_sequence()
        if long_sequence and self.is_downtrend() and self.is_stop_falling_bar():
            self.sequence_start_bar, self.sequence_end_bar = long_sequence
            self.stop_bar = snapshot_bar(bar)
            self.bars_after_stop = 0
            self.setup_state = "等待向上突破"
            self.write_log(
                f"发现止跌K线，等待向上突破：止跌高点={bar.high_price:.2f}，"
                f"止跌低点={bar.low_price:.2f}"
            )
            return

        short_sequence = self.find_up_sequence()
        if short_sequence and self.is_uptrend() and self.is_stalling_bar():
            self.sequence_start_bar, self.sequence_end_bar = short_sequence
            self.stop_bar = snapshot_bar(bar)
            self.bars_after_stop = 0
            self.setup_state = "等待向下突破"
            self.write_log(
                f"发现滞涨K线，等待向下突破：滞涨高点={bar.high_price:.2f}，"
                f"滞涨低点={bar.low_price:.2f}"
            )

    def check_long_breakout(self, bar: BarData) -> None:
        """止跌后等待向上突破确认。"""

        if not self.stop_bar:
            self.reset_setup()
            return

        self.bars_after_stop += 1
        broke_high = bar.high_price > self.stop_bar.high_price
        close_confirmed = bar.close_price > self.stop_bar.high_price

        if broke_high and (close_confirmed or not self.breakout_by_close) and bar.close_price > bar.open_price:
            self.breakout_bar = snapshot_bar(bar)
            self.pullback_bar = None
            self.bars_after_breakout = 0
            self.setup_state = "等待做多回踩"
            self.write_log(
                f"向上突破确认：突破K线低点={bar.low_price:.2f}，"
                f"突破K线高点={bar.high_price:.2f}"
            )
            return

        if bar.low_price < self.stop_bar.low_price - self.stop_buffer_ticks * self.price_tick:
            self.reset_setup("止跌K线低点被跌破，做多形态失效")
            return

        if self.bars_after_stop >= self.breakout_wait_bars:
            self.reset_setup("等待向上突破超时")

    def check_short_breakout(self, bar: BarData) -> None:
        """滞涨后等待向下突破确认。"""

        if not self.stop_bar:
            self.reset_setup()
            return

        self.bars_after_stop += 1
        broke_low = bar.low_price < self.stop_bar.low_price
        close_confirmed = bar.close_price < self.stop_bar.low_price

        if broke_low and (close_confirmed or not self.breakout_by_close) and bar.close_price < bar.open_price:
            self.breakout_bar = snapshot_bar(bar)
            self.pullback_bar = None
            self.bars_after_breakout = 0
            self.setup_state = "等待做空回踩"
            self.write_log(
                f"向下突破确认：突破K线高点={bar.high_price:.2f}，"
                f"突破K线低点={bar.low_price:.2f}"
            )
            return

        if bar.high_price > self.stop_bar.high_price + self.stop_buffer_ticks * self.price_tick:
            self.reset_setup("滞涨K线高点被突破，做空形态失效")
            return

        if self.bars_after_stop >= self.breakout_wait_bars:
            self.reset_setup("等待向下突破超时")

    def check_long_pullback_and_entry(self, bar: BarData) -> None:
        """向上突破后等待回踩不破，再二次启动开多。"""

        if not self.stop_bar or not self.breakout_bar:
            self.reset_setup()
            return

        self.bars_after_breakout += 1
        stop_buffer = self.stop_buffer_ticks * self.price_tick
        body_mid = (self.breakout_bar.open_price + self.breakout_bar.close_price) / 2

        if bar.low_price < self.breakout_bar.low_price - stop_buffer:
            self.reset_setup("回踩跌破突破K线低点，做多形态失效")
            return

        if self.require_body_half_hold and bar.low_price < body_mid:
            self.reset_setup("回踩跌破突破阳线实体一半，做多形态失效")
            return

        if self.pullback_bar:
            trigger_price = self.pullback_bar.high_price
            second_break = bar.high_price > trigger_price
            close_confirmed = bar.close_price > trigger_price
            if second_break and (close_confirmed or not self.second_breakout_by_close):
                self.send_long_entry(bar)
                return

        if self.is_long_pullback_bar(bar):
            self.pullback_bar = snapshot_bar(bar)
            self.write_log(
                f"做多回踩确认：回踩高点={bar.high_price:.2f}，"
                f"回踩低点={bar.low_price:.2f}"
            )
            return

        if self.bars_after_breakout >= self.pullback_wait_bars:
            self.reset_setup("等待做多回踩/二次启动超时")

    def check_short_pullback_and_entry(self, bar: BarData) -> None:
        """向下突破后等待反抽不破，再二次下跌开空。"""

        if not self.stop_bar or not self.breakout_bar:
            self.reset_setup()
            return

        self.bars_after_breakout += 1
        stop_buffer = self.stop_buffer_ticks * self.price_tick
        body_mid = (self.breakout_bar.open_price + self.breakout_bar.close_price) / 2

        if bar.high_price > self.breakout_bar.high_price + stop_buffer:
            self.reset_setup("反抽突破突破K线高点，做空形态失效")
            return

        if self.require_body_half_hold and bar.high_price > body_mid:
            self.reset_setup("反抽突破阴线实体一半，做空形态失效")
            return

        if self.pullback_bar:
            trigger_price = self.pullback_bar.low_price
            second_break = bar.low_price < trigger_price
            close_confirmed = bar.close_price < trigger_price
            if second_break and (close_confirmed or not self.second_breakout_by_close):
                self.send_short_entry(bar)
                return

        if self.is_short_pullback_bar(bar):
            self.pullback_bar = snapshot_bar(bar)
            self.write_log(
                f"做空反抽确认：反抽高点={bar.high_price:.2f}，"
                f"反抽低点={bar.low_price:.2f}"
            )
            return

        if self.bars_after_breakout >= self.pullback_wait_bars:
            self.reset_setup("等待做空反抽/二次下跌超时")

    def find_down_sequence(self) -> tuple[BarSnapshot, BarSnapshot] | None:
        """识别当前止跌K线之前的2到4根连续快速阴线。"""

        am = self.am
        atr = am.atr(self.atr_window)
        if isnan(atr) or atr <= 0:
            return None

        for count in range(self.max_sequence_bars, self.min_sequence_bars - 1, -1):
            start = -count - 1
            end = -2
            valid = True

            for index in range(start, end + 1):
                if not self.is_large_bear_bar(index):
                    valid = False
                    break
                if index > start and am.close[index] >= am.close[index - 1]:
                    valid = False
                    break

            if not valid:
                continue

            total_move = am.open[start] - am.close[end]
            if total_move < atr * self.sequence_atr_multiple:
                continue

            return self.array_bar_snapshot(start), self.array_bar_snapshot(end)

        return None

    def find_up_sequence(self) -> tuple[BarSnapshot, BarSnapshot] | None:
        """识别当前滞涨K线之前的2到4根连续快速阳线。"""

        am = self.am
        atr = am.atr(self.atr_window)
        if isnan(atr) or atr <= 0:
            return None

        for count in range(self.max_sequence_bars, self.min_sequence_bars - 1, -1):
            start = -count - 1
            end = -2
            valid = True

            for index in range(start, end + 1):
                if not self.is_large_bull_bar(index):
                    valid = False
                    break
                if index > start and am.close[index] <= am.close[index - 1]:
                    valid = False
                    break

            if not valid:
                continue

            total_move = am.close[end] - am.open[start]
            if total_move < atr * self.sequence_atr_multiple:
                continue

            return self.array_bar_snapshot(start), self.array_bar_snapshot(end)

        return None

    def is_downtrend(self) -> bool:
        """过滤：整体下跌、均线向下、波动率正常且不是窄幅横盘。"""

        am = self.am
        start_close = am.close[-self.trend_window]
        end_close = am.close[-1]
        if start_close <= 0:
            return False

        drop_rate = (start_close - end_close) / start_close
        if drop_rate < self.trend_threshold:
            return False

        ma = am.sma(self.ma_window, array=True)
        if isnan(ma[-1]) or ma[-1] >= ma[-self.ma_slope_bars]:
            return False

        return self.volatility_filter()

    def is_uptrend(self) -> bool:
        """过滤：整体上涨、均线向上、波动率正常且不是窄幅横盘。"""

        am = self.am
        start_close = am.close[-self.trend_window]
        end_close = am.close[-1]
        if start_close <= 0:
            return False

        rise_rate = (end_close - start_close) / start_close
        if rise_rate < self.trend_threshold:
            return False

        ma = am.sma(self.ma_window, array=True)
        if isnan(ma[-1]) or ma[-1] <= ma[-self.ma_slope_bars]:
            return False

        return self.volatility_filter()

    def volatility_filter(self) -> bool:
        """过滤横盘和异常波动。"""

        am = self.am
        atr = am.atr(self.atr_window)
        close_price = am.close[-1]
        if isnan(atr) or atr < self.min_atr:
            return False

        if close_price <= 0 or atr / close_price > self.max_atr_pct:
            return False

        recent_high = max(am.high[-self.trend_window:])
        recent_low = min(am.low[-self.trend_window:])
        if recent_high - recent_low < atr * self.min_range_atr:
            return False

        return True

    def is_stop_falling_bar(self) -> bool:
        """识别连续下跌后的止跌K线。"""

        am = self.am
        low_not_lower = am.low[-1] >= am.low[-2]
        lower_shadow = min(am.open[-1], am.close[-1]) - am.low[-1]
        bar_range = max(am.high[-1] - am.low[-1], self.price_tick)
        small_body = abs(am.close[-1] - am.open[-1]) / bar_range <= self.small_body_ratio
        long_lower_shadow = lower_shadow / bar_range >= self.shadow_ratio

        return low_not_lower or long_lower_shadow or small_body

    def is_stalling_bar(self) -> bool:
        """识别连续上涨后的滞涨K线。"""

        am = self.am
        high_not_higher = am.high[-1] <= am.high[-2]
        upper_shadow = am.high[-1] - max(am.open[-1], am.close[-1])
        bar_range = max(am.high[-1] - am.low[-1], self.price_tick)
        small_body = abs(am.close[-1] - am.open[-1]) / bar_range <= self.small_body_ratio
        long_upper_shadow = upper_shadow / bar_range >= self.shadow_ratio

        return high_not_higher or long_upper_shadow or small_body

    def is_long_pullback_bar(self, bar: BarData) -> bool:
        """向上突破后的回踩K线。"""

        if not self.breakout_bar:
            return False

        return (
            bar.low_price <= self.breakout_bar.high_price
            or bar.close_price < bar.open_price
            or bar.close_price < self.breakout_bar.close_price
        )

    def is_short_pullback_bar(self, bar: BarData) -> bool:
        """向下突破后的反抽K线。"""

        if not self.breakout_bar:
            return False

        return (
            bar.high_price >= self.breakout_bar.low_price
            or bar.close_price > bar.open_price
            or bar.close_price > self.breakout_bar.close_price
        )

    # ----------------------------------------------------------------------
    # 交易执行和仓位管理

    def send_long_entry(self, bar: BarData) -> None:
        """二次启动后提交开多单。"""

        if not self.stop_bar or not self.breakout_bar:
            self.reset_setup()
            return

        stop_price = min(self.stop_bar.low_price, self.breakout_bar.low_price)
        self.stop_loss_price = self.round_price(stop_price - self.stop_buffer_ticks * self.price_tick)
        risk = bar.close_price - self.stop_loss_price
        volume = self.calculate_order_volume(risk)
        if volume <= 0:
            self.reset_setup("理论风险超过限制，跳过开多")
            return

        self.active_side = "long"
        self.final_target_reference = max(self.am.high[-self.target_lookback:])
        order_price = self.round_price(bar.close_price + self.entry_price_add_ticks * self.price_tick)
        self.buy(order_price, volume)
        self.setup_state = "等待开多成交"
        self.cooldown_left = self.cooldown_bars
        self.write_log(
            f"买点信号：二次启动开多，信号收盘={bar.close_price:.2f}，"
            f"委托价={order_price:.2f}，止损={self.stop_loss_price:.2f}，手数={volume}"
        )

    def send_short_entry(self, bar: BarData) -> None:
        """二次下跌后提交开空单。"""

        if not self.stop_bar or not self.breakout_bar:
            self.reset_setup()
            return

        stop_price = max(self.stop_bar.high_price, self.breakout_bar.high_price)
        self.stop_loss_price = self.round_price(stop_price + self.stop_buffer_ticks * self.price_tick)
        risk = self.stop_loss_price - bar.close_price
        volume = self.calculate_order_volume(risk)
        if volume <= 0:
            self.reset_setup("理论风险超过限制，跳过开空")
            return

        self.active_side = "short"
        self.final_target_reference = min(self.am.low[-self.target_lookback:])
        order_price = self.round_price(bar.close_price - self.entry_price_add_ticks * self.price_tick)
        self.short(order_price, volume)
        self.setup_state = "等待开空成交"
        self.cooldown_left = self.cooldown_bars
        self.write_log(
            f"卖点信号：二次下跌开空，信号收盘={bar.close_price:.2f}，"
            f"委托价={order_price:.2f}，止损={self.stop_loss_price:.2f}，手数={volume}"
        )

    def on_trade(self, trade: TradeData) -> None:
        """成交回调：开仓后挂止损/止盈，平仓后统计盈亏。"""

        if trade.offset == Offset.OPEN:
            self.handle_entry_trade(trade)
        else:
            self.handle_exit_trade(trade)

        self.put_event()

    def handle_entry_trade(self, trade: TradeData) -> None:
        """开仓成交后设置分批止盈和保护止损。"""

        self.entry_price = trade.price
        self.entry_bar_datetime = str(trade.datetime)
        self.entry_volume = int(trade.volume)
        self.remaining_volume = int(trade.volume)
        self.trade_pnl = 0.0
        self.first_target_done = False

        if trade.direction == Direction.LONG:
            self.active_side = "long"
            risk = self.entry_price - self.stop_loss_price
            self.first_target_price = self.round_price(self.entry_price + risk * self.first_target_rr)
            fallback_target = self.entry_price + risk * self.final_target_rr
            self.final_target_price = self.round_price(max(self.final_target_reference, fallback_target))
            self.sell(self.stop_loss_price, self.remaining_volume, stop=True)
            self.write_log(
                f"开多成交：成交价={self.entry_price:.2f}，止损={self.stop_loss_price:.2f}，"
                f"1R止盈={self.first_target_price:.2f}，最终止盈={self.final_target_price:.2f}"
            )
            self.send_first_target_order()
        else:
            self.active_side = "short"
            risk = self.stop_loss_price - self.entry_price
            self.first_target_price = self.round_price(self.entry_price - risk * self.first_target_rr)
            fallback_target = self.entry_price - risk * self.final_target_rr
            self.final_target_price = self.round_price(min(self.final_target_reference, fallback_target))
            self.cover(self.stop_loss_price, self.remaining_volume, stop=True)
            self.write_log(
                f"开空成交：成交价={self.entry_price:.2f}，止损={self.stop_loss_price:.2f}，"
                f"1R止盈={self.first_target_price:.2f}，最终止盈={self.final_target_price:.2f}"
            )
            self.send_first_target_order()

        self.reset_setup()

    def send_first_target_order(self) -> None:
        """挂出第一目标止盈单。"""

        if self.remaining_volume <= 0:
            return

        self.first_target_volume = max(1, int(self.remaining_volume * self.first_target_ratio))
        self.first_target_volume = min(self.first_target_volume, self.remaining_volume)

        if self.active_side == "long":
            self.sell(self.first_target_price, self.first_target_volume)
        elif self.active_side == "short":
            self.cover(self.first_target_price, self.first_target_volume)

    def send_final_exit_orders(self) -> None:
        """第一目标成交后，为剩余仓位重新挂保护止损和最终目标。"""

        if self.remaining_volume <= 0:
            return

        if self.active_side == "long":
            self.sell(self.stop_loss_price, self.remaining_volume, stop=True)
            self.sell(self.final_target_price, self.remaining_volume)
        elif self.active_side == "short":
            self.cover(self.stop_loss_price, self.remaining_volume, stop=True)
            self.cover(self.final_target_price, self.remaining_volume)

    def handle_exit_trade(self, trade: TradeData) -> None:
        """处理平仓成交、分批止盈和连续亏损统计。"""

        close_volume = int(trade.volume)
        self.remaining_volume -= close_volume

        if self.active_side == "long":
            self.trade_pnl += (trade.price - self.entry_price) * close_volume * self.contract_size
        elif self.active_side == "short":
            self.trade_pnl += (self.entry_price - trade.price) * close_volume * self.contract_size

        if self.remaining_volume > 0 and not self.first_target_done:
            self.first_target_done = True
            self.cancel_all()
            self.write_log(
                f"第一目标成交，剩余仓位={self.remaining_volume}，"
                f"重新挂止损={self.stop_loss_price:.2f}和最终止盈={self.final_target_price:.2f}"
            )
            self.send_final_exit_orders()
            return

        self.cancel_all()
        result_text = "盈利" if self.trade_pnl >= 0 else "亏损"
        if self.trade_pnl < 0:
            self.consecutive_loss_count += 1
        else:
            self.consecutive_loss_count = 0

        self.write_log(
            f"平仓完成：本轮{result_text}={self.trade_pnl:.2f}，"
            f"当天连续亏损={self.consecutive_loss_count}"
        )
        self.reset_trade_vars()
        self.cooldown_left = self.cooldown_bars

    def manage_open_position(self, bar: BarData) -> None:
        """持仓中检查反向K线或长影线衰竭信号。"""

        if self.active_side == "long" and self.is_long_exhaustion_bar():
            self.force_flatten(bar, "多头出现反向/长上影衰竭")
        elif self.active_side == "short" and self.is_short_exhaustion_bar():
            self.force_flatten(bar, "空头出现反向/长下影衰竭")

    def force_flatten(self, bar: BarData, reason: str) -> None:
        """主动平仓，回测中会在下一根K线撮合成交。"""

        if self.pos == 0:
            return

        self.cancel_all()
        if self.pos > 0:
            order_price = self.round_price(bar.close_price - self.exit_price_add_ticks * self.price_tick)
            self.sell(order_price, abs(self.pos))
            self.write_log(f"卖点信号：{reason}，平多委托价={order_price:.2f}")
        else:
            order_price = self.round_price(bar.close_price + self.exit_price_add_ticks * self.price_tick)
            self.cover(order_price, abs(self.pos))
            self.write_log(f"买点信号：{reason}，平空委托价={order_price:.2f}")

    def calculate_order_volume(self, risk_per_unit: float) -> int:
        """按照固定手数和1%风险上限共同决定下单手数。"""

        if risk_per_unit <= 0:
            return 0

        capital = getattr(self.cta_engine, "capital", 0)
        if capital <= 0:
            return min(self.fixed_size, self.max_size)

        risk_capital = capital * self.risk_percent
        risk_per_lot = risk_per_unit * self.contract_size
        risk_size = floor(risk_capital / risk_per_lot)

        return max(0, min(self.fixed_size, self.max_size, risk_size))

    # ----------------------------------------------------------------------
    # 风控和辅助函数

    def update_daily_risk_state(self, bar: BarData) -> None:
        """按自然日重置当天连续亏损计数。"""

        bar_date = bar.datetime.date()
        if self.current_date != bar_date:
            self.current_date = bar_date
            self.consecutive_loss_count = 0

    def trading_stopped_for_day(self) -> bool:
        """当天连续亏损达到限制后停止开仓。"""

        return self.consecutive_loss_count >= self.max_consecutive_losses

    def is_force_exit_time(self, bar: BarData) -> bool:
        """是否到达日内强制平仓发单时间。"""

        return bar.datetime.strftime("%H:%M") in self.parse_time_text(self.force_exit_times)

    def is_no_open_time(self, bar: BarData) -> bool:
        """日盘/夜盘收盘前不再开新仓。"""

        current_time = bar.datetime.time()
        day_after = self.parse_single_time(self.day_no_open_after)
        night_after = self.parse_single_time(self.night_no_open_after)

        if day_after <= current_time < time(15, 0):
            return True
        if night_after <= current_time <= time(23, 59):
            return True
        return False

    def parse_time_text(self, text: str) -> set[str]:
        """解析逗号分隔的HH:MM时间列表。"""

        return {item.strip() for item in text.split(",") if item.strip()}

    def parse_single_time(self, text: str) -> time:
        """解析单个HH:MM时间。"""

        hour, minute = text.split(":")
        return time(int(hour), int(minute))

    def is_large_bear_bar(self, index: int) -> bool:
        """实体较大的阴线。"""

        am = self.am
        body = am.open[index] - am.close[index]
        bar_range = am.high[index] - am.low[index]
        if body <= 0 or bar_range <= 0:
            return False

        return (
            body >= self.min_body_ticks * self.price_tick
            and body / bar_range >= self.min_body_ratio
        )

    def is_large_bull_bar(self, index: int) -> bool:
        """实体较大的阳线。"""

        am = self.am
        body = am.close[index] - am.open[index]
        bar_range = am.high[index] - am.low[index]
        if body <= 0 or bar_range <= 0:
            return False

        return (
            body >= self.min_body_ticks * self.price_tick
            and body / bar_range >= self.min_body_ratio
        )

    def is_long_exhaustion_bar(self) -> bool:
        """多头持仓中的反向阴线或长上影衰竭。"""

        am = self.am
        bar_range = max(am.high[-1] - am.low[-1], self.price_tick)
        body_ratio = abs(am.close[-1] - am.open[-1]) / bar_range
        upper_shadow = am.high[-1] - max(am.open[-1], am.close[-1])
        strong_bear = am.close[-1] < am.open[-1] and body_ratio >= self.min_body_ratio
        long_upper_shadow = upper_shadow / bar_range >= self.shadow_ratio

        return strong_bear or long_upper_shadow

    def is_short_exhaustion_bar(self) -> bool:
        """空头持仓中的反向阳线或长下影衰竭。"""

        am = self.am
        bar_range = max(am.high[-1] - am.low[-1], self.price_tick)
        body_ratio = abs(am.close[-1] - am.open[-1]) / bar_range
        lower_shadow = min(am.open[-1], am.close[-1]) - am.low[-1]
        strong_bull = am.close[-1] > am.open[-1] and body_ratio >= self.min_body_ratio
        long_lower_shadow = lower_shadow / bar_range >= self.shadow_ratio

        return strong_bull or long_lower_shadow

    def array_bar_snapshot(self, index: int) -> BarSnapshot:
        """从ArrayManager中提取某根K线的快照。"""

        am = self.am
        # ArrayManager不保存datetime，这里用当前时间占位；价格信息才参与后续计算。
        return BarSnapshot(
            datetime=datetime.min,
            open_price=float(am.open[index]),
            high_price=float(am.high[index]),
            low_price=float(am.low[index]),
            close_price=float(am.close[index]),
            volume=float(am.volume[index]),
        )

    def round_price(self, price: float) -> float:
        """按最小变动价位取整。"""

        return round_to(price, self.price_tick)

    def reset_setup(self, reason: str = "") -> None:
        """重置未成交的形态状态。"""

        if reason:
            self.write_log(reason)

        self.setup_state = "等待信号"
        self.stop_bar = None
        self.breakout_bar = None
        self.pullback_bar = None
        self.sequence_start_bar = None
        self.sequence_end_bar = None
        self.bars_after_stop = 0
        self.bars_after_breakout = 0

    def reset_trade_vars(self) -> None:
        """重置持仓相关变量。"""

        self.entry_price = 0.0
        self.stop_loss_price = 0.0
        self.first_target_price = 0.0
        self.final_target_price = 0.0
        self.remaining_volume = 0
        self.entry_volume = 0
        self.first_target_volume = 0
        self.final_target_reference = 0.0
        self.first_target_done = False
        self.active_side = ""
        self.entry_bar_datetime = ""
        self.trade_pnl = 0.0

    def on_order(self, order: OrderData) -> None:
        """委托回调。"""

        return

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """停止单回调。"""

        return


def load_csv_data(
    file_path: str | Path,
    vt_symbol: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[BarData]:
    """从CSV加载5分钟K线，并转换为vn.py回测引擎需要的BarData列表。"""

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV文件不存在：{path}")

    df = pd.read_csv(path)
    required_columns = {"datetime", "open", "high", "low", "close", "volume"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"CSV缺少必要字段：{missing}")

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")

    if start:
        df = df[df["datetime"] >= start]
    if end:
        df = df[df["datetime"] <= end]

    symbol, exchange_str = vt_symbol.rsplit(".", 1)
    exchange = Exchange(exchange_str)
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


def print_strategy_logs(engine: BacktestingEngine) -> None:
    """打印策略记录的买卖点和风控日志。"""

    print("\n" + "=" * 100)
    print("策略买卖点日志")
    print("=" * 100)

    if not engine.logs:
        print("没有策略日志")
        return

    keywords = ("买点", "卖点", "开多", "开空", "平仓", "止跌", "滞涨", "突破", "回踩", "反抽", "失效")
    for log in engine.logs:
        if any(keyword in log for keyword in keywords):
            print(log)


def print_trading_records(engine: BacktestingEngine) -> None:
    """打印回测成交记录。"""

    print("\n" + "=" * 100)
    print("交易记录详情")
    print("=" * 100)

    if not engine.trades:
        print("没有成交记录")
        return

    print(f"{'序号':<6} {'时间':<22} {'方向':<6} {'开平':<6} {'价格':<10} {'数量':<8} {'成交金额':<12}")
    print("-" * 100)

    total_amount = 0.0
    for index, trade in enumerate(engine.trades.values(), 1):
        direction = "买入" if trade.direction == Direction.LONG else "卖出"
        offset = "开仓" if trade.offset == Offset.OPEN else "平仓"
        amount = trade.price * trade.volume * engine.size
        total_amount += amount
        print(
            f"{index:<6} "
            f"{str(trade.datetime):<22} "
            f"{direction:<6} "
            f"{offset:<6} "
            f"{trade.price:<10.2f} "
            f"{trade.volume:<8.0f} "
            f"{amount:<12.2f}"
        )

    print("=" * 100)
    print(f"总成交笔数：{len(engine.trades)}")
    print(f"总成交金额：{total_amount:.2f}")
    print("=" * 100 + "\n")


def run_backtesting() -> BacktestingEngine:
    """执行回测并返回回测引擎，便于后续查看结果。"""

    vt_symbol = "RB0.SHFE"
    start = datetime(2026, 4, 28)
    end = datetime(2026, 5, 22)
    csv_path = Path(__file__).resolve().parents[1] / "data_recorder" / "RB0_5min.csv"

    bars = load_csv_data(csv_path, vt_symbol, start, end)
    if not bars:
        raise RuntimeError("CSV中没有可用于回测的K线数据")

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

    strategy_setting = {
        "fixed_size": 2,
        "max_size": 2,
        "risk_percent": 0.01,
        "trend_window": 20,
        "trend_threshold": 0.002,
        "ma_window": 20,
        "atr_window": 14,
        "min_atr": 1.0,
        "first_target_rr": 1.0,
        "final_target_rr": 2.0,
        "cooldown_bars": 6,
        "force_exit_times": "14:50,22:55",
    }
    engine.add_strategy(IntradayReversal5MinStrategy, strategy_setting)
    engine.history_data = bars

    print(f"开始执行5分钟K线日内反转策略回测，K线数量：{len(bars)}")
    engine.run_backtesting()
    engine.calculate_result()
    engine.calculate_statistics()
    print_strategy_logs(engine)
    print_trading_records(engine)

    return engine


if __name__ == "__main__":
    run_backtesting()
