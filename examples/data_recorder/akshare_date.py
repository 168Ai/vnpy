import akshare as ak
import pandas as pd
from pathlib import Path


def get_futures_contract_list():
    """
    获取所有期货主力连续合约的代码和名称对应关系
    
    返回:
        DataFrame: 包含 symbol（代码）、exchange（交易所）、name（名称）的表格
    """
    df = ak.futures_display_main_sina()
    
    print("期货主力连续合约列表：")
    print(df)
    print(f"\n总共 {len(df)} 个合约")
    
    return df


def get_active_contracts():
    """
    获取活跃的主力合约列表（排除冷门合约）
    
    返回:
        list: 活跃合约的 symbol 列表
    """
    # 定义主要交易所的活跃品种
    active_symbols = {
        # 上海期货交易所 (SHFE) - 金属、能源
        "RB0": "螺纹钢",
        "HC0": "热卷",
        "I0": "铁矿石",  # 实际在大商所
        "CU0": "铜",
        "AL0": "铝",
        "ZN0": "锌",
        "NI0": "镍",
        "SN0": "锡",
        "PB0": "铅",
        "AU0": "黄金",
        "AG0": "白银",
        "RU0": "橡胶",
        "BU0": "沥青",
        "FU0": "燃料油",
        "SP0": "纸浆",
        "SS0": "不锈钢",
        
        # 大连商品交易所 (DCE) - 农产品、化工
        "M0": "豆粕",
        "RM0": "菜粕",  # 实际在郑商所
        "Y0": "豆油",
        "P0": "棕榈油",
        "OI0": "菜油",
        "CF0": "棉花",  # 实际在郑商所
        "SR0": "白糖",  # 实际在郑商所
        "C0": "玉米",
        "A0": "豆一",
        "B0": "豆二",
        "L0": "塑料",
        "V0": "PVC",
        "PP0": "聚丙烯",
        "EG0": "乙二醇",
        "EB0": "苯乙烯",
        "PG0": "液化气",
        "LH0": "生猪",
        "J0": "焦炭",
        "JM0": "焦煤",
        "I0": "铁矿石",
        
        # 郑州商品交易所 (CZCE) - 农产品、化工
        "TA0": "PTA",
        "MA0": "甲醇",
        "FG0": "玻璃",
        "SA0": "纯碱",
        "UR0": "尿素",
        "SH0": "烧碱",
        "AO0": "氧化铝",
        "AP0": "苹果",
        "CJ0": "红枣",
        "SF0": "硅铁",
        "SM0": "锰硅",
        "PF0": "短纤",
        "PK0": "花生",
        
        # 中国金融期货交易所 (CFFEX) - 股指期货、国债期货
        "IF0": "沪深300",
        "IC0": "中证500",
        "IH0": "上证50",
        "IM0": "中证1000",
        "T0": "10年国债",
        "TF0": "5年国债",
        "TS0": "2年国债",
        "TL0": "30年国债",
        
        # 上海国际能源交易中心 (INE)
        "SC0": "原油",
        "LU0": "低硫燃油",
        "NR0": "20号胶",
    }
    
    print(f"活跃合约数量: {len(active_symbols)}")
    print("\n活跃合约列表：")
    print("-" * 60)
    
    for symbol, name in sorted(active_symbols.items()):
        print(f"{symbol:8s} - {name}")
    
    return list(active_symbols.keys())


def get_futures_minute_data(symbol, period, filename):
    """
    获取期货主力连续合约的分钟K线数据（最近几天，约1000条）
    
    参数:
        symbol: 合约代码，如 "RB0"（螺纹钢）、"HC0"（热卷）等
        period: 分钟周期，可选值："1", "5", "15", "30", "60"
        filename: 保存的文件名，如 "RB0_5min.csv"
    
    返回:
        DataFrame: K线数据
    """
    
    df = ak.futures_zh_minute_sina(
        symbol=symbol,
        period=period
    )

    # 打印原始数据
    print(f"获取 {symbol} {period}分钟K线数据（最近数据）：")
    print("原始数据：")
    print(df.head())

    # 统一字段处理（方便后面接 vn.py / 回测）
    df = df.rename(columns={
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume"
    })

    # 转换时间格式
    df["datetime"] = pd.to_datetime(df["datetime"])

    # 排序（非常重要）
    df = df.sort_values("datetime")

    # 重置索引
    df = df.reset_index(drop=True)

    print("\n处理后数据：")
    print(df.head())
    
    # 构建保存路径到 csv_data 目录
    project_root = Path(__file__).parent.parent / "cta_backtesting" / "csv_data"
    project_root.mkdir(parents=True, exist_ok=True)
    
    save_path = project_root / filename
    
    # 保存本地（后面给 vn.py 用）
    df.to_csv(save_path, index=False)
    print(f"\n已保存：{save_path}")
    print(f"数据条数: {len(df)}")
    return df


def get_futures_daily_data(symbol, start_date, end_date, filename):
    """
    获取期货主力连续合约的历史日线数据（可指定日期范围）
    
    参数:
        symbol: 合约代码，如 "RB0"（螺纹钢）、"HC0"（热卷）等
        start_date: 开始日期，格式 "YYYYMMDD"，如 "20200101"
        end_date: 结束日期，格式 "YYYYMMDD"，如 "20240101"
        filename: 保存的文件名，如 "RB0_daily.csv"
    
    返回:
        DataFrame: K线数据
    """
    
    df = ak.futures_main_sina(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date
    )

    print(f"获取 {symbol} 日线数据 ({start_date} 至 {end_date})：")
    print("原始数据：")
    print(df.head())

    # 统一字段处理
    df = df.rename(columns={
        "日期": "datetime",
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
        "持仓量": "hold"
    })

    # 转换时间格式
    df["datetime"] = pd.to_datetime(df["datetime"])

    # 排序
    df = df.sort_values("datetime")

    # 重置索引
    df = df.reset_index(drop=True)

    print("\n处理后数据：")
    print(df.head())
    
    # 构建保存路径到 csv_data 目录
    project_root = Path(__file__).parent.parent / "cta_backtesting" / "csv_data"
    project_root.mkdir(parents=True, exist_ok=True)
    
    save_path = project_root / filename
    
    # 保存本地
    df.to_csv(save_path, index=False)
    print(f"\n已保存：{save_path}")
    print(f"数据条数: {len(df)}")
    return df


def get_rb0_5min(file):
    """
    获取螺纹钢主力连续合约 RB0 的 5分钟K线数据（保留原接口）
    """
    return get_futures_minute_data("RB0", "5", file)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("开始下载数据...")
    print("="*60)
    
    # ========== 方式1：获取最近的分钟数据（约3-5天，无法指定日期）==========
    df = get_futures_minute_data("RB0", "5", "RB0_5min.csv")      # 螺纹钢5分钟
    # df = get_futures_minute_data("AG0", "5", "AG0_5min.csv")      # 白银5分钟
    # df = get_futures_minute_data("SH0", "5", "SH0_5min.csv")      # 烧碱5分钟
    # df = get_futures_minute_data("AO0", "5", "AO0_5min.csv")      # 氧化铝5分钟
    
    # ========== 方式2：获取指定日期范围的日线数据（推荐）==========
    # 示例1：获取螺纹钢从2020年到2024年的日线数据
    # df = get_futures_daily_data("RB0", "20200101", "20241231", "RB0_daily_2020_2024.csv")
    
    # 示例2：获取白银从2015年至今的日线数据
    # df = get_futures_daily_data("AG0", "20150101", "20241231", "AG0_daily_2015_2024.csv")
    
    # 示例3：获取烧碱上市以来的数据（烧碱是较新的品种）
    # df = get_futures_daily_data("SH0", "20210101", "20241231", "SH0_daily.csv")
    
    # 示例4：获取氧化铝的数据
    # df = get_futures_daily_data("AO0", "20200101", "20241231", "AO0_daily.csv")
    
    # ========== 批量下载多个品种的日线数据 ==========
    # symbols_to_download = [
    #     ("RB0", "RB0_daily.csv"),
    #     ("HC0", "HC0_daily.csv"),
    #     ("I0", "I0_daily.csv"),
    #     ("AU0", "AU0_daily.csv"),
    #     ("AG0", "AG0_daily.csv"),
    #     ("SH0", "SH0_daily.csv"),
    #     ("AO0", "AO0_daily.csv"),
    # ]
    # 
    # for symbol, filename in symbols_to_download:
    #     try:
    #         get_futures_daily_data(symbol, "20200101", "20241231", filename)
    #     except Exception as e:
    #         print(f"下载 {symbol} 失败: {e}")

    print("\n数据下载完成！")
