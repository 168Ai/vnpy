from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from mootdx.consts import EX_HOSTS
from tdxpy.exhq import TdxExHq_API


FREQUENCY_MAP = {
    "5m": 0,
    "5min": 0,
    "15m": 1,
    "15min": 1,
    "30m": 2,
    "30min": 2,
    "1h": 3,
    "60m": 3,
    "60min": 3,
    "day": 4,
    "daily": 4,
    "d": 4,
    "week": 5,
    "w": 5,
    "month": 6,
    "mon": 6,
    "1m": 7,
    "1min": 7,
}

FUTURE_MARKET_IDS = {
    "czce": [28],
    "dce": [29],
    "shfe": [30],
    "cffex": [47],
    "main": [60],
    "gfex": [66, 65],
}

EXCHANGE_ALIASES = {
    "shfe": {"shfe", "sq", "上期所", "上海期货", "上海期货交易所"},
    "ine": {"ine", "能源", "上海国际能源", "上海国际能源交易中心"},
    "dce": {"dce", "dl", "大商所", "大连商品", "大连商品交易所"},
    "czce": {"czce", "zc", "郑商所", "郑州商品", "郑州商品交易所"},
    "cffex": {"cffex", "zj", "中金所", "中国金融期货", "中国金融期货交易所"},
    "gfex": {"gfex", "广期所", "广州期货", "广州期货交易所"},
}

EXCHANGE_KEYWORDS = {
    "shfe": ("上海期", "上期", "SHFE"),
    "ine": ("能源", "INE"),
    "dce": ("大连", "大商", "DCE"),
    "czce": ("郑州", "郑商", "CZCE"),
    "cffex": ("中金", "金融期", "CFFEX"),
    "gfex": ("广州", "广期", "GFEX"),
}

# 国内期货品种对应交易所。用于在未拉取全量合约表前快速限定搜索范围。
PRODUCT_EXCHANGE = {
    "AG": "shfe",
    "AL": "shfe",
    "AO": "shfe",
    "AU": "shfe",
    "BR": "shfe",
    "BU": "shfe",
    "CU": "shfe",
    "FU": "shfe",
    "HC": "shfe",
    "NI": "shfe",
    "PB": "shfe",
    "RB": "shfe",
    "RU": "shfe",
    "SN": "shfe",
    "SP": "shfe",
    "SS": "shfe",
    "WR": "shfe",
    "ZN": "shfe",
    "BC": "ine",
    "EC": "ine",
    "LU": "ine",
    "NR": "ine",
    "SC": "ine",
    "A": "dce",
    "B": "dce",
    "C": "dce",
    "CS": "dce",
    "EB": "dce",
    "EG": "dce",
    "I": "dce",
    "J": "dce",
    "JD": "dce",
    "JM": "dce",
    "L": "dce",
    "LH": "dce",
    "M": "dce",
    "P": "dce",
    "PG": "dce",
    "PP": "dce",
    "RR": "dce",
    "V": "dce",
    "Y": "dce",
    "AP": "czce",
    "CF": "czce",
    "CJ": "czce",
    "CY": "czce",
    "FG": "czce",
    "JR": "czce",
    "LR": "czce",
    "MA": "czce",
    "OI": "czce",
    "PF": "czce",
    "PK": "czce",
    "PM": "czce",
    "PX": "czce",
    "RI": "czce",
    "RM": "czce",
    "RS": "czce",
    "SA": "czce",
    "SF": "czce",
    "SH": "czce",
    "SM": "czce",
    "SR": "czce",
    "TA": "czce",
    "UR": "czce",
    "WH": "czce",
    "ZC": "czce",
    "IC": "cffex",
    "IF": "cffex",
    "IH": "cffex",
    "IM": "cffex",
    "T": "cffex",
    "TF": "cffex",
    "TL": "cffex",
    "TS": "cffex",
    "LC": "gfex",
    "PS": "gfex",
    "SI": "gfex",
}


@dataclass(frozen=True)
class Contract:
    market: int
    code: str
    name: str = ""
    category: int | None = None
    desc: str = ""

    @classmethod
    def from_record(cls, row: pd.Series | dict) -> "Contract":
        return cls(
            market=int(row["market"]),
            code=str(row["code"]).strip(),
            name=str(row.get("name", "")).strip(),
            category=int(row["category"]) if "category" in row and pd.notna(row["category"]) else None,
            desc=str(row.get("desc", "")).strip(),
        )


def normalize_frequency(frequency: str | int) -> int:
    if isinstance(frequency, int):
        return frequency

    key = str(frequency).strip().lower()
    if key.isdigit():
        minute = int(key)
        aliases = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h"}
        key = aliases.get(minute, key)

    if key not in FREQUENCY_MAP:
        supported = ", ".join(sorted(FREQUENCY_MAP))
        raise ValueError(f"不支持的K线周期：{frequency}，支持：{supported}")

    return FREQUENCY_MAP[key]


def normalize_exchange(exchange: str | None) -> str | None:
    if not exchange:
        return None

    value = str(exchange).strip().lower()
    for standard, aliases in EXCHANGE_ALIASES.items():
        if value in {item.lower() for item in aliases}:
            return standard

    raise ValueError(f"不支持的交易所：{exchange}")


def product_from_symbol(symbol: str) -> str:
    match = re.match(r"^([A-Za-z]+)", symbol.strip())
    return match.group(1).upper() if match else ""


def guess_exchange(symbol: str) -> str | None:
    return PRODUCT_EXCHANGE.get(product_from_symbol(symbol))


def normalize_symbol_candidates(symbol: str) -> list[str]:
    """
    生成通达信扩展行情里可能出现的代码写法。

    指定月份合约通常是 RB2505、rb2505 这类代码；主力连续在不同通达信源
    可能写作 RB0、RB00、RBL0、RBL8，需要逐个匹配服务器返回的合约表。
    """
    raw = symbol.strip()
    compact = raw.replace(".", "").replace("-", "").replace("_", "")
    candidates = [raw, compact, compact.upper(), compact.lower()]

    product = product_from_symbol(compact)
    suffix = compact[len(product) :]

    if product and suffix in {"0", "00", "L0", "L8", "l0", "l8"}:
        candidates.extend(
            [
                f"{product}0",
                f"{product}00",
                f"{product}L0",
                f"{product}L8",
                f"{product.lower()}0",
                f"{product.lower()}00",
                f"{product.lower()}L0",
                f"{product.lower()}L8",
            ]
        )

    unique = []
    for item in candidates:
        if item and item not in unique:
            unique.append(item)
    return unique


def output_dir() -> Path:
    path = Path(__file__).parent.parent / "cta_backtesting" / "csv_data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def iter_servers(extra_servers: Iterable[tuple[str, int]] | None = None):
    seen = set()

    if extra_servers:
        for ip, port in extra_servers:
            key = (ip, int(port))
            if key not in seen:
                seen.add(key)
                yield "自定义扩展行情", ip, int(port)

    for name, ip, port in EX_HOSTS:
        key = (ip, int(port))
        if key not in seen:
            seen.add(key)
            yield name, ip, int(port)


def parse_server(value: str | None) -> list[tuple[str, int]]:
    if not value:
        return []

    servers = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("--server 格式应为 ip:port，多个用逗号分隔")
        ip, port = item.rsplit(":", 1)
        servers.append((ip.strip(), int(port)))
    return servers


def connect_ext(timeout: float = 5, server: str | None = None) -> TdxExHq_API:
    errors = []

    for name, ip, port in iter_servers(parse_server(server)):
        client = TdxExHq_API(auto_retry=True, raise_exception=True)
        try:
            client.connect(ip, port, time_out=timeout)
            markets = client.get_markets()
            if markets:
                print(f"已连接通达信扩展行情：{name} {ip}:{port}")
                return client
            errors.append(f"{name} {ip}:{port} 无市场列表")
        except Exception as exc:
            errors.append(f"{name} {ip}:{port} -> {exc}")
            safe_close(client)

    details = "\n".join(errors[-8:])
    raise ConnectionError(
        "所有通达信扩展行情服务器连接失败。通达信免费扩展行情源不稳定，"
        "可以用 --server ip:port 指定你本机通达信可用的扩展行情服务器。\n"
        f"最近失败信息：\n{details}"
    )


def safe_close(client: TdxExHq_API) -> None:
    try:
        client.close()
    except Exception:
        pass


def fetch_markets(client: TdxExHq_API) -> pd.DataFrame:
    df = pd.DataFrame(client.get_markets() or [])
    if df.empty:
        return pd.DataFrame(columns=["market", "category", "name", "short_name", "exchange"])

    df["exchange"] = df.apply(infer_exchange_from_market, axis=1)
    return df.sort_values(["market", "category"]).reset_index(drop=True)


def infer_exchange_from_market(row: pd.Series) -> str:
    text = f"{row.get('name', '')} {row.get('short_name', '')}"
    lowered = text.lower()
    for exchange, keywords in EXCHANGE_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in lowered:
                return exchange
    return ""


def market_ids_for_exchange(markets: pd.DataFrame, exchange: str | None) -> list[int]:
    if not exchange:
        return []

    matched = markets[markets["exchange"] == exchange]
    ids = {int(value) for value in matched["market"].tolist()}
    ids.update(FUTURE_MARKET_IDS.get(exchange, []))
    return sorted(ids)


def likely_market_ids(symbol: str, exchange: str | None) -> list[int]:
    ids = []
    if exchange:
        ids.extend(FUTURE_MARKET_IDS.get(exchange, []))

    if symbol_is_main(symbol):
        ids.extend(FUTURE_MARKET_IDS["main"])

    for market_ids in FUTURE_MARKET_IDS.values():
        ids.extend(market_ids)

    unique = []
    for item in ids:
        if item not in unique:
            unique.append(item)
    return unique


def symbol_is_main(symbol: str) -> bool:
    compact = symbol.strip().replace(".", "").replace("-", "").replace("_", "")
    product = product_from_symbol(compact)
    suffix = compact[len(product) :].upper()
    return bool(product and suffix in {"0", "00", "L0", "L8"})


def fetch_instruments(
    client: TdxExHq_API,
    cache_file: Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    if cache_file and cache_file.exists() and not refresh:
        return pd.read_csv(cache_file)

    count = int(client.get_instrument_count() or 0)
    rows = []

    for start in range(0, count, 500):
        batch = client.get_instrument_info(start, 500) or []
        rows.extend(batch)
        print(f"已读取合约表 {min(start + len(batch), count)}/{count}")

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["market", "code"], keep="last")
        df = df.sort_values(["market", "code"]).reset_index(drop=True)

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_file, index=False, quoting=csv.QUOTE_MINIMAL, escapechar="\\")
        print(f"合约表已缓存：{cache_file}")

    return df


def search_contracts(
    instruments: pd.DataFrame,
    keyword: str,
    exchange: str | None = None,
    markets: pd.DataFrame | None = None,
    limit: int = 50,
) -> pd.DataFrame:
    if instruments.empty:
        return instruments

    df = instruments.copy()
    if exchange and markets is not None and not markets.empty:
        ids = market_ids_for_exchange(markets, exchange)
        if ids:
            df = df[df["market"].isin(ids)]

    keyword_upper = keyword.strip().upper()
    mask = (
        df["code"].astype(str).str.upper().str.contains(keyword_upper, regex=False)
        | df["name"].astype(str).str.upper().str.contains(keyword_upper, regex=False)
        | df["desc"].astype(str).str.upper().str.contains(keyword_upper, regex=False)
    )
    return df[mask].head(limit).reset_index(drop=True)


def resolve_contract(
    client: TdxExHq_API,
    symbol: str,
    frequency: str | int = "5m",
    exchange: str | None = None,
    refresh_instruments: bool = False,
) -> Contract:
    markets = fetch_markets(client)
    exchange = normalize_exchange(exchange) or guess_exchange(symbol)
    direct = resolve_contract_direct(client, symbol=symbol, frequency=frequency, exchange=exchange)
    if direct:
        return direct

    cache_file = output_dir() / "mootdx_instruments.csv"
    instruments = fetch_instruments(client, cache_file=cache_file, refresh=refresh_instruments)

    if instruments.empty:
        raise LookupError("无法获取通达信扩展行情合约表。")

    candidates = normalize_symbol_candidates(symbol)
    df = instruments.copy()

    ids = market_ids_for_exchange(markets, exchange)
    if ids:
        df = df[df["market"].isin(ids)]

    upper_codes = df["code"].astype(str).str.upper()
    for candidate in candidates:
        exact = df[upper_codes == candidate.upper()]
        if len(exact) == 1:
            return Contract.from_record(exact.iloc[0])
        if len(exact) > 1:
            # 同一代码在不同扩展市场出现时，优先返回期货 category=3。
            futures = exact[exact["category"] == 3] if "category" in exact.columns else exact
            return Contract.from_record((futures if not futures.empty else exact).iloc[0])

    product = product_from_symbol(symbol)
    if product:
        prefix = df[upper_codes.str.startswith(product)]
        if not prefix.empty:
            preview = prefix[["market", "category", "code", "name", "desc"]].head(20)
            raise LookupError(
                f"没有精确匹配到 {symbol}。可用相近合约如下，请用 --symbol 指定其中一个 code：\n"
                f"{preview.to_string(index=False)}"
            )

    raise LookupError(f"没有在通达信扩展行情合约表中找到：{symbol}")


def resolve_contract_direct(
    client: TdxExHq_API,
    symbol: str,
    frequency: str | int = "5m",
    exchange: str | None = None,
) -> Contract | None:
    candidates = normalize_symbol_candidates(symbol)
    markets = likely_market_ids(symbol, exchange)
    category = normalize_frequency(frequency)

    for code in candidates:
        for market in markets:
            try:
                bars = client.get_instrument_bars(category, market, code, 0, 1)
                if not bars:
                    continue
                return Contract(market=market, code=code)
            except Exception:
                continue

    return None


def fetch_bars(
    client: TdxExHq_API,
    contract: Contract,
    frequency: str | int = "5m",
    offset: int = 800,
    pages: int = 1,
) -> pd.DataFrame:
    category = normalize_frequency(frequency)
    offset = max(1, min(int(offset), 800))
    pages = max(1, int(pages))

    frames = []
    for page in range(pages):
        start = page * offset
        data = client.get_instrument_bars(
            category=category,
            market=contract.market,
            code=contract.code,
            start=start,
            count=offset,
        )
        df = pd.DataFrame(data or [])
        if df.empty:
            break
        frames.append(df)
        print(f"已获取 {contract.code} 第 {page + 1}/{pages} 页，{len(df)} 根")
        if len(df) < offset:
            break

    if not frames:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "hold", "settlement"])

    raw = pd.concat(frames, ignore_index=True)
    return normalize_bars(raw)


def normalize_bars(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["volume"] = pd.to_numeric(df.get("trade", 0), errors="coerce").fillna(0)
    df["hold"] = pd.to_numeric(df.get("position", 0), errors="coerce").fillna(0)
    df["settlement"] = pd.to_numeric(df.get("price", 0), errors="coerce").fillna(0)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["datetime", "open", "high", "low", "close"])
    df = df[["datetime", "open", "high", "low", "close", "volume", "hold", "settlement"]]
    df = df.sort_values("datetime")
    df = df.drop_duplicates(subset=["datetime"], keep="last")
    return df.reset_index(drop=True)


def save_bars(df: pd.DataFrame, filename: str | None, symbol: str, frequency: str | int) -> Path | None:
    if df.empty:
        print("没有获取到K线数据，不写入CSV。")
        return None

    if not filename:
        safe_frequency = str(frequency).replace("/", "_")
        filename = f"{symbol}_{safe_frequency}.csv"

    path = output_dir() / filename
    df.to_csv(path, index=False)
    print(f"已保存：{path}")
    return path


def get_futures_kline(
    symbol: str = "RB0",
    frequency: str | int = "5m",
    exchange: str | None = None,
    filename: str | None = None,
    offset: int = 800,
    pages: int = 1,
    timeout: float = 5,
    server: str | None = None,
    refresh_instruments: bool = False,
) -> pd.DataFrame:
    """
    使用 mootdx/tdxpy 扩展行情获取国内期货K线。

    symbol:
        主力连续可以尝试 RB0/RB00/RBL0/RBL8；指定月份合约用 RB2505、i2509 等。
        如果代码不确定，先运行：
        python mootdx_get.py --search RB
    frequency:
        1m/5m/15m/30m/1h/day/week/month，也可传 1/5/15/30/60。
    exchange:
        可选 shfe/ine/dce/czce/cffex/gfex。未传时按品种自动猜测。
    """
    client = connect_ext(timeout=timeout, server=server)
    try:
        contract = resolve_contract(
            client,
            symbol,
            frequency=frequency,
            exchange=exchange,
            refresh_instruments=refresh_instruments,
        )
        print(
            f"匹配合约：market={contract.market}, code={contract.code}, "
            f"name={contract.name}, desc={contract.desc}"
        )
        df = fetch_bars(client, contract, frequency=frequency, offset=offset, pages=pages)
        if not df.empty:
            print(f"数据范围：{df['datetime'].min()} 至 {df['datetime'].max()}，共 {len(df)} 根")
            print(df.head())
            print(df.tail())
        save_bars(df, filename=filename, symbol=contract.code, frequency=frequency)
        return df
    finally:
        safe_close(client)


def print_markets(timeout: float, server: str | None) -> None:
    client = connect_ext(timeout=timeout, server=server)
    try:
        markets = fetch_markets(client)
        print(markets[["market", "category", "name", "short_name", "exchange"]].to_string(index=False))
    finally:
        safe_close(client)


def print_search(keyword: str, exchange: str | None, timeout: float, server: str | None, refresh: bool) -> None:
    client = connect_ext(timeout=timeout, server=server)
    try:
        markets = fetch_markets(client)
        instruments = fetch_instruments(client, cache_file=output_dir() / "mootdx_instruments.csv", refresh=refresh)
        result = search_contracts(
            instruments,
            keyword=keyword,
            exchange=normalize_exchange(exchange) if exchange else guess_exchange(keyword),
            markets=markets,
            limit=80,
        )
        if result.empty:
            print(f"没有找到：{keyword}")
            return
        print(result[["market", "category", "code", "name", "desc"]].to_string(index=False))
    finally:
        safe_close(client)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 mootdx/tdxpy 扩展行情获取国内期货数据")
    parser.add_argument("--symbol", default="RB0", help="合约代码，如 RB0/RBL8/RB2505/i2509")
    parser.add_argument("--exchange", help="交易所：shfe/ine/dce/czce/cffex/gfex，可不填自动猜测")
    parser.add_argument("--frequency", default="5m", help="周期：1m/5m/15m/30m/1h/day/week/month")
    parser.add_argument("--offset", type=int, default=800, help="每页K线数量，最大800")
    parser.add_argument("--pages", type=int, default=1, help="向前翻页次数，每页最多800根")
    parser.add_argument("--filename", help="输出CSV文件名，默认 symbol_frequency.csv")
    parser.add_argument("--timeout", type=float, default=5, help="服务器连接超时秒数")
    parser.add_argument("--server", help="自定义扩展行情服务器 ip:port，多个用逗号分隔")
    parser.add_argument("--refresh-instruments", action="store_true", help="重新拉取并缓存合约表")
    parser.add_argument("--markets", action="store_true", help="只打印扩展市场列表")
    parser.add_argument("--search", help="搜索合约代码或名称，例如 RB、螺纹、IF")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.markets:
        print_markets(timeout=args.timeout, server=args.server)
        return

    if args.search:
        print_search(
            keyword=args.search,
            exchange=args.exchange,
            timeout=args.timeout,
            server=args.server,
            refresh=args.refresh_instruments,
        )
        return

    get_futures_kline(
        symbol=args.symbol,
        frequency=args.frequency,
        exchange=args.exchange,
        filename=args.filename,
        offset=args.offset,
        pages=args.pages,
        timeout=args.timeout,
        server=args.server,
        refresh_instruments=args.refresh_instruments,
    )


if __name__ == "__main__":
    main()
