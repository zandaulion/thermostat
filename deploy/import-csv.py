"""Load an existing temp_log.csv into the readings database.

The CSV timestamps are naive local time, written by a logger running in
Europe/Bucharest; the database stores UTC. Getting that wrong shifts every
historical point by two or three hours depending on the season, which is
exactly the kind of error that looks plausible on a chart.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app")
from thermo import store  # noqa: E402
from thermo.db import connect  # noqa: E402

LOCAL = ZoneInfo("Europe/Bucharest")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(path: str) -> None:
    store.init()
    rows, skipped = [], 0
    with open(path, newline="", encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            raw = (rec.get("Timestamp") or "").strip()
            try:
                # fold=0 resolves the ambiguous hour when clocks go back to
                # the first (summer-time) occurrence, deterministically.
                ts = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=LOCAL, fold=0
                )
            except ValueError:
                skipped += 1
                continue
            rows.append({
                "ts": ts.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds"),
                "location": (rec.get("Location") or "").strip(),
                "room": (rec.get("Room") or "").strip() or None,
                "device": (rec.get("Device Name") or "").strip() or None,
                "zone": (rec.get("Zone") or "").strip() or None,
                "temperature": num(rec.get("Temperature")),
                "humidity": num(rec.get("Humidity")),
                "setpoint": num(rec.get("Setpoint")),
                "status": (rec.get("Status") or "").strip() or None,
            })

    written = store._insert_blocking(rows)
    with connect() as con:
        n, first, last = con.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM readings").fetchone()
        locs = [r[0] for r in con.execute(
            "SELECT DISTINCT location FROM readings ORDER BY location")]
    print(f"  read {len(rows)} rows, {skipped} unparseable")
    print(f"  inserted {written} (duplicates ignored)")
    print(f"  database now holds {n} readings")
    print(f"  from {first} to {last}")
    print(f"  locations: {', '.join(locs)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/import/temp_log.csv")
