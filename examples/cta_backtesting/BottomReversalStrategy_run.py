"""
底部止跌确认策略回测脚本
"""

import os
from pathlib import Path
import pandas as pd

from vnpy.trader.object import BarData
from vnpy.trader.constant import Direction, Exchange, Interval, Offset
from vnpy_ctastrategy.backtesting import BacktestingEngine
from BottomReversalStrategy import BottomReversalStrategy


FUTURES_EXCHANGE_MAP = {
    "AG": Exchange.SHFE,
    "AO": Exchange.SHFE,
    "RB": Exchange.SHFE,
    "SH": Exchange.CZCE,
}


def infer_vt_symbol(file_path: str) -> str:
    """
    根据CSV文件名推断合约代码，例如SH0_daily_2021_2026.csv -> SH0.CZCE
    """
    symbol = Path(file_path).name.split("_", 1)[0].upper()
    product = "".join(char for char in symbol if char.isalpha())
    exchange = FUTURES_EXCHANGE_MAP.get(product, Exchange.SHFE)
    return f"{symbol}.{exchange.value}"


def infer_interval(file_path: str, datetime_series: pd.Series) -> Interval:
    """
    根据文件名和datetime列格式推断K线周期。
    """
    file_name = Path(file_path).name.lower()
    datetime_text = datetime_series.astype(str).str.strip()

    if "daily" in file_name or datetime_text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        return Interval.DAILY

    return Interval.MINUTE


def load_csv_data(file_path: str, vt_symbol: str) -> tuple[list[BarData], Interval]:
    """
    从CSV文件加载历史K线数据并转换为BarData对象
    
    Args:
        file_path: CSV文件路径
        vt_symbol: 合约代码，格式为"合约代码.交易所代码"
    
    Returns:
        BarData对象列表和K线周期
    """
    bars: list[BarData] = []

    df = pd.read_csv(file_path)
    required_columns = {"datetime", "open", "high", "low", "close", "volume"}
    missing_columns = required_columns - set(df.columns)
    if missing_columns:
        raise ValueError(f"CSV缺少必要字段: {', '.join(sorted(missing_columns))}")

    interval = infer_interval(file_path, df["datetime"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="raise")

    if "hold" in df.columns:
        df["hold"] = pd.to_numeric(df["hold"], errors="coerce").fillna(0)
    else:
        df["hold"] = 0

    symbol = vt_symbol.split(".")[0]
    exchange_str = vt_symbol.split(".")[1]
    exchange = Exchange(exchange_str)

    for _, row in df.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["datetime"].to_pydatetime(),
            interval=interval,
            volume=float(row["volume"]),
            open_interest=float(row["hold"]),
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            gateway_name="CSV",
        )
        bars.append(bar)

    return bars, interval


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
        direction = "买入" if trade.direction == Direction.LONG else "卖出"
        offset_map = {
            Offset.OPEN: "开仓",
            Offset.CLOSE: "平仓",
            Offset.CLOSETODAY: "平今",
            Offset.CLOSEYESTERDAY: "平昨",
        }
        offset = offset_map.get(trade.offset, trade.offset.value)
        amount = trade.price * trade.volume * engine.size
        
        print(f"{idx:<6} {str(trade.datetime):<22} {direction:<6} {offset:<6} {trade.price:<10.2f} {trade.volume:<8} {amount:<12.2f}")
    
    print("="*80)
    print(f"总成交笔数: {len(engine.trades)}")
    print(f"总成交金额: {sum(t.price * t.volume * engine.size for t in engine.trades.values()):.2f}")
    print("="*80 + "\n")


if __name__ == "__main__":
    """
    主程序入口：执行底部止跌策略回测
    """
    # 从CSV文件加载历史数据
    csv_path_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv_data")
    # csv_path = os.path.join(csv_path_root, "SH0_5min.csv")  # 烧碱
    # csv_path = os.path.join(csv_path_root, "AG0_5min.csv")  # 白银数据
    # csv_path = os.path.join(csv_path_root, "SH0_daily_2021_2026.csv")  #
    # csv_path = os.path.join(csv_path_root, "AO0_daily_2020_2026.csv")  #
    csv_path = os.path.join(csv_path_root, "AG0_daily_2015_2026.csv")  #

    vt_symbol = infer_vt_symbol(csv_path)
    bars, interval = load_csv_data(csv_path, vt_symbol)
    if not bars:
        raise ValueError(f"CSV数据为空: {csv_path}")

    # 创建回测引擎实例
    engine = BacktestingEngine()

    # 设置回测参数
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=interval,
        start=bars[0].datetime,
        end=bars[-1].datetime,
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100_000,
    )

    # 添加策略及参数配置
    strategy_setting = {
        "drop_count": 20,              # 观察下跌30根K线
        "drop_threshold": 0.01,       # 跌幅0.5%
        "ma_length": 20,              # 20周期均线
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "risk_reward_ratio": 3        # 盈亏比1:3
    }
    
    engine.add_strategy(BottomReversalStrategy, strategy_setting)
    
    # 将加载的数据赋值给回测引擎
    engine.history_data = bars

    print(
        f"加载数据: {os.path.basename(csv_path)}, 合约: {vt_symbol}, "
        f"周期: {interval.value}, 数据量: {len(bars)}, "
        f"范围: {bars[0].datetime.date()} - {bars[-1].datetime.date()}"
    )
    
    # 执行回测流程
    print("开始执行回测...")
    engine.run_backtesting()
    df = engine.calculate_result()
    engine.calculate_statistics()
    
    # 打印交易记录
    print_trading_records(engine)
    
    print("回测完成！")
