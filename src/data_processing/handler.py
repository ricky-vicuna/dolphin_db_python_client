import csv
from datetime import date

import polars as pl

from data_processing.trades_types import (
    Exchange,
    ExecType,
    SseTickTradeRawItem,
    SzseTickTradeRawItem,
    TradeBSFlag,
)

db_items = []
trading_day = date(2026, 10, 27)  # 根據檔名或實際交易日設定

with open("A50-20261027-Stock/20261027-Stock-0.csv", mode="r", encoding="utf-8") as f:
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
df = pl.DataFrame(data_dicts)

print(df)
print(df.schema)
