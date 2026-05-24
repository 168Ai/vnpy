from mootdx.quotes import Quotes
import pandas as pd


def get_futures_kline():
    """
    获取期货K线（通达信源，需支持期货）
    """

    # 期货市场（关键）
    client = Quotes.factory(market='future')

    # ⚠️ 不同通达信源代码可能不同
    # 常见尝试：
    symbol = "rb00"   # 螺纹钢主力（可能不可用，取决于源）

    df = client.bars(
        symbol=symbol,
        frequency=0,   # 0 = 1分钟
        offset=1000
    )

    print("原始数据：")
    print(df.head())

    # 统一字段
    df = df.rename(columns={
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume"
    })

    df["datetime"] = pd.to_datetime(df["datetime"])

    df = df.sort_values("datetime").reset_index(drop=True)

    # 保存
    df.to_csv("futures_kline.csv", index=False)

    print("已保存 futures_kline.csv")

    return df


if __name__ == "__main__":
    get_futures_kline()