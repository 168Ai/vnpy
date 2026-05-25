from tqsdk import TqApi, TqAuth
import pandas as pd


def get_rb_5min():
    """
    获取螺纹钢主力连续合约 5分钟K线
    """

    # 登录（需要天勤账号）
    api = TqApi(auth=TqAuth("phone", "***##111"))

    # 主力连续合约（螺纹钢）
    klines = api.get_kline_serial("SHFE.rb000", 5 * 60)

    # 等待数据加载完成
    api.wait_update()

    # 转换为 DataFrame
    df = klines.copy()

    # 时间戳转换
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ns")

    # 统一字段（方便后面接 vn.py）
    df = df.rename(columns={
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume"
    })

    df = df[["datetime", "open", "high", "low", "close", "volume"]]

    print(df.head())

    # 保存
    df.to_csv("RB_5min_tq.csv", index=False)

    api.close()

    return df


if __name__ == "__main__":
    df = get_rb_5min()