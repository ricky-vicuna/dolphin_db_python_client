"""Small context-managed client using the official remote Table API."""

import os
import re
from datetime import date

import dolphindb as ddb
import polars as pl
import pyarrow as pa

DB_PATH = "dfs://sample_ticks"


class TickClient:
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

    def trades(self, *, day=None, exchange=None, symbol=None):
        """Return a remote Table; downloading is explicit via fetch()/toDF()."""
        table = self.session.loadTable("trades", dbPath=DB_PATH)
        if day:
            day = date.fromisoformat(str(day)).strftime("%Y.%m.%d")
            table = table.where(f"trade_date = {day}")
        if exchange:
            if exchange not in {"SSE", "SZSE"}:
                raise ValueError("exchange must be SSE or SZSE")
            table = table.where(f'exchange = "{exchange}"')
        if symbol:
            if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", symbol):
                raise ValueError("symbol must look like 000338.SZ or 601328.SH")
            table = table.where(f'symbol = "{symbol}"')
        return table

    @staticmethod
    def fetch(table, output="polars"):
        if output not in {"pandas", "polars", "arrow"}:
            raise ValueError("output must be pandas, polars or arrow")
        pdf = table.toDF()
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
            .select(["exchange", "symbol", "count(*) as n"])
            .groupby(["exchange", "symbol"])
            .sort(["exchange", "symbol"])
        )
