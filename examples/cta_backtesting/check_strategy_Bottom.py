"""
调试底部止跌策略 - 分析特定时间点为什么没有触发信号
"""

from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy_ctastrategy import ArrayManager


def load_csv_data(file_path: str, vt_symbol: str) -> list[BarData]:
    """从CSV加载数据"""
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


def check_strategy_conditions(bars: list[BarData], target_time: datetime):
    """
    检查特定时间点的策略条件
    """
    # 找到目标K线的索引
    target_idx = None
    for i, bar in enumerate(bars):
        if bar.datetime == target_time:
            target_idx = i
            break
    
    if target_idx is None:
        print(f"未找到时间点: {target_time}")
        return
    
    print(f"\n{'='*80}")
    print(f"分析时间点: {target_time}")
    print(f"K线索引: {target_idx}")
    print(f"当前K线数据:")
    print(f"  开盘价: {bars[target_idx].open_price}")
    print(f"  最高价: {bars[target_idx].high_price}")
    print(f"  最低价: {bars[target_idx].low_price}")
    print(f"  收盘价: {bars[target_idx].close_price}")
    print(f"  成交量: {bars[target_idx].volume}")
    print(f"{'='*80}\n")
    
    # 需要至少100根K线才能初始化ArrayManager
    if target_idx < 99:
        print("错误: 数据不足，无法计算指标\n")
        return
    
    # 获取前100根K线用于计算
    start_idx = target_idx - 99
    relevant_bars = bars[start_idx:target_idx + 1]
    
    # 创建ArrayManager并更新数据
    am = ArrayManager(size=100)
    for bar in relevant_bars:
        am.update_bar(bar)
    
    if not am.inited:
        print("错误: ArrayManager未初始化\n")
        return
    
    # 1. 检查总体下跌条件
    drop_count = 30
    drop_threshold = 0.005
    closes = am.close
    
    start_price = closes[-drop_count-1]
    end_price = closes[-1]
    drop_rate = (start_price - end_price) / start_price
    
    print(f"【条件1】总体下跌检查 (N={drop_count}, 阈值={drop_threshold*100}%)")
    print(f"  起始价格 (第-{drop_count+1}根): {start_price:.2f}")
    print(f"  结束价格 (最后一根): {end_price:.2f}")
    print(f"  跌幅: {drop_rate*100:.2f}%")
    print(f"  结果: {'✓ 通过' if drop_rate >= drop_threshold else '✗ 未通过'}\n")
    
    # 2. 检查均线向下趋势
    ma_length = 20
    ma_current = am.sma(ma_length)
    ma_previous = am.sma(ma_length, array=True)[-2]
    
    print(f"【条件2】均线向下趋势 (周期={ma_length})")
    print(f"  当前MA{ma_length}: {ma_current:.2f}")
    print(f"  前一根MA{ma_length}: {ma_previous:.2f}")
    print(f"  结果: {'✓ 通过' if ma_current < ma_previous else '✗ 未通过'}\n")
    
    # 3. 检查三K线形态
    opens = am.open
    highs = am.high
    lows = am.low
    
    open1, close1, high1, low1 = opens[-3], closes[-3], highs[-3], lows[-3]
    open2, close2, high2, low2 = opens[-2], closes[-2], highs[-2], lows[-2]
    open3, close3, high3, low3 = opens[-1], closes[-1], highs[-1], lows[-1]
    
    print(f"【条件3】三K线形态检查")
    print(f"  第一根K线(-3): O={open1:.2f}, H={high1:.2f}, L={low1:.2f}, C={close1:.2f}")
    print(f"  第二根K线(-2): O={open2:.2f}, H={high2:.2f}, L={low2:.2f}, C={close2:.2f}")
    print(f"  第三根K线(-1): O={open3:.2f}, H={high3:.2f}, L={low3:.2f}, C={close3:.2f}")
    
    cond1 = close1 > open1  # 第一根阳线
    cond2 = close2 > open2  # 第二根阳线
    cond3 = close3 < open3  # 第三根阴线
    cond4 = open2 > open1 and close2 > close1 and high2 > high1 and low2 > low1  # 第二根>第一根
    cond5 = close3 > open1  # 第三根收盘 > 第一根开盘
    cond6 = low3 > low1  # 第三根最低 > 第一根最低
    
    print(f"    第一根是阳线: {'✓' if cond1 else '✗'} (C>O)")
    print(f"    第二根是阳线: {'✓' if cond2 else '✗'} (C>O)")
    print(f"    第三根是阴线: {'✓' if cond3 else '✗'} (C<O)")
    print(f"    第二根OHLC都大于第一根: {'✓' if cond4 else '✗'}")
    print(f"      - O2({open2:.2f}) > O1({open1:.2f}): {open2 > open1}")
    print(f"      - C2({close2:.2f}) > C1({close1:.2f}): {close2 > close1}")
    print(f"      - H2({high2:.2f}) > H1({high1:.2f}): {high2 > high1}")
    print(f"      - L2({low2:.2f}) > L1({low1:.2f}): {low2 > low1}")
    print(f"    第三根收盘({close3:.2f}) > 第一根开盘({open1:.2f}): {'✓' if cond5 else '✗'}")
    print(f"    第三根最低({low3:.2f}) > 第一根最低({low1:.2f}): {'✓' if cond6 else '✗'}")
    
    pattern_ok = cond1 and cond2 and cond3 and cond4 and cond5 and cond6
    print(f"  形态结果: {'✓ 通过' if pattern_ok else '✗ 未通过'}\n")
    
    # 4. 检查量能条件
    volumes = am.volume
    current_volume = volumes[-1]
    max_prev_volume = max(volumes[-2], volumes[-3])
    
    print(f"【条件4】量能检查")
    print(f"  第三根K线成交量: {current_volume:.0f}")
    print(f"  前两根最大成交量: {max_prev_volume:.0f}")
    print(f"  结果: {'✓ 通过' if current_volume < max_prev_volume else '✗ 未通过'}\n")
    
    # 5. 检查MACD条件
    macd, signal, hist = am.macd(12, 26, 9, array=True)
    current_macd = macd[-1]
    current_hist = hist[-1]
    prev_hist = hist[-2]
    
    print(f"【条件5】MACD检查")
    print(f"  当前MACD值: {current_macd:.4f}")
    print(f"  当前Hist值: {current_hist:.4f}")
    print(f"  前一根Hist值: {prev_hist:.4f}")
    print(f"  MACD在零轴下方: {'✓' if current_macd < 0 else '✗'}")
    print(f"  Hist缩短 (绿柱绝对值变小): {'✓' if current_hist > prev_hist else '✗'}")
    print(f"    说明: 当hist为负时，{current_hist:.4f} > {prev_hist:.4f} 表示更接近零（柱子变短）")
    
    macd_ok = current_macd < 0 and current_hist > prev_hist
    print(f"  MACD结果: {'✓ 通过' if macd_ok else '✗ 未通过'}\n")
    
    # 总结
    all_passed = (drop_rate >= drop_threshold and 
                  ma_current < ma_previous and 
                  pattern_ok and 
                  current_volume < max_prev_volume and 
                  macd_ok)
    
    print(f"{'='*80}")
    print(f"最终结论: {'🎉 所有条件通过，应该触发买入信号！' if all_passed else '❌ 条件未全部满足，不触发信号'}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    # 加载数据
    csv_path = "/Users/zhanghuan/code/github/vnpy/examples/data_recorder/RB0_5min.csv"
    vt_symbol = "RB0.SHFE"
    bars = load_csv_data(csv_path, vt_symbol)
    
    print(f"加载了 {len(bars)} 根K线数据")
    
    # 分析 05-08 21:25 这根K线
    target_time = datetime(2026, 5, 8, 21, 20, 0)
    check_strategy_conditions(bars, target_time)
