from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel

from data_processing.timestamp_conversion import (
    parse_recv_datetime,
    parse_sse_datetime,
    parse_szse_datetime,
)


class Exchange(Enum):
    SZSE = "SZSE"
    SSE = "SSE"


class TradeBSFlag(Enum):
    B = "B"
    S = "S"
    N = "N"


class ExecType(Enum):
    F = "F"
    CANCEL = "4"


class TickTradeDBItem(BaseModel):
    exchange: Exchange
    recv_dt: datetime
    event_dt: datetime
    security_id: str
    type: ExecType | TradeBSFlag
    trade_price: float
    trade_quantity: int


class SzseTickTradeRawItem(BaseModel):
    exchange: Exchange
    recv_dt: str
    event_dt: int
    security_id: str
    exec_type: ExecType
    trade_price: float
    trade_quantity: int

    def to_db(self) -> TickTradeDBItem:
        data = self.model_dump()
        data["recv_dt"] = parse_recv_datetime(data["recv_dt"])
        data["event_dt"] = parse_szse_datetime(event_time=data["event_dt"])
        data["trade_quantity"] = int(data["trade_quantity"] / 100)
        data["type"] = data["exec_type"]
        data.pop("exec_type", None)
        return TickTradeDBItem.model_validate(data)


class SseTickTradeRawItem(BaseModel):
    exchange: Exchange
    recv_dt: str
    event_dt: str
    security_id: str
    trade_bs_flag: TradeBSFlag
    trade_price: float
    trade_quantity: int

    def to_db(self, *, trading_day: date) -> TickTradeDBItem:
        data = self.model_dump()
        data["recv_dt"] = parse_recv_datetime(data["recv_dt"])
        data["event_dt"] = parse_sse_datetime(data["event_dt"], trading_day)
        data["trade_quantity"] = int(data["trade_quantity"] / 1000)
        data["type"] = data["trade_bs_flag"]
        data.pop("trade_bs_flag", None)
        return TickTradeDBItem.model_validate(data)


if __name__ == "__main__":
    import csv

    import polars as pl

    db_items = []
    trading_day = date(2026, 10, 27)  # 根據檔名或實際交易日設定

    with open(
        "A50-20261027-Stock/20261027-Stock-0.csv", mode="r", encoding="utf-8"
    ) as f:
        reader = csv.reader(f)
        for row in reader:
            # row[0] 判斷是 SzseTrade 還是 SseTrade
            source_type = row[0]

            if source_type == "SzseTrade":
                raw_item = SzseTickTradeRawItem(
                    exchange=Exchange.SZSE,
                    recv_dt=row[1],
                    event_dt=int(row[2]),
                    security_id=str(row[3]),
                    exec_type=ExecType(row[4]),
                    trade_price=float(row[5]),
                    trade_quantity=int(row[6]),
                )
                # 轉換成 DB Item
                db_items.append(raw_item.to_db())

            elif source_type == "SseTrade":
                raw_item = SseTickTradeRawItem(
                    exchange=Exchange.SSE,
                    recv_dt=row[1],
                    event_dt=row[2],
                    security_id=str(row[3]),
                    trade_bs_flag=TradeBSFlag(row[4]),
                    trade_price=float(row[5]),
                    trade_quantity=int(row[6]),
                )
                # 轉換成 DB Item (需帶入 trading_day)
                db_items.append(raw_item.to_db(trading_day=trading_day))

    # 1. 將所有的 TickTradeDBItem 透過 model_dump() 轉成 dict 列表
    data_dicts = [item.model_dump() for item in db_items]

    # 2. 生成 Polars DataFrame
    df = (
        pl.DataFrame(data_dicts)
        .sort("recv_dt")
        .filter(pl.col("security_id") == "000338")
    )

    print(df)
    print(df.schema)
