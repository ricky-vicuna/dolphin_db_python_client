"""Query TickTradeDBItem tables through the official remote Table API."""

import os
import re
from datetime import date, timedelta
from typing import Literal, Protocol, overload

import dolphindb as ddb
import pandas as pd
import polars as pl
import pyarrow as pa

from data_processing.trades_types import Exchange

DB_PATH = "dfs://python_ticks"
TABLE_NAME = "python_trades"
TIMEZONE = "Asia/Shanghai"


class _TableResult(Protocol):
    """Table and grouped queries both expose this download method."""

    def toDF(self) -> pd.DataFrame: ...


class TickClient:
    def __init__(self, *, db_path: str | None = DB_PATH, table_name: str = TABLE_NAME):
        """Use db_path=None to query a session-local table (useful in tests)."""
        self.db_path = db_path
        self.table_name = table_name

    def __enter__(self):
        self.session = ddb.Session()
        try:
            if not self.session.connect(
                os.environ.get("DDB_HOST", "127.0.0.1"),
                int(os.environ.get("DDB_PORT", "8849")),
                os.environ["DDB_USER"],
                os.environ["DDB_PASSWORD"],
            ):
                raise ConnectionError("DolphinDB connection failed")
        except BaseException:
            self.session.close()
            raise
        return self

    def __exit__(self, *args):
        self.session.close()

    def trades(
        self,
        *,
        day: date | str | None = None,
        exchange: Exchange | str | None = None,
        security_id: str | None = None,
    ) -> ddb.Table:
        """Return a remote query; day filters event_dt in Shanghai local time."""
        conditions = []
        if day is not None:
            start = date.fromisoformat(str(day))
            end = start + timedelta(days=1)
            conditions.extend(
                [
                    f"event_dt >= {start:%Y.%m.%d}T00:00:00.000000000",
                    f"event_dt < {end:%Y.%m.%d}T00:00:00.000000000",
                ]
            )
        if exchange is not None:
            if isinstance(exchange, Exchange):
                exchange = exchange.value
            if exchange not in {"SSE", "SZSE"}:
                raise ValueError("exchange must be SSE or SZSE")
            conditions.append(f'exchange = "{exchange}"')
        if security_id is not None:
            if not re.fullmatch(r"[0-9]{6}", security_id):
                raise ValueError("security_id must be a six-digit string, e.g. 000338")
            conditions.append(f'security_id = "{security_id}"')
        table = self.session.loadTable(self.table_name, dbPath=self.db_path)
        for condition in conditions:
            table = table.where(condition)
        return table

    @staticmethod
    @overload
    def fetch(
        table: _TableResult, output: Literal["polars"] = "polars"
    ) -> pl.DataFrame: ...

    @staticmethod
    @overload
    def fetch(table: _TableResult, output: Literal["pandas"]) -> pd.DataFrame: ...

    @staticmethod
    @overload
    def fetch(table: _TableResult, output: Literal["arrow"]) -> pa.Table: ...

    @staticmethod
    def fetch(table: _TableResult, output: str = "polars"):
        """Download results, labeling recv_dt/event_dt as Asia/Shanghai.

        DolphinDB stores local wall time. Localizing adds timezone metadata
        without shifting the displayed clock. Enum columns remain strings.
        """
        if output not in {"pandas", "polars", "arrow"}:
            raise ValueError("output must be pandas, polars or arrow")
        pdf = table.toDF()
        for column in ("recv_dt", "event_dt"):
            if column in pdf.columns:
                pdf[column] = pdf[column].dt.tz_localize(TIMEZONE)
        if output == "pandas":
            return pdf
        if output == "arrow":
            return pa.Table.from_pandas(pdf, preserve_index=False)
        return pl.from_pandas(pdf)

    def count(self, **filters):
        return int(self.trades(**filters).select("count(*) as n").toDF().iloc[0, 0])

    def universe(self, **filters):
        return self.fetch(
            self.trades(**filters)
            .select(["exchange", "security_id", "count(*) as n"])
            .groupby(["exchange", "security_id"])
            .sort(["exchange", "security_id"])
        )
