"""
CTA策略回测示例 - 从CSV文件加载数据进行回测

本脚本演示如何：
1. 从CSV文件加载历史K线数据
2. 使用ATR RSI策略进行回测
3. 打印详细的交易记录
"""

from datetime import datetime
import pandas as pd

from vnpy.trader.object import BarData
from vnpy.trader.constant import Interval, Exchange
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy_ctastrategy.strategies.atr_rsi_strategy import AtrRsiStrategy


def load_csv_data(file_path: str, vt_symbol: str) -> list[BarData]:
    """
    从CSV文件加载历史K线数据并转换为BarData对象
    
    Args:
        file_path: CSV文件路径，需要包含datetime, open, high, low, close, volume列
        vt_symbol: 合约代码，格式为"合约代码.交易所代码"，如"RB0.SHFE"
    
    Returns:
        BarData对象列表，每个对象代表一根K线
    """
    bars: list[BarData] = []

    # 读取CSV文件为DataFrame
    df = pd.read_csv(file_path)

    # 从合约代码中提取交易品种和交易所信息
    # 例如："RB0.SHFE" -> symbol="RB0", exchange_str="SHFE"
    symbol = vt_symbol.split(".")[0]
    exchange_str = vt_symbol.split(".")[1]
    
    # 将交易所字符串转换为Exchange枚举对象
    exchange = Exchange(exchange_str)

    # 遍历每一行数据，创建BarData对象
    for _, row in df.iterrows():
        bar = BarData(
            symbol=symbol,                                    # 交易品种代码
            exchange=exchange,                                # 交易所
            datetime=datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S"),  # K线时间
            interval=Interval.MINUTE,                         # K线周期（分钟线）
            volume=row["volume"],                             # 成交量
            open_price=row["open"],                           # 开盘价
            high_price=row["high"],                           # 最高价
            low_price=row["low"],                             # 最低价
            close_price=row["close"],                         # 收盘价
            gateway_name="CSV",                               # 数据来源标识
        )
        bars.append(bar)

    return bars


def print_trading_records(engine):
    """
    打印回测过程中的所有交易记录
    
    Args:
        engine: 回测引擎对象，包含回测结果和交易数据
    """
    print("\n" + "="*80)
    print("交易记录详情")
    print("="*80)
    
    # 检查是否有成交记录
    if not engine.trades:
        print("没有成交记录")
        return
    
    # 打印表头
    print(f"{'序号':<6} {'时间':<22} {'方向':<6} {'开平':<6} {'价格':<10} {'数量':<8} {'金额':<12}")
    print("-" * 80)
    
    # 遍历所有成交记录并打印
    for idx, trade in enumerate(engine.trades.values(), 1):
        # 转换方向：多->买入，空->卖出
        direction = "买入" if trade.direction.value == "多" else "卖出"
        
        # 转换开平标志：开->开仓，平->平仓
        offset = "开仓" if trade.offset.value == "开" else "平仓"
        
        # 计算成交金额 = 价格 × 数量 × 合约乘数
        amount = trade.price * trade.volume * trade.size if hasattr(trade, 'size') else trade.price * trade.volume
        
        # 格式化输出交易信息
        print(f"{idx:<6} {str(trade.datetime):<22} {direction:<6} {offset:<6} {trade.price:<10.2f} {trade.volume:<8} {amount:<12.2f}")
    
    # 打印汇总信息
    print("="*80)
    print(f"总成交笔数: {len(engine.trades)}")
    print(f"总成交金额: {sum(t.price * t.volume * (t.size if hasattr(t, 'size') else 1) for t in engine.trades.values()):.2f}")
    print("="*80 + "\n")


if __name__ == "__main__":
    """
    主程序入口：执行CTA策略回测
    """
    # 创建回测引擎实例
    engine = BacktestingEngine()

    # 设置回测参数
    vt_symbol = "RB0.SHFE"  # 螺纹钢期货主力合约，上海期货交易所
    engine.set_parameters(
        vt_symbol=vt_symbol,              # 交易合约代码
        interval=Interval.MINUTE,         # K线周期：分钟线
        start=datetime(2026, 4, 28),      # 回测开始日期
        end=datetime(2026, 5, 22),        # 回测结束日期
        rate=0.0001,                      # 手续费率：万分之1
        slippage=1,                       # 滑点：1个最小变动价位
        size=10,                          # 合约乘数：10吨/手
        pricetick=1,                      # 最小价格变动：1元
        capital=100_000,                  # 初始资金：10万元
    )

    # 添加要测试的策略类及其参数
    # AtrRsiStrategy是基于ATR和RSI指标的CTA策略
    engine.add_strategy(AtrRsiStrategy, {})

    # 从CSV文件加载历史数据
    csv_path = "/examples/data_recorder/RB0_5min.csv"
    bars = load_csv_data(csv_path, vt_symbol)
    
    # 将加载的数据直接赋值给回测引擎的历史数据
    # 注意：这种方式会忽略set_parameters中设置的start和end参数
    # 回测将使用CSV文件中的所有数据
    engine.history_data = bars
    
    # 执行回测流程
    # 1. 初始化策略
    engine.run_backtesting()
    
    # 2. 计算每日盈亏结果
    df = engine.calculate_result()
    
    # 3. 计算统计指标（收益率、夏普比率、最大回撤等）
    engine.calculate_statistics()
    
    # 4. 打印详细的交易记录
    print_trading_records(engine)
