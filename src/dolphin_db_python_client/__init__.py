from .client import TickClient

__all__ = ["TickClient"]


def main() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Query python_trades through DolphinDB Python Table API"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    loader = sub.add_parser("ingest")
    loader.add_argument("directory")
    for name in ("query", "count", "universe"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--day")
        cmd.add_argument("--exchange", choices=["SSE", "SZSE"])
        cmd.add_argument("--security-id")
        if name == "query":
            cmd.add_argument("--limit", type=int, default=20)
            cmd.add_argument("--parquet", type=Path)
    args = parser.parse_args()
    if args.command == "ingest":
        from .ingest import ingest

        ingest(args.directory)
        return
    filters = {
        "day": args.day,
        "exchange": args.exchange,
        "security_id": args.security_id,
    }
    with TickClient() as client:
        if args.command == "count":
            print(client.count(**filters))
        elif args.command == "universe":
            print(client.universe(**filters))
        else:
            if args.limit <= 0:
                parser.error("--limit must be positive")
            query = (
                client.trades(**filters)
                .sort(["exchange", "security_id", "event_dt", "recv_dt"])
                .top(args.limit)
            )
            result = client.fetch(query)
            if args.parquet:
                args.parquet.parent.mkdir(parents=True, exist_ok=True)
                result.write_parquet(args.parquet, compression="zstd")
                print(f"Wrote {result.height} rows to {args.parquet}")
            else:
                print(result)
