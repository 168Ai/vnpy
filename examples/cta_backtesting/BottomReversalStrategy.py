"""
底部止跌确认做多策略

策略逻辑：
1. 最近N根K线总体下跌（首尾比较），均线向下趋势，且总体跌幅大于2%
2. 最近3根K线的前面两根K线必须是连续实体阳线，第三根K线是实体阴线
3. 第二根K线的OHLC都大于第一根K线
4. 第3根K线的收盘价大于第一根K线的开盘价，最低价大于第一根K线的最低价
5. 第3根K线量能 < 前面两根K线的最大量能
6. MACD绿柱缩短且位于零轴下方
7. 第三根K线收盘后不破位就是确认做多

止损：放在最近3根K线的最低价处
止盈：固定盈亏比1:3
"""

from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager
)


class BottomReversalStrategy(CtaTemplate):
    """底部止跌确认做多策略"""
    
    author = "VeighNa"
    
    # 策略参数
    drop_count = 30              # 观察下跌的K线数量窗口
    drop_threshold = 0.005       # 总体跌幅阈值（0.5%）
    ma_length = 20              # 均线周期
    macd_fast = 12              # MACD快线周期
    macd_slow = 26              # MACD慢线周期
    macd_signal = 9             # MACD信号线周期
    risk_reward_ratio = 3       # 盈亏比（1:3）
    
    # 策略变量
    entry_price = 0.0           # 入场价格
    stop_loss_price = 0.0       # 止损价格
    take_profit_price = 0.0     # 止盈价格
    signal_bar_low = 0.0        # 信号K线最低价
    
    parameters = [
        "drop_count",
        "drop_threshold",
        "ma_length",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "risk_reward_ratio"
    ]
    
    variables = [
        "entry_price",
        "stop_loss_price",
        "take_profit_price",
        "signal_bar_low"
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=100)
        
    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")
        self.load_bar(10)
        
    def on_start(self):
        """
        Callback when strategy is started.
        """
        self.write_log("策略启动")
        
    def on_stop(self):
        """
        Callback when strategy is stopped.
        """
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        """
        Callback of new tick data update.
        """
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """
        Callback of new bar data update.
        """
        self.cancel_all()
        
        am = self.am
        am.update_bar(bar)
        
        if not am.inited:
            return
        
        # 如果已有持仓，管理止损止盈
        if self.pos != 0:
            self.manage_position(bar)
            return
        
        # 检查是否满足做多条件
        if self.check_long_condition():
            # 记录入场信息
            self.entry_price = bar.close_price
            self.signal_bar_low = am.low[-3]  # 最近3根K线的最低价
            
            # 计算止损和止盈价格
            stop_distance = self.entry_price - self.signal_bar_low
            self.stop_loss_price = self.signal_bar_low
            self.take_profit_price = self.entry_price + (stop_distance * self.risk_reward_ratio)
            
            # 在下一根K线开盘时入场
            self.buy(bar.close_price, 1)
            
            self.write_log(f"触发做多信号，入场价: {self.entry_price:.2f}, "
                          f"止损: {self.stop_loss_price:.2f}, "
                          f"止盈: {self.take_profit_price:.2f}")
        
        self.put_event()
    
    def check_long_condition(self) -> bool:
        """
        检查是否满足做多条件
        """
        am = self.am
        
        # 获取最近的K线数据
        closes = am.close
        opens = am.open
        highs = am.high
        lows = am.low
        volumes = am.volume
        
        # 1. 检查最近N根K线总体下跌（首尾比较），且跌幅大于阈值
        if not self.check_overall_drop(closes, self.drop_count, self.drop_threshold):
            return False
        
        # 2. 检查均线向下趋势
        ma_current = am.sma(self.ma_length)
        ma_previous = am.sma(self.ma_length, array=True)[-2]
        if ma_current >= ma_previous:
            return False
        
        # 3. 检查最近3根K线的形态
        if not self.check_three_bar_pattern(opens, closes, highs, lows):
            return False
        
        # 4. 检查量能条件：第3根K线量能 < 前两根的最大量能
        current_volume = volumes[-1]
        max_prev_volume = max(volumes[-2], volumes[-3])
        if current_volume >= max_prev_volume:
            return False
        
        # 5. 检查MACD条件
        if not self.check_macd_condition():
            return False
        
        return True
    
    def check_overall_drop(self, closes: list, count: int, threshold: float) -> bool:
        """
        检查最近count根K线是否总体下跌（首尾比较）
        
        Args:
            closes: 收盘价数组
            count: 观察的K线数量
            threshold: 跌幅阈值
            
        Returns:
            bool: 如果总体跌幅超过阈值返回True
        """
        # 比较count根K线前的收盘价和当前收盘价
        start_price = closes[-count-1]
        end_price = closes[-1]
        
        # 计算跌幅
        drop_rate = (start_price - end_price) / start_price
        
        # 检查是否为下跌且跌幅超过阈值
        return drop_rate >= threshold
    
    def check_three_bar_pattern(self, opens, closes, highs, lows) -> bool:
        """
        检查最近3根K线的形态：
        - 前两根是实体阳线
        - 第三根是实体阴线
        - 第二根的OHLC都大于第一根
        - 第三根收盘价 > 第一根开盘价
        - 第三根最低价 > 第一根最低价
        """
        # 第一根K线（倒数第3根）
        open1, close1, high1, low1 = opens[-3], closes[-3], highs[-3], lows[-3]
        # 第二根K线（倒数第2根）
        open2, close2, high2, low2 = opens[-2], closes[-2], highs[-2], lows[-2]
        # 第三根K线（最后一根）
        open3, close3, high3, low3 = opens[-1], closes[-1], highs[-1], lows[-1]
        
        # 检查前两根是实体阳线（收盘价 > 开盘价）
        if close1 <= open1 or close2 <= open2:
            return False
        
        # 检查第三根是实体阴线（收盘价 < 开盘价）
        if close3 >= open3:
            return False
        
        # 检查第二根的OHLC都大于第一根
        if not (open2 > open1 and close2 > close1 and high2 > high1 and low2 > low1):
            return False
        
        # 检查第三根收盘价 > 第一根开盘价
        if close3 <= open1:
            return False
        
        # 检查第三根最低价 > 第一根最低价
        if low3 <= low1:
            return False
        
        return True
    
    def check_macd_condition(self) -> bool:
        """
        检查MACD条件：
        - MACD位于零轴下方
        - MACD绿柱缩短
        """
        macd, signal, hist = self.am.macd(
            self.macd_fast, 
            self.macd_slow, 
            self.macd_signal, 
            array=True
        )
        
        current_macd = macd[-1]
        current_hist = hist[-1]
        prev_hist = hist[-2]
        
        # MACD位于零轴下方
        if current_macd >= 0:
            return False
        
        # MACD绿柱缩短（hist为负值，缩短意味着绝对值变小，即current_hist更接近0）
        # 当hist为负时，current_hist > prev_hist 表示更接近零（柱子变短）
        if current_hist <= prev_hist:
            return False
        
        return True
    
    def manage_position(self, bar: BarData):
        """
        管理持仓：止损和止盈
        """
        # 止损
        if bar.low_price <= self.stop_loss_price:
            self.sell(bar.close_price, abs(self.pos))
            self.write_log(f"触发止损，价格: {bar.close_price:.2f}")
            self.reset_position_vars()
            return
        
        # 止盈
        if bar.high_price >= self.take_profit_price:
            self.sell(bar.close_price, abs(self.pos))
            self.write_log(f"触发止盈，价格: {bar.close_price:.2f}")
            self.reset_position_vars()
            return
    
    def reset_position_vars(self):
        """
        重置持仓相关变量
        """
        self.entry_price = 0.0
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.signal_bar_low = 0.0
    
    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        pass

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder):
        """
        Callback of stop order update.
        """
        pass
