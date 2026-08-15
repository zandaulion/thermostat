"""Collect readings from the Salus and Tuya clouds.

Reuses the existing fetchers rather than reimplementing them -- read_temp.py
and tuya_temp.py already know the quirks of both APIs, and those quirks are
the hard part.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("thermo.poller")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "600"))


def _to_row(rec: list, now: str) -> dict:
    """The fetchers return the CSV row order:
    Timestamp, Location, Room, Device, Zone, Temperature, Humidity,
    Setpoint, Status."""
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return {
        "ts": now,
        "location": rec[1],
        "room": rec[2],
        "device": rec[3],
        "zone": rec[4],
        "temperature": num(rec[5]),
        "humidity": num(rec[6]),
        "setpoint": num(rec[7]),
        "status": (str(rec[8]) if len(rec) > 8 and rec[8] is not None else None),
        # Appended later than the rest, so older callers may not send it.
        "battery": num(rec[9]) if len(rec) > 9 else None,
    }


async def collect() -> tuple[list[dict], list[str]]:
    """-> (rows, errors). A failure of one source must not lose the other."""
    rows: list[dict] = []
    errors: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        import log_temp
        records, err = await log_temp.fetch_all()
        if err:
            # Partial success is normal here: one cloud can be down while the
            # other answers. Keep whatever arrived and report the rest.
            errors.append(err)
        for rec in records or []:
            try:
                rows.append(_to_row(rec, now))
            except Exception as exc:  # noqa: BLE001 - one bad row is not all of them
                errors.append(f"row: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        log.warning("collection failed: %s", exc)

    return rows, errors
