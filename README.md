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

Imports each file through `db_handler.handler()` into persistent
`dfs://python_ticks / python_trades`, in batches of 10,000 rows. The raw
Pydantic models' `.to_db()` methods supply the time and quantity conversions;
the SSE trading day comes from the `YYYYMMDD` in the filename.

The table follows `TickTradeDBItem` exactly:

| Column | DolphinDB type |
| --- | --- |
| `exchange` | SYMBOL (`SSE` / `SZSE`) |
| `recv_dt` | NANOTIMESTAMP |
| `event_dt` | NANOTIMESTAMP |
| `security_id` | STRING (six digits, preserving leading zeros) |
| `type` | SYMBOL (ExecType / TradeBSFlag values) |
| `trade_price` | DOUBLE |
| `trade_quantity` | LONG |

Both timestamps store **Asia/Shanghai local wall time**. DolphinDB does not
store timezone metadata; `TickClient.fetch()` attaches `Asia/Shanghai` when
downloading. The current sample uses OLAP with 8 security-id-hash partitions.

Imports **append**: reimporting a file duplicates its rows. If an import fails,
earlier successfully written batches remain. The old `dfs://sample_ticks/trades`
raw-export layout is no longer the target of this client or its CLI.

## Query from the terminal

```sh
uv run --env-file .env dolphin-db-python-client count
uv run --env-file .env dolphin-db-python-client count --exchange SZSE
uv run --env-file .env dolphin-db-python-client universe --exchange SSE
uv run --env-file .env dolphin-db-python-client query --exchange SZSE --security-id 000338 --day 2026-10-27 --limit 10
uv run --env-file .env dolphin-db-python-client query --exchange SZSE --security-id 000338 --limit 1000 --parquet output/sample.parquet
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
        client.trades(day="2026-10-27", exchange="SZSE", security_id="000338")
        .select([
            "exchange", "recv_dt", "event_dt", "security_id", "type",
            "trade_price", "trade_quantity",
        ])
        .sort(["event_dt", "recv_dt"])
        .top(1000)
    )
    df = client.fetch(query, output="polars")
    # Other choices: output="pandas" or output="arrow".

# Fully downloaded results remain usable after the session closes.
df.write_parquet("sample.parquet", compression="zstd")
lazy = pl.scan_parquet("sample.parquet")
```

`day` filters `event_dt` using the Shanghai calendar day, including midnight
at the start and excluding midnight of the next day. `exchange` also accepts
`Exchange.SZSE` / `Exchange.SSE`. Use `security_id="000338"` rather than a
suffixed `symbol="000338.SZ"`.

`fetch()` returns string Enum values (`"SZSE"`, `"F"`, etc.) and timezone-aware
timestamps in pandas, Polars, and Arrow. Parquet round-trips the timezone.
If you need Pydantic objects rather than a DataFrame, fetch all seven fields:

```python
from data_processing.trades_types import TickTradeDBItem

items = [TickTradeDBItem.model_validate(row) for row in df.iter_rows(named=True)]
```

The Table API generates server queries internally; DolphinDB still executes
them. It is not a separate Python query engine. `.select()` expressions use
DolphinDB expression syntax. Database creation and upload plumbing use small
internal server scripts. `client.fetch()` downloads through pandas before
converting to Polars or Arrow; use bounded queries for large results.

## Join tests

Tests use Python's built-in `unittest`; no extra test dependency is needed.

```sh
uv run make check
uv run make test
uv run --env-file .env make test-integration
```

- `make test`: offline unit tests for raw-model conversion, quantity scales,
  leading zeros, and Shanghai timestamp handling.
- `make test-integration`: connects to DolphinDB, uploads fixed Pydantic trades
  into session-local tables, then checks actual server results against explicit
  expected numbers. A connection/configuration error fails the run.

Integration tests cover:

1. The seven-column schema, day boundaries, exchange/security filtering, count,
   grouped count, sorting, and limiting.
2. Inner/left merge on `exchange` + `security_id`, including an unmatched row.
3. Backward asof join: exact match, previous quote, no future quote, missing
   quotes, group isolation, and duplicate timestamps with a defined tie order.
4. pandas / Polars / Arrow output, Pydantic reconstruction, and Parquet
   timezone/precision round-trip.

For example, synthetic quotes for `SZSE/000338` have bid 20.5 at 09:30:00.100
and bid 20.75 at 09:30:00.200. Tests assert these asof results:

| Trade time | Expected bid |
| --- | --- |
| 09:30:00.000 | null (first quote is in the future) |
| 09:30:00.100 | 20.5 (exact match) |
| 09:30:00.150 | 20.5 (previous quote) |
| 09:30:00.300 | 20.75 (latest prior quote) |

See `tests/test_integration.py` for the complete fixed inputs and assertions.
The tests use the SDK's actual `.merge()` / `.merge_asof()` methods, not local
DataFrame joins. They use independent sessions and automatically release their
temporary tables on close. Run them repeatedly without adding any rows to
the persistent `python_trades` table.

For your own asof queries, sort the right table by
`exchange, security_id, event_dt` before joining, with `event_dt` as the last
join key. A session-local example is:

```python
# trades and quotes are remote Table objects in the same live session.
sorted_quotes = quotes.sort(["exchange", "security_id", "event_dt"]).executeAs("sorted_quotes")
query = trades.merge_asof(sorted_quotes, on=["exchange", "security_id", "event_dt"])
result = client.fetch(query)
```

If quotes have duplicate times, add a sequence column to the sort to define
which quote is last. Filter the appropriate date/session before joining if
quotes must not carry across trading days.

## Stop / resume

```sh
docker compose stop
docker compose start
```

`docker compose down` also retains the named volume. Adding `-v` deletes it.
Remote Table handles require a live session; downloaded frames and Parquet do not.
