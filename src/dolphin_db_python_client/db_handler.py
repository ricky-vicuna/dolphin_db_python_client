"""Append raw trade CSVs to dfs://python_ticks/python_trades.

Run from the project root:
    PYTHONPATH=src python -m dolphin_db_python_client.db_handler path/to/20261027-Stock-0.csv

Uses DDB_HOST, DDB_PORT, DDB_USER and DDB_PASSWORD (see client.py).
Imports append: importing the same file again adds duplicate rows.
NANOTIMESTAMP values represent Asia/Shanghai local time, without timezone metadata.
"""

import argparse
import csv
import re
from datetime import date, datetime
from pathlib import Path

from dolphindb import Session
import dolphindb.settings as keys
import pandas as pd

from data_processing.trades_types import (
    Exchange,
    ExecType,
    SseTickTradeRawItem,
    SzseTickTradeRawItem,
    TickTradeDBItem,
    TradeBSFlag,
)

from .client import TickClient

DB_PATH = "dfs://python_ticks"
TABLE_NAME = "python_trades"
BATCH_SIZE = 10_000
COLUMN_TYPES = {
    "exchange": keys.DT_SYMBOL,
    "recv_dt": keys.DT_NANOTIMESTAMP,
    "event_dt": keys.DT_NANOTIMESTAMP,
    "security_id": keys.DT_STRING,
    "type": keys.DT_SYMBOL,
    "trade_price": keys.DT_DOUBLE,
    "trade_quantity": keys.DT_LONG,
}


def _trading_day(path: Path) -> date:
    match = re.search(r"(?<!\d)(\d{8})(?!\d)", path.stem)
    if match is None:
        raise ValueError(f"CSV filename must contain a YYYYMMDD trading date: {path.name}")
    return datetime.strptime(match.group(1), "%Y%m%d").date()


def _parse_row(row: list[str], trading_day: date) -> TickTradeDBItem:
    if len(row) != 7:
        raise ValueError(f"Expected 7 CSV fields, got {len(row)}")

    source, recv_dt, event_dt, security_id, flag, price, quantity = row
    if source == "SzseTrade":
        return SzseTickTradeRawItem(
            exchange=Exchange.SZSE,
            recv_dt=recv_dt,
            event_dt=int(event_dt),
            security_id=security_id,
            exec_type=ExecType(flag),
            trade_price=float(price),
            trade_quantity=int(quantity),
        ).to_db()
    if source == "SseTrade":
        return SseTickTradeRawItem(
            exchange=Exchange.SSE,
            recv_dt=recv_dt,
            event_dt=event_dt,
            security_id=security_id,
            trade_bs_flag=TradeBSFlag(flag),
            trade_price=float(price),
            trade_quantity=int(quantity),
        ).to_db(trading_day=trading_day)
    raise ValueError(f"Unknown trade source: {source!r}")


def _to_frame(items: list[TickTradeDBItem]) -> pd.DataFrame:
    records = []
    for item in items:
        record = item.model_dump()
        record["exchange"] = item.exchange.value
        record["type"] = item.type.value
        records.append(record)

    frame = pd.DataFrame(records, columns=list(COLUMN_TYPES))
    for column in ("recv_dt", "event_dt"):
        frame[column] = (
            pd.to_datetime(frame[column], utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.tz_localize(None)
            .astype("datetime64[ns]")
        )
    frame["trade_price"] = frame["trade_price"].astype("float64")
    frame["trade_quantity"] = frame["trade_quantity"].astype("int64")
    frame.__dict__["__DolphinDB_Type__"] = COLUMN_TYPES.copy()
    return frame


def _ensure_table(session:Session) -> None:
    session.run(f'''
        if (!existsDatabase("{DB_PATH}")) {{
            database("{DB_PATH}", HASH, [STRING, 8])
        }}
        if (!existsTable("{DB_PATH}", "{TABLE_NAME}")) {{
            db = database("{DB_PATH}")
            schemaTable = table(1:0,
                `exchange`recv_dt`event_dt`security_id`type`trade_price`trade_quantity,
                [SYMBOL,NANOTIMESTAMP,NANOTIMESTAMP,STRING,SYMBOL,DOUBLE,LONG])
            db.createPartitionedTable(schemaTable, `{TABLE_NAME}, `security_id)
        }}
        pythonTradesTarget = loadTable("{DB_PATH}", "{TABLE_NAME}")
    ''')
    schema = session.run("schema(pythonTradesTarget).colDefs")
    if list(schema["name"]) != list(COLUMN_TYPES) or list(schema["typeInt"]) != list(
        COLUMN_TYPES.values()
    ):
        raise ValueError(f"{DB_PATH}/{TABLE_NAME} does not match TickTradeDBItem schema")


def _append_batch(session:Session, items: list[TickTradeDBItem]) -> None:
    session.upload({"pythonTradesIncoming": _to_frame(items)})
    try:
        inserted = session.run("tableInsert(pythonTradesTarget, pythonTradesIncoming)")
        if inserted != len(items):
            raise RuntimeError(f"Expected to insert {len(items)} rows, inserted {inserted}")
    finally:
        session.run("undef(`pythonTradesIncoming)")


def handler(csv_file: str | Path) -> None:
    """Convert a headerless seven-column CSV using the raw models and append it.

    The filename supplies the SSE trading date. Timestamps are stored as
    Asia/Shanghai local wall time (DolphinDB does not store timezone metadata).
    Memory usage is bounded by BATCH_SIZE. Errors include the source line;
    successfully appended earlier batches remain if a later batch fails.
    """
    path = Path(csv_file)
    trading_day = _trading_day(path)
    with (
        path.open("r", encoding="utf-8-sig", newline="") as source,
        TickClient() as client,
    ):
        session = client.session
        _ensure_table(session)
        batch: list[TickTradeDBItem] = []
        reader = csv.reader(source)
        for row in reader:
            if not row:
                continue
            try:
                batch.append(_parse_row(row, trading_day))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{reader.line_num}: {exc}") from exc
            if len(batch) >= BATCH_SIZE:
                _append_batch(session, batch)
                batch.clear()
        if batch:
            _append_batch(session, batch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    handler(parser.parse_args().csv_file)
