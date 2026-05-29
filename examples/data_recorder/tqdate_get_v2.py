from tqsdk import TqApi, TqAuth
import pandas as pd
from pathlib import Path
from datetime import datetime


def get_futures_minute_data_tq(symbol_code, period_minutes, start_dt, end_dt, filename):
    """
    使用天勤量化获取期货历史分钟K线数据（可指定日期范围）
    
    参数:
        symbol_code: 合约代码，如 "SHFE.rb"（螺纹钢）、"DCE.i"（铁矿石）等
        period_minutes: 分钟周期，如 1, 5, 15, 30, 60
        start_dt: 开始时间，datetime对象，如 datetime(2024, 1, 1)
        end_dt: 结束时间，datetime对象，如 datetime(2024, 12, 31)
        filename: 保存的文件名，如 "RB0_5min_2024.csv"
    
    返回:
        DataFrame: K线数据
    """
    
    print(f"正在连接天勤量化...")
    
    # 登录天勤（需要账号密码）
    api = TqApi(auth=TqAuth("18516510818", "zhang##111"))
    
    try:
        # 构建主力连续合约代码
        # 天勤量化格式：KQ.m@交易所.品种小写
        contract_code = f"KQ.m@{symbol_code}"
        
        print(f"正在获取 {contract_code} {period_minutes}分钟K线数据...")
        print(f"日期范围: {start_dt.strftime('%Y-%m-%d')} 至 {end_dt.strftime('%Y-%m-%d')}")
        
        # 使用 query_history 获取历史数据
        print("正在查询历史数据...")
        
        # 查询历史K线
        klines = api.query_history(
            symbol=contract_code,
            duration_seconds=period_minutes * 60,
            start_datetime=start_dt,
            end_datetime=end_dt
        )
        
        print(f"成功获取数据，原始数据条数: {len(klines)}")
        
        if len(klines) == 0:
            print("未获取到数据，请检查合约代码和日期范围是否正确")
            return None
        
        # 转换为 DataFrame
        df = pd.DataFrame(klines)
        
        # 时间戳转换（已经是北京时间）
        df["datetime"] = pd.to_datetime(df["datetime"], unit="s")
        
        print(f"时间范围: {df['datetime'].min()} 至 {df['datetime'].max()}")
        
        # 统一字段（符合 vn.py 格式）
        df = df.rename(columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume"
        })
        
        # 选择需要的列
        df = df[["datetime", "open", "high", "low", "close", "volume"]]
        
        # 去除空值
        df = df.dropna()
        
        # 排序
        df = df.sort_values("datetime").reset_index(drop=True)
        
        print(f"\n处理后数据条数: {len(df)}")
        print("数据预览：")
        print(df.head())
        print(df.tail())
        
        # 构建保存路径
        project_root = Path(__file__).parent.parent / "cta_backtesting" / "csv_data"
        project_root.mkdir(parents=True, exist_ok=True)
        
        save_path = project_root / filename
        
        # 保存CSV
        df.to_csv(save_path, index=False)
        print(f"\n已保存：{save_path}")
        
        return df
        
    except Exception as e:
        print(f"获取数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None
        
    finally:
        # 关闭API连接
        api.close()


def get_active_contracts_tq():
    """
    获取天勤量化支持的活跃合约列表
    """
    contracts = {
        # 上海期货交易所
        "SHFE.rb": "螺纹钢",
        "SHFE.hc": "热卷",
        "SHFE.au": "黄金",
        "SHFE.ag": "白银",
        "SHFE.cu": "铜",
        "SHFE.al": "铝",
        "SHFE.zn": "锌",
        "SHFE.ni": "镍",
        "SHFE.ru": "橡胶",
        "SHFE.bu": "沥青",
        "SHFE.fu": "燃料油",
        "SHFE.sp": "纸浆",
        "SHFE.ss": "不锈钢",
        
        # 大连商品交易所
        "DCE.i": "铁矿石",
        "DCE.m": "豆粕",
        "DCE.y": "豆油",
        "DCE.p": "棕榈油",
        "DCE.c": "玉米",
        "DCE.a": "豆一",
        "DCE.l": "塑料",
        "DCE.v": "PVC",
        "DCE.pp": "聚丙烯",
        "DCE.eg": "乙二醇",
        "DCE.eb": "苯乙烯",
        "DCE.lh": "生猪",
        "DCE.j": "焦炭",
        "DCE.jm": "焦煤",
        
        # 郑州商品交易所
        "CZCE.TA": "PTA",
        "CZCE.MA": "甲醇",
        "CZCE.FG": "玻璃",
        "CZCE.SA": "纯碱",
        "CZCE.UR": "尿素",
        "CZCE.SH": "烧碱",
        "CZCE.AO": "氧化铝",
        "CZCE.AP": "苹果",
        "CZCE.CF": "棉花",
        "CZCE.SR": "白糖",
        
        # 中国金融期货交易所
        "CFFEX.IF": "沪深300",
        "CFFEX.IC": "中证500",
        "CFFEX.IH": "上证50",
        "CFFEX.IM": "中证1000",
        
        # 上海国际能源交易中心
        "INE.sc": "原油",
        "INE.lu": "低硫燃油",
    }
    
    print("天勤量化支持的活跃合约：")
    print("-" * 60)
    for code, name in sorted(contracts.items()):
        print(f"{code:15s} - {name}")
    
    return contracts


if __name__ == "__main__":
    # 显示可用合约
    contracts = get_active_contracts_tq()
    
    print("\n" + "="*60)
    print("开始下载数据...")
    print("="*60)
    
    # ========== 示例1：获取螺纹钢2024年全年5分钟数据 ==========
    df = get_futures_minute_data_tq(
        symbol_code="SHFE.rb",
        period_minutes=5,
        start_dt=datetime(2024, 1, 1),
        end_dt=datetime(2024, 12, 31),
        filename="RB0_5min_2024.csv"
    )
    
    # ========== 示例2：获取白银2024年数据 ==========
    # df = get_futures_minute_data_tq(
    #     symbol_code="SHFE.ag",
    #     period_minutes=5,
    #     start_dt=datetime(2024, 1, 1),
    #     end_dt=datetime(2024, 12, 31),
    #     filename="AG0_5min_2024.csv"
    # )
    
    # ========== 示例3：获取烧碱数据 ==========
    # df = get_futures_minute_data_tq(
    #     symbol_code="CZCE.SH",
    #     period_minutes=5,
    #     start_dt=datetime(2024, 1, 1),
    #     end_dt=datetime(2024, 12, 31),
    #     filename="SH0_5min_2024.csv"
    # )
    
    # ========== 示例4：获取氧化铝数据 ==========
    # df = get_futures_minute_data_tq(
    #     symbol_code="CZCE.AO",
    #     period_minutes=5,
    #     start_dt=datetime(2024, 1, 1),
    #     end_dt=datetime(2024, 12, 31),
    #     filename="AO0_5min_2024.csv"
    # )
    
    # ========== 示例5：批量下载多个品种 ==========
    # symbols_to_download = [
    #     ("SHFE.rb", "RB0_5min_2024.csv"),
    #     ("SHFE.hc", "HC0_5min_2024.csv"),
    #     ("DCE.i", "I0_5min_2024.csv"),
    #     ("SHFE.au", "AU0_5min_2024.csv"),
    #     ("SHFE.ag", "AG0_5min_2024.csv"),
    # ]
    # 
    # for symbol_code, filename in symbols_to_download:
    #     try:
    #         get_futures_minute_data_tq(
    #             symbol_code=symbol_code,
    #             period_minutes=5,
    #             start_dt=datetime(2024, 1, 1),
    #             end_dt=datetime(2024, 12, 31),
    #             filename=filename
    #         )
    #     except Exception as e:
    #         print(f"下载 {symbol_code} 失败: {e}")

    print("\n数据下载完成！")
