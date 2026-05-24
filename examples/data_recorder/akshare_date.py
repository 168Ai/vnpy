import akshare as ak
import pandas as pd


def get_rb0_5min():
    """
    获取螺纹钢主力连续合约 RB0 的 5分钟K线数据
    """

    symbol = "RB0"

    df = ak.futures_zh_minute_sina(
        symbol=symbol,
        period="5"
    )

    # 打印原始数据
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

    return df


if __name__ == "__main__":
    df = get_rb0_5min()

    # 保存本地（后面给 vn.py 用）
    df.to_csv("RB0_5min.csv", index=False)

    print("\n已保存：RB0_5min.csv")