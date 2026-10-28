"""Profile upstream CSV exports without third-party dependencies or unit assumptions."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def profile(directory):
    groups = {}
    files = []
    malformed = []
    for path in sorted(directory.glob("*.csv")):
        count = 0
        types = Counter()
        previous = {}
        backwards = Counter()
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for line, row in enumerate(csv.reader(handle), 1):
                count += 1
                if len(row) != 7:
                    malformed.append({"file": path.name, "line": line, "fields": len(row)})
                    continue
                kind, received, event, security, flag, price, qty = row
                types[kind] += 1
                group = groups.setdefault(kind, {
                    "rows": 0, "symbols": Counter(), "flags": Counter(),
                    "event_lengths": Counter(), "receive_dates": Counter(),
                    "ranges": {}, "examples": [], "zero_price": 0, "zero_qty": 0,
                })
                group["rows"] += 1
                group["symbols"][security] += 1
                group["flags"][flag] += 1
                group["event_lengths"][len(event)] += 1
                group["receive_dates"][received[:10]] += 1
                values = {"received": received, "event_raw": int(event),
                          "price_exported": float(price), "qty_raw": int(qty)}
                for key, value in values.items():
                    bounds = group["ranges"].setdefault(key, [value, value])
                    bounds[0] = min(bounds[0], value)
                    bounds[1] = max(bounds[1], value)
                group["zero_price"] += float(price) == 0
                group["zero_qty"] += int(qty) == 0
                if len(group["examples"]) < 3:
                    group["examples"].append(row)
                key = (kind, security)
                if key in previous and int(event) < previous[key]:
                    backwards[kind] += 1
                previous[key] = int(event)
        files.append({"file": path.name, "bytes": path.stat().st_size,
                      "rows": count, "message_types": types,
                      "event_backwards_within_file_symbol": backwards})
    return {"files": files, "groups": groups, "malformed": malformed,
            "total_rows": sum(f["rows"] for f in files),
            "total_bytes": sum(f["bytes"] for f in files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(profile(args.directory), indent=2, ensure_ascii=False))
