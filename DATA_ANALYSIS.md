# Sample feed analysis

## Reproduce

```sh
python3 scripts/profile_sample.py A50-20261027-Stock > sample_profile.json
```

The profiler uses only the Python standard library. No uv environment or DolphinDB server is required. Original CSVs are not modified.

## Observations

- 51 headerless CSV files, 262,608,775 bytes, 3,511,608 records.
- All records have seven fields; all files contain both exchanges.
- Inferred columns: message type, receive/export timestamp, raw exchange time, security code, exchange-specific flag, exported price, raw quantity.
- Receive timestamp semantics and timezone require confirmation from the exporter.
- SSE: 2,428,220 rows, 36 securities. Flags B=1,283,667, S=1,123,389, N=21,164.
- SZSE: 1,083,388 rows, 14 securities. All flags F; no cancellation records in this sample.
- Receive dates are all 2026-10-27, approximately 09:25–11:30. This is not a full trading day.
- SZSE raw event time has 17 digits, consistent with yyyyMMddHHmmssSSS.
- SSE raw event time has 7–8 digits (9250000–11295999), consistent with zero-padded HHmmsscc (centiseconds), but this needs upstream confirmation.
- No decreasing raw event times within a file and (message type, security) group. This does not establish ordering across files or uniqueness.
- Every exported price is integral despite six decimal places. SSE price range 5–1352; SZSE 18–617. Investigate integer division/truncation in the exporter before using prices for research.
- SSE quantities are all divisible by 1000; SZSE quantities by 100. This is consistent with the provided struct scales, but export semantics must be confirmed.
- CSVs omit channel, sequence numbers, order IDs and SSE trade money. Exact feed-event deduplication and order reconstruction cannot be established from these columns alone.
- No quotes are present, so a real trades/quotes asof join needs another input.

## Proposed schema

Preserve raw imports before applying confirmed normalization rules.

| Field | DolphinDB type | Meaning |
| --- | --- | --- |
| trade_date | DATE | Exchange trading date |
| exchange | SYMBOL | SSE or SZSE, derived from message type |
| security_id | SYMBOL | Six-character code; preserve leading zeroes |
| symbol | SYMBOL | Canonical identifier, e.g. 000338.SZ or 601328.SH |
| event_ts | NANOTIMESTAMP | Normalized exchange time; original precision is unchanged |
| recv_ts | NANOTIMESTAMP | Export column 2; semantics/timezone to confirm |
| event_time_raw | LONG | Original numeric event time |
| message_type | SYMBOL | SseTrade or SzseTrade |
| source_flag | SYMBOL | Original exchange-specific flag |
| exec_type | SYMBOL | SZSE execution/cancellation classification, null for SSE |
| bs_flag | SYMBOL | SSE flag, null for SZSE |
| price_exported | DECIMAL64(4) | CSV value, not proof of original precision |
| qty_raw | LONG | Quantity before confirmed scale conversion |
| quantity | DECIMAL64(3) | Populate after confirmation of quantity scales/units |
| source_file | SYMBOL | Import provenance |
| source_row | LONG | 1-based CSV record number, not an exchange sequence |

Time policy: document Asia/Shanghai exchange-local semantics or convert consistently to UTC before upload. DolphinDB temporal columns do not carry timezone metadata.

SYMBOL provides dictionary encoding; do not persist internal symbol codes as application security IDs. A separate instrument master should carry stable identity and listing attributes if needed.

For a growing tick store, evaluate TSDB with date partitions, optional symbol hash subpartitions, sortColumns symbol/event_ts and keepDuplicates=ALL. Choose partition sizes using actual daily volume. Equal timestamps are not duplicate event identifiers. Filtering an exchange column alone does not guarantee partition pruning.

Maintain a small daily observed-universe table (trade_date, exchange, symbol, row_count), populated during ingestion, for fast coverage queries. This is the observed feed universe, not the full listed or strategy-eligible universe. A complete historical universe requires an instrument master with effective dates and listing/status data.

## Open questions before normalized ingestion

1. Can the CSV exporter code be supplied, especially price division and quantity conversion?
2. What is the official SSE TradeTime layout and resolution?
3. What does timestamp column 2 represent, and what timezone does it use?
4. Can future exports include channel, event sequence, order IDs and trade money?

## Official reference

- SYMBOL dictionary encoding: https://docs.dolphindb.com/en/Functions/s/symbolCode.html

## Environment plan

After Homebrew uv installation finishes, create a Python 3.12 environment with numpy, pandas, polars, pyarrow and dolphindb. No environment installation or server launch was performed during this analysis.
