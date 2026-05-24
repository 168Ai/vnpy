"""
底部止跌确认策略回测脚本
"""

from datetime import datetime
import pandas as pd

from vnpy.trader.object import BarData
from vnpy.trader.constant import Interval, Exchange
from vnpy_ctastrategy.backtesting import BacktestingEngine
from BottomReversalStrategy import BottomReversalStrategy


def load_csv_data(file_path: str, vt_symbol: str) -> list[BarData]:
    """
    从CSV文件加载历史K线数据并转换为BarData对象
    
    Args:
        file_path: CSV文件路径
        vt_symbol: 合约代码，格式为"合约代码.交易所代码"
    
    Returns:
        BarData对象列表
    """
    bars: list[BarData] = []

    df = pd.read_csv(file_path)

    symbol = vt_symbol.split(".")[0]
    exchange_str = vt_symbol.split(".")[1]
    exchange = Exchange(exchange_str)

    for _, row in df.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S"),
            interval=Interval.MINUTE,
            volume=row["volume"],
            open_price=row["open"],
            high_price=row["high"],
            low_price=row["low"],
            close_price=row["close"],
            gateway_name="CSV",
        )
        bars.append(bar)

    return bars


def print_trading_records(engine):
    """
    打印回测过程中的所有交易记录
    """
    print("\n" + "="*80)
    print("交易记录详情")
    print("="*80)
    
    if not engine.trades:
        print("没有成交记录")
        return
    
    print(f"{'序号':<6} {'时间':<22} {'方向':<6} {'开平':<6} {'价格':<10} {'数量':<8} {'金额':<12}")
    print("-" * 80)
    
    for idx, trade in enumerate(engine.trades.values(), 1):
        direction = "买入" if trade.direction.value == "多" else "卖出"
        offset = "开仓" if trade.offset.value == "开" else "平仓"
        amount = trade.price * trade.volume * trade.size if hasattr(trade, 'size') else trade.price * trade.volume
        
        print(f"{idx:<6} {str(trade.datetime):<22} {direction:<6} {offset:<6} {trade.price:<10.2f} {trade.volume:<8} {amount:<12.2f}")
    
    print("="*80)
    print(f"总成交笔数: {len(engine.trades)}")
    print(f"总成交金额: {sum(t.price * t.volume * (t.size if hasattr(t, 'size') else 1) for t in engine.trades.values()):.2f}")
    print("="*80 + "\n")


if __name__ == "__main__":
    """
    主程序入口：执行底部止跌策略回测
    """
    # 创建回测引擎实例
    engine = BacktestingEngine()

    # 设置回测参数
    vt_symbol = "RB0.SHFE"
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.MINUTE,
        start=datetime(2026, 4, 28),
        end=datetime(2026, 5, 22),
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100_000,
    )

    # 添加策略及参数配置
    strategy_setting = {
        "drop_count": 30,              # 观察下跌30根K线
        "drop_threshold": 0.005,       # 跌幅0.5%
        "ma_length": 20,              # 20周期均线
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "risk_reward_ratio": 3        # 盈亏比1:3
    }
    
    engine.add_strategy(BottomReversalStrategy, strategy_setting)

    # 从CSV文件加载历史数据
    csv_path = "/Users/zhanghuan/code/github/vnpy/examples/data_recorder/RB0_5min.csv"
    bars = load_csv_data(csv_path, vt_symbol)
    
    # 将加载的数据赋值给回测引擎
    engine.history_data = bars
    
    # 执行回测流程
    print("开始执行回测...")
    engine.run_backtesting()
    df = engine.calculate_result()
    engine.calculate_statistics()
    
    # 打印交易记录
    print_trading_records(engine)
    
    print("回测完成！")
