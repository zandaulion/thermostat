"""Readings storage.

One row per sensor per poll. The Discord version appended to a CSV and re-read
the whole file with pandas for every plot; at 4 locations every 10 minutes
that is ~17k rows a month, and a month of history is a normal thing to ask
for. SQLite with an index answers the same question without loading the lot.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .db import connect

log = logging.getLogger("thermo.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,           -- ISO8601, UTC
    location    TEXT NOT NULL,
    room        TEXT,
    device      TEXT,
    zone        TEXT,
    temperature REAL,
    humidity    REAL,
    setpoint    REAL,
    status      TEXT,
    battery     REAL,
    -- When the sensor itself last reported, as distinct from `ts`, which is
    -- when we wrote the row. The two diverge when an upstream cloud keeps
    -- serving a dead device's last-known values: Tuya kept answering for days
    -- after a sensor went offline, and every poll looked fresh.
    reported_at TEXT
);
CREATE INDEX IF NOT EXISTS readings_loc_ts ON readings(location, ts);
CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts);
-- The poller can run twice for the same minute after a restart; this makes a
-- repeated insert a no-op rather than a duplicate point on the chart.
-- COALESCE is essential: SQLite treats NULLs as distinct in a UNIQUE index,
-- so a plain index on these columns silently stops deduplicating for any
-- source that leaves room or device unset.
CREATE UNIQUE INDEX IF NOT EXISTS readings_unique
    ON readings(location, COALESCE(room,''), COALESCE(device,''), ts);

-- A push source: anything that sends readings to /api/ingest rather than
-- being polled. Keeps the app independent of any one vendor's cloud, which
-- is how three sensors went dark when Tuya changed its pricing.
CREATE TABLE IF NOT EXISTS sources (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    location   TEXT NOT NULL,
    room       TEXT,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    last_seen  TEXT,
    revoked    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alert_state (
    key        TEXT PRIMARY KEY,         -- e.g. "cold:Snagov"
    firing     INTEGER NOT NULL DEFAULT 0,
    since      TEXT,
    last_sent  TEXT
);
"""


def init() -> None:
    with connect() as con:
        con.execute("PRAGMA journal_mode = WAL")
        # The first version of this index did not COALESCE and so failed to
        # deduplicate rows with a NULL room; replace it if present.
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='readings_unique'"
        ).fetchone()
        if row and row[0] and "COALESCE" not in row[0]:
            con.execute("DROP INDEX readings_unique")
            log.info("rebuilding readings_unique to handle NULL room/device")
        con.executescript(SCHEMA)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(readings)")}
        if "battery" not in cols:
            con.execute("ALTER TABLE readings ADD COLUMN battery REAL")
            log.info("migrated readings: added battery")
        if "reported_at" not in cols:
            con.execute("ALTER TABLE readings ADD COLUMN reported_at TEXT")
            log.info("migrated readings: added reported_at")


def _insert_blocking(rows: list[dict]) -> int:
    if not rows:
        return 0
    with connect() as con:
        cur = con.executemany(
            """INSERT OR IGNORE INTO readings
                 (ts, location, room, device, zone, temperature, humidity,
                  setpoint, status, battery, reported_at)
               VALUES (:ts, :location, :room, :device, :zone, :temperature,
                       :humidity, :setpoint, :status, :battery, :reported_at)""",
            rows,
        )
        return cur.rowcount


async def insert(rows: list[dict]) -> int:
    return await asyncio.to_thread(_insert_blocking, rows)


def _latest_blocking() -> list[dict]:
    with connect() as con:
        return [
            dict(r)
            for r in con.execute(
                """SELECT r.* FROM readings r
                   JOIN (SELECT location, room, device, MAX(ts) AS ts
                           FROM readings GROUP BY location, room, device) m
                     ON m.location = r.location AND m.room IS r.room
                    AND m.device IS r.device AND m.ts = r.ts
                  ORDER BY r.location"""
            )
        ]


async def latest() -> list[dict]:
    return await asyncio.to_thread(_latest_blocking)


def _history_blocking(location: str | None, hours: int, max_points: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with connect() as con:
        if location:
            rows = con.execute(
                """SELECT ts, location, temperature, humidity, setpoint,
                          status, battery
                     FROM readings WHERE location = ? AND ts >= ? ORDER BY ts""",
                (location, since),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT ts, location, temperature, humidity, setpoint,
                          status, battery
                     FROM readings WHERE ts >= ? ORDER BY ts""",
                (since,),
            ).fetchall()
    out = [dict(r) for r in rows]
    # Thin evenly rather than truncating: a month of 10-minute samples is
    # ~4300 points per location, far more than any phone screen can show.
    if len(out) > max_points:
        step = len(out) / max_points
        out = [out[int(i * step)] for i in range(max_points)]
    return out


async def history(location: str | None, hours: int, max_points: int = 600) -> list[dict]:
    return await asyncio.to_thread(_history_blocking, location, hours, max_points)


def _locations_blocking() -> list[str]:
    with connect() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT location FROM readings ORDER BY location")]


async def locations() -> list[str]:
    return await asyncio.to_thread(_locations_blocking)


def _source_by_token_blocking(token_hash: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM sources WHERE token_hash = ? AND revoked = 0",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        con.execute(
            "UPDATE sources SET last_seen = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), row["id"]),
        )
        return dict(row)


async def source_by_token(token_hash: str) -> dict | None:
    return await asyncio.to_thread(_source_by_token_blocking, token_hash)


def _add_source_blocking(name: str, location: str, room: str | None,
                         token_hash: str) -> int:
    with connect() as con:
        cur = con.execute(
            """INSERT INTO sources (name, location, room, token_hash, created_at)
               VALUES (?,?,?,?,?)""",
            (name, location, room, token_hash,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        return cur.lastrowid


async def add_source(name: str, location: str, room: str | None,
                     token_hash: str) -> int:
    return await asyncio.to_thread(_add_source_blocking, name, location, room, token_hash)


def _list_sources_blocking() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(
            """SELECT id, name, location, room, created_at, last_seen, revoked
                 FROM sources ORDER BY id""")]


async def list_sources() -> list[dict]:
    return await asyncio.to_thread(_list_sources_blocking)


def _revoke_source_blocking(source_id: int, revoked: bool) -> bool:
    with connect() as con:
        cur = con.execute("UPDATE sources SET revoked = ? WHERE id = ?",
                          (int(revoked), source_id))
        return cur.rowcount > 0


async def revoke_source(source_id: int, revoked: bool = True) -> bool:
    return await asyncio.to_thread(_revoke_source_blocking, source_id, revoked)


def _stats_blocking() -> dict:
    with connect() as con:
        n, first, last = con.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM readings").fetchone()
        return {"readings": n, "first": first, "last": last}


async def stats() -> dict:
    return await asyncio.to_thread(_stats_blocking)
