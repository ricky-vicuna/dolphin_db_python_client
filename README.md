# dolphin_db_python_client

Python 3.12 / uv, DolphinDB Docker, and the official Python Table API.

## Start

```sh
uv sync
cp .env.example .env
# Set DDB_PASSWORD in .env (fresh image default account: admin / 123456).
docker compose up -d
```

The project uses `127.0.0.1:8849` and a dedicated Docker named volume.
The pinned 3.00.5 x86 image runs under Docker emulation on Apple Silicon.
Credentials are read from environment variables; `.env` is gitignored.
The local development server currently uses the image's initial admin account.

## Import

```sh
uv run --env-file .env dolphin-db-python-client ingest A50-20261027-Stock
```

Imports one file at a time into persistent `dfs://sample_ticks / trades`.
The initial dataset has 3,511,608 records, 36 SSE and 14 SZSE securities.
The sample store uses OLAP with 8 symbol-hash partitions; it is a simple
working sample, not the proposed production date-partitioned TSDB layout.

Reimport replaces rows with the same source filename before appending that
file. Use a single importer and unique filenames across input directories.
Delete + append is not atomic; rerun an interrupted import to repair the file.
No event-level deduplication is applied.

`exchange`, `symbol` and `security_id` are DolphinDB SYMBOL columns.
Prices are retained as exported DOUBLE values; quantities and exchange times
are retained as raw LONG values. No unconfirmed scale or SSE time conversion
is applied. `trade_date` is provisionally derived from the receive date for
this daytime sample. `recv_ts` retains nanosecond storage precision and the
CSV's timezone-naive clock values. See DATA_ANALYSIS.md for upstream questions.

## Query from the terminal

```sh
uv run --env-file .env dolphin-db-python-client count
uv run --env-file .env dolphin-db-python-client count --exchange SZSE
uv run --env-file .env dolphin-db-python-client universe --exchange SSE
uv run --env-file .env dolphin-db-python-client query --symbol 000338.SZ --day 2026-10-27 --limit 10
uv run --env-file .env dolphin-db-python-client query --symbol 000338.SZ --limit 1000 --parquet output/sample.parquet
```

`--limit` applies to the saved Parquet too (default 20); it is not a full export.
The universe command aggregates observed ticks, not the complete listed universe.

## Python API (no handwritten SQL query)

Run your script with `uv run --env-file .env your_script.py`:

```python
from dolphin_db_python_client import TickClient
import polars as pl

with TickClient() as client:
    print(client.count(exchange="SZSE"))
    print(client.universe(exchange="SSE"))

    # Remote Table API: filtering, sorting and limiting run on the server.
    query = (
        client.trades(day="2026-10-27", symbol="000338.SZ")
        .select(["symbol", "recv_ts", "event_time_raw", "price_exported", "qty_raw"])
        .sort(["event_time_raw", "recv_ts"])
        .top(1000)
    )
    df = client.fetch(query, output="polars")
    # Other choices: output="pandas" or output="arrow".

# Fully downloaded results remain usable after the session closes.
df.write_parquet("sample.parquet", compression="zstd")
lazy = pl.scan_parquet("sample.parquet")
```

The Table API generates server queries internally; DolphinDB still executes
them. It is not a separate Python query engine. `.select()` expressions use
DolphinDB expression syntax. Database creation and upload plumbing use small
internal server scripts. `client.fetch()` downloads through pandas before
converting to Polars or Arrow; use bounded queries for large results.

Remote tables also expose the SDK's `.merge()` and `.merge_asof()` methods.
The current sample contains trades only, and SSE time encoding is unconfirmed,
so no trades/quotes asof join is claimed or fabricated.

## Stop / resume

```sh
docker compose stop
docker compose start
```

`docker compose down` also retains the named volume. Adding `-v` deletes it.
Remote Table handles require a live session; downloaded frames and Parquet do not.
