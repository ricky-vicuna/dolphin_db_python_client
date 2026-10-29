"""Conversion regressions that run without a DolphinDB server."""

import unittest
from datetime import date, datetime

import pandas as pd

from data_processing.trades_types import (
    Exchange,
    ExecType,
    TickTradeDBItem,
    TradeBSFlag,
)
from dolphin_db_python_client import TickClient
from dolphin_db_python_client.db_handler import _parse_row, _to_frame


class TradeConversionTests(unittest.TestCase):
    def test_szse_raw_conversion(self):
        item = _parse_row(
            [
                "SzseTrade",
                "2026-10-27 09:42:03.123456",
                "20261027094203123",
                "000338",
                "F",
                "21.5",
                "12300",
            ],
            date(2026, 10, 27),
        )
        self.assertEqual(item.exchange, Exchange.SZSE)
        self.assertEqual(item.type, ExecType.F)
        self.assertEqual(item.security_id, "000338")
        self.assertEqual(item.trade_price, 21.5)
        self.assertEqual(item.trade_quantity, 123)
        self.assertEqual(item.recv_dt.isoformat(), "2026-10-27T09:42:03.123456+08:00")
        self.assertEqual(item.event_dt.isoformat(), "2026-10-27T09:42:03.123000+08:00")

    def test_sse_raw_conversion(self):
        item = _parse_row(
            [
                "SseTrade",
                "2026-10-27 09:42:03.123456",
                "9420311",
                "600000",
                "B",
                "10.25",
                "123000",
            ],
            date(2026, 10, 27),
        )
        self.assertEqual(item.exchange, Exchange.SSE)
        self.assertEqual(item.type, TradeBSFlag.B)
        self.assertEqual(item.trade_quantity, 123)
        self.assertEqual(item.event_dt.isoformat(), "2026-10-27T09:42:03.110000+08:00")

    def test_upload_frame_keeps_shanghai_clock_and_microseconds(self):
        item = TickTradeDBItem(
            exchange=Exchange.SZSE,
            recv_dt=datetime.fromisoformat("2026-10-27T01:30:00.123456+00:00"),
            event_dt=datetime.fromisoformat("2026-10-27T09:30:00.110000+08:00"),
            security_id="000338",
            type=ExecType.CANCEL,
            trade_price=21.5,
            trade_quantity=123,
        )
        frame = _to_frame([item])
        self.assertEqual(
            frame["recv_dt"].iloc[0], pd.Timestamp("2026-10-27 09:30:00.123456")
        )
        self.assertEqual(
            frame["event_dt"].iloc[0], pd.Timestamp("2026-10-27 09:30:00.110000")
        )
        self.assertEqual(str(frame["recv_dt"].dtype), "datetime64[ns]")
        self.assertEqual(frame["exchange"].iloc[0], "SZSE")
        self.assertEqual(frame["type"].iloc[0], "4")
        self.assertEqual(frame["security_id"].iloc[0], "000338")

    def test_invalid_filter_rejected_before_connecting(self):
        client = TickClient()
        with self.assertRaisesRegex(ValueError, "six-digit"):
            client.trades(security_id="000338.SZ")
        with self.assertRaisesRegex(ValueError, "exchange"):
            client.trades(exchange="INVALID")


if __name__ == "__main__":
    unittest.main()
