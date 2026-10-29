"""Import the seven-column CSV export, preserving unconfirmed units."""

from pathlib import Path

import polars as pl

from .client import DB_PATH, TickClient

COLUMNS = [
    "message_type",
    "recv_ts",
    "event_time_raw",
    "security_id",
    "source_flag",
    "price_exported",
    "qty_raw",
]


def read_batch(path):
    frame = pl.read_csv(
        path,
        has_header=False,
        new_columns=COLUMNS,
        schema_overrides={name: pl.String for name in COLUMNS},
    )
    unknown = set(frame["message_type"].unique()) - {"SseTrade", "SzseTrade"}
    if unknown:
        raise ValueError(f"Unknown message types: {unknown}")
    frame = (
        frame.with_row_index("source_row", offset=1)
        .with_columns(
            pl.col("recv_ts").str.to_datetime("%Y-%m-%d %H:%M:%S%.f", time_unit="ns"),
            pl.col("event_time_raw").cast(pl.Int64),
            pl.col("qty_raw").cast(pl.Int64),
            pl.col("price_exported").cast(pl.Float64),
            pl.col("source_row").cast(pl.Int64),
            pl.when(pl.col("message_type") == "SseTrade")
            .then(pl.lit("SSE"))
            .otherwise(pl.lit("SZSE"))
            .alias("exchange"),
            pl.lit(path.name).alias("source_file"),
        )
        .with_columns(
            pl.col("recv_ts").dt.date().alias("trade_date"),
            (
                pl.col("security_id")
                + pl.when(pl.col("exchange") == "SSE")
                .then(pl.lit(".SH"))
                .otherwise(pl.lit(".SZ"))
            ).alias("symbol"),
        )
    )
    return frame.select(
        "trade_date",
        "exchange",
        "symbol",
        "security_id",
        "recv_ts",
        "event_time_raw",
        "message_type",
        "source_flag",
        "price_exported",
        "qty_raw",
        "source_file",
        "source_row",
    )


def ingest(directory):
    paths = sorted(Path(directory).glob("*.csv"))
    if not paths:
        raise ValueError(f"No CSV files in {directory}")
    total = 0
    with TickClient() as client:
        session = client.session
        # DDL and upload plumbing use server scripts; user queries use Table API.
        session.run(f'''
            if (!existsDatabase("{DB_PATH}")) {{
                db = database("{DB_PATH}", HASH, [SYMBOL, 8])
                schemaTable = table(1:0,
                    `trade_date`exchange`symbol`security_id`recv_ts`event_time_raw`message_type`source_flag`price_exported`qty_raw`source_file`source_row,
                    [DATE,SYMBOL,SYMBOL,SYMBOL,NANOTIMESTAMP,LONG,SYMBOL,SYMBOL,DOUBLE,LONG,SYMBOL,LONG])
                db.createPartitionedTable(schemaTable, `trades, `symbol)
            }}
            target = loadTable("{DB_PATH}", "trades")
        ''')
        for path in paths:
            frame = read_batch(path)
            pdf = frame.to_pandas()
            # Explicit DATE type hint prevents pandas date objects becoming strings.
            pdf.__dict__["__DolphinDB_Type__"] = {"trade_date": 6}
            session.upload({"incoming": pdf, "importFile": path.name})
            # Single-writer, file-replacement import: rerun repairs an interrupted file.
            # Delete + append are not an atomic transaction.
            session.run("""
                delete from target where source_file = importFile
                tableInsert(target, incoming)
                undef(`incoming)
            """)
            total += frame.height
            print(f"Imported {path.name}: {frame.height:,} rows", flush=True)
        actual = client.count()
        print(f"Imported {total:,} rows; database contains {actual:,} rows")
