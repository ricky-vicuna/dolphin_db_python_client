"""Import a directory of raw CSVs using the TickTradeDBItem handler."""

from pathlib import Path

from .client import TickClient
from .db_handler import handler


def ingest(directory: str | Path) -> None:
    """Append each CSV to python_trades using the raw models' conversions."""
    paths = sorted(Path(directory).glob("*.csv"))
    if not paths:
        raise ValueError(f"No CSV files in {directory}")
    for path in paths:
        handler(path)
        print(f"Imported {path.name}", flush=True)
    with TickClient() as client:
        print(f"Imported {len(paths)} files; database contains {client.count():,} rows")
