# 均线交叉策略

from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager,
)


class DoubleMaStrategy(CtaTemplate):
    """双均线交叉策略"""
    
    author = "Veighna"
    
    # 策略参数
    fast_window = 10  # 快速均线周期
    slow_window = 60  # 慢速均线周期
    
    # 策略变量
    fast_ma0 = 0.0
    fast_ma1 = 0.0
    slow_ma0 = 0.0
    slow_ma1 = 0.0

    parameters = ["fast_window", "slow_window"]
    variables = ["fast_ma0", "fast_ma1", "slow_ma0", "slow_ma1"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        
        self.bg = BarGenerator(self.on_bar, 1, self.on_1min_bar)
        self.am = ArrayManager(size=100)

    def on_init(self):
        """策略初始化"""
        self.write_log("策略初始化")
        self.load_bar(10)

    def on_start(self):
        """策略启动"""
        self.write_log("策略启动")

    def on_stop(self):
        """策略停止"""
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        """Tick数据回调"""
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """Bar数据回调"""
        self.bg.update_bar(bar)

    def on_1min_bar(self, bar: BarData):
        """1分钟K线回调"""
        self.cancel_all()
        
        self.am.update_bar(bar)
        if not self.am.inited:
            return
        
        # 计算均线
        self.fast_ma0 = self.am.sma(self.fast_window, array=True)[-1]
        self.fast_ma1 = self.am.sma(self.fast_window, array=True)[-2]
        self.slow_ma0 = self.am.sma(self.slow_window, array=True)[-1]
        self.slow_ma1 = self.am.sma(self.slow_window, array=True)[-2]
        
        # 金叉买入
        cross_over = (self.fast_ma1 < self.slow_ma1) and (self.fast_ma0 >= self.slow_ma0)
        if cross_over:
            if self.pos == 0:
                self.buy(bar.close_price, 1)
            elif self.pos < 0:
                self.cover(bar.close_price, 1)
                self.buy(bar.close_price, 1)
        
        # 死叉卖出
        cross_down = (self.fast_ma1 > self.slow_ma1) and (self.fast_ma0 <= self.slow_ma0)
        if cross_down:
            if self.pos == 0:
                self.short(bar.close_price, 1)
            elif self.pos > 0:
                self.sell(bar.close_price, 1)
                self.short(bar.close_price, 1)
        
        self.put_event()


if __name__ == "__main__":
    # 回测示例
    from vnpy_ctastrategy.backtesting import BacktestingEngine
    from datetime import datetime
    
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="rb2401.SHFE",
        interval="1m",
        start=datetime(2023, 1, 1),
        end=datetime(2023, 12, 31),
        rate=0.0003,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100000,
    )
    
    engine.add_strategy(DoubleMaStrategy, {})
    engine.load_data()
    engine.run_backtesting()
    engine.calculate_result()
    engine.show_chart()
