"""Fixed-value joins on session-local DolphinDB tables; requires DDB_* env vars.

Each test uploads synthetic Pydantic trades and closes its own session afterward.
Quantities are distinct so they can identify rows in expected results. Quotes and
metadata are synthetic fixtures, including the same security_id on two exchanges.
"""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import dolphindb.settings as keys
import pandas as pd
import polars as pl
import pyarrow as pa
from polars.testing import assert_frame_equal

from data_processing.trades_types import (
    Exchange,
    ExecType,
    TickTradeDBItem,
    TradeBSFlag,
)
from dolphin_db_python_client import TickClient
from dolphin_db_python_client.db_handler import _to_frame

DAY = "2026-10-27"


def fixed_trades() -> list[TickTradeDBItem]:
    # Deliberately unsorted. The three midnight rows test day boundaries.
    rows = [
        ("SZSE", "000338", "2026-10-27T09:30:00.150000", 300),
        ("SSE", "000338", "2026-10-27T09:30:00.150000", 600),
        ("SZSE", "000338", "2026-10-27T09:30:00.000000", 100),
        ("SZSE", "000001", "2026-10-27T09:30:00.150000", 500),
        ("SZSE", "000338", "2026-10-27T09:30:00.300000", 400),
        ("SZSE", "000002", "2026-10-27T09:30:00.150000", 700),
        ("SZSE", "000338", "2026-10-27T09:30:00.100000", 200),
        ("SZSE", "000338", "2026-10-26T23:59:59.999999", 800),
        ("SZSE", "000338", "2026-10-27T00:00:00.000000", 900),
        ("SZSE", "000338", "2026-10-28T00:00:00.000000", 1000),
    ]
    items = []
    for exchange, security_id, event_time, quantity in rows:
        event_dt = datetime.fromisoformat(event_time + "+08:00")
        items.append(
            TickTradeDBItem(
                exchange=Exchange(exchange),
                recv_dt=event_dt + timedelta(microseconds=123456),
                event_dt=event_dt,
                security_id=security_id,
                type=ExecType.F if exchange == "SZSE" else TradeBSFlag.B,
                trade_price=21.0,
                trade_quantity=quantity,
            )
        )
    return items


class DolphinDBIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TickClient(db_path=None, table_name="test_trades")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.session.upload({"test_trades": _to_frame(fixed_trades())})

    def intraday_trades(self):
        return self.client.trades(day=DAY).where(
            "event_dt >= 2026.10.27T09:30:00.000000000"
        )

    def instruments(self):
        frame = pd.DataFrame(
            {
                "exchange": ["SZSE", "SZSE", "SSE"],
                "security_id": ["000338", "000001", "000338"],
                "lot_multiplier": [2, 3, 5],
            }
        )
        frame.__dict__["__DolphinDB_Type__"] = {
            "exchange": keys.DT_SYMBOL,
            "security_id": keys.DT_STRING,
            "lot_multiplier": keys.DT_LONG,
        }
        return self.client.session.table(data=frame)

    def test_schema_filters_count_sort_and_limit(self):
        schema = self.client.trades().schema
        self.assertEqual(schema["name"].tolist(), list(TickTradeDBItem.model_fields))
        self.assertEqual(
            schema["typeString"].tolist(),
            [
                "SYMBOL",
                "NANOTIMESTAMP",
                "NANOTIMESTAMP",
                "STRING",
                "SYMBOL",
                "DOUBLE",
                "LONG",
            ],
        )
        self.assertEqual(self.client.count(), 10)
        self.assertEqual(self.client.count(day=DAY), 8)
        self.assertEqual(self.client.count(day=DAY, exchange=Exchange.SZSE), 7)
        self.assertEqual(self.client.count(day=DAY, exchange="SSE"), 1)
        query = (
            self.client.trades(day=DAY, exchange="SZSE", security_id="000338")
            .sort(["event_dt", "recv_dt"])
            .top(3)
        )
        self.assertEqual(
            self.client.fetch(query)["trade_quantity"].to_list(), [900, 100, 200]
        )
        self.assertEqual(
            self.client.universe(day=DAY).rows(),
            [
                ("SSE", "000338", 1),
                ("SZSE", "000001", 1),
                ("SZSE", "000002", 1),
                ("SZSE", "000338", 5),
            ],
        )

    def test_inner_merge_matches_both_exchange_and_security_id(self):
        instruments = self.instruments()
        query = (
            self.intraday_trades()
            .merge(instruments, how="inner", on=["exchange", "security_id"])
            .select(
                [
                    "trade_quantity",
                    "trade_quantity * lot_multiplier as weighted_quantity",
                ]
            )
            .sort("trade_quantity")
        )
        self.assertEqual(
            self.client.fetch(query).rows(),
            [
                (100, 200),
                (200, 400),
                (300, 600),
                (400, 800),
                (500, 1500),
                (600, 3000),
            ],
        )

    def test_left_merge_keeps_unmatched_trade(self):
        instruments = self.instruments()
        query = (
            self.intraday_trades()
            .merge(instruments, how="left", on=["exchange", "security_id"])
            .select(
                [
                    "trade_quantity",
                    "trade_quantity * lot_multiplier as weighted_quantity",
                ]
            )
            .sort("trade_quantity")
        )
        self.assertEqual(
            self.client.fetch(query).rows(),
            [
                (100, 200),
                (200, 400),
                (300, 600),
                (400, 800),
                (500, 1500),
                (600, 3000),
                (700, None),
            ],
        )

    def test_asof_exact_previous_no_future_and_duplicate_timestamp(self):
        quotes = pd.DataFrame(
            {
                "exchange": ["SZSE", "SZSE", "SZSE", "SSE", "SZSE"],
                "security_id": ["000338", "000338", "000001", "000338", "000338"],
                "event_dt": pd.to_datetime(
                    [
                        "2026-10-27 09:30:00.200",
                        "2026-10-27 09:30:00.100",
                        "2026-10-27 09:30:00.100",
                        "2026-10-27 09:30:00.100",
                        "2026-10-27 09:30:00.100",
                    ]
                ).astype("datetime64[ns]"),
                "bid": [20.75, 20.0, 30.0, 40.0, 20.5],
                "quote_seq": [3, 1, 4, 5, 2],
            }
        )
        quotes.__dict__["__DolphinDB_Type__"] = {
            "exchange": keys.DT_SYMBOL,
            "security_id": keys.DT_STRING,
            "event_dt": keys.DT_NANOTIMESTAMP,
            "bid": keys.DT_DOUBLE,
            "quote_seq": keys.DT_LONG,
        }
        uploaded = self.client.session.table(data=quotes)
        # Time must be ascending within each equality-key group. quote_seq breaks ties.
        right = uploaded.sort(
            ["exchange", "security_id", "event_dt", "quote_seq"]
        ).executeAs("test_sorted_quotes")
        query = (
            self.intraday_trades()
            .merge_asof(right, on=["exchange", "security_id", "event_dt"])
            .select(["trade_quantity", "bid", "quote_seq"])
            .sort("trade_quantity")
        )
        self.assertEqual(
            self.client.fetch(query).rows(),
            [
                (100, None, None),  # Trade before first quote: no future match.
                (200, 20.5, 2),  # Exact timestamp: last duplicate (seq=2).
                (300, 20.5, 2),  # 150ms uses 100ms, not the future 200ms quote.
                (400, 20.75, 3),  # Latest prior quote.
                (500, 30.0, 4),  # Different security.
                (600, 40.0, 5),  # Same security_id, different exchange.
                (700, None, None),  # Security with no quotes.
            ],
        )

    def test_fetch_formats_pydantic_and_parquet_timezone_round_trip(self):
        query = self.intraday_trades().where("trade_quantity = 100")
        pdf = self.client.fetch(query, output="pandas")
        self.assertEqual(str(pdf["recv_dt"].dt.tz), "Asia/Shanghai")
        self.assertEqual(
            pdf["recv_dt"].iloc[0].isoformat(), "2026-10-27T09:30:00.123456+08:00"
        )
        self.assertEqual(
            pdf["event_dt"].iloc[0].isoformat(), "2026-10-27T09:30:00+08:00"
        )

        frame = self.client.fetch(query, output="polars")
        self.assertEqual(frame.schema["recv_dt"], pl.Datetime("ns", "Asia/Shanghai"))
        item = TickTradeDBItem.model_validate(frame.row(0, named=True))
        self.assertEqual(item.exchange, Exchange.SZSE)
        self.assertEqual(item.type, ExecType.F)
        self.assertEqual(item.security_id, "000338")
        arrow = self.client.fetch(query, output="arrow")
        self.assertEqual(
            arrow.schema.field("recv_dt").type, pa.timestamp("ns", "Asia/Shanghai")
        )
        self.assertEqual(
            arrow.schema.field("event_dt").type, pa.timestamp("ns", "Asia/Shanghai")
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trades.parquet"
            frame.write_parquet(path, compression="zstd")
            assert_frame_equal(pl.scan_parquet(path).collect(), frame)


if __name__ == "__main__":
    unittest.main()
