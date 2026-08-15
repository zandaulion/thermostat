"""Alert rules.

Edge-triggered: a condition that persists produces one notification, not one
per poll. A channel that repeats itself gets muted, and a muted channel is
worth nothing when something real happens.

Each rule needs a reason to exist beyond "we can measure it":

  cold     an unheated property in winter is a burst-pipe risk, and nobody
           is there to notice
  stuck    heating on continuously for hours means a stuck relay or a door
           left open; it costs money quietly
  silent   a sensor that stops reporting looks exactly like "everything is
           fine" on a dashboard, which is the dangerous failure
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from .db import connect

log = logging.getLogger("thermo.alerts")

COLD_C = float(os.getenv("ALERT_COLD_C", "8"))
HOT_C = float(os.getenv("ALERT_HOT_C", "30"))
STUCK_HOURS = float(os.getenv("ALERT_STUCK_HOURS", "6"))
SILENT_MINUTES = int(os.getenv("ALERT_SILENT_MINUTES", "90"))
# Never repeat the same firing alert more often than this, even if it clears
# and re-fires around the threshold.
COOLDOWN = timedelta(hours=float(os.getenv("ALERT_COOLDOWN_HOURS", "6")))


def _state_blocking(key: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM alert_state WHERE key = ?", (key,)).fetchone()
        return dict(r) if r else None


def _set_state_blocking(key: str, firing: bool, sent: bool) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        row = con.execute("SELECT * FROM alert_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO alert_state (key, firing, since, last_sent) VALUES (?,?,?,?)",
                (key, int(firing), now if firing else None, now if sent else None),
            )
            return
        since = row["since"] if row["firing"] and firing else (now if firing else None)
        last = now if sent else row["last_sent"]
        con.execute(
            "UPDATE alert_state SET firing = ?, since = ?, last_sent = ? WHERE key = ?",
            (int(firing), since, last, key),
        )


async def _transition(key: str, firing: bool) -> str | None:
    """-> 'fire' | 'clear' | None. Only edges, and only outside the cooldown."""
    st = await asyncio.to_thread(_state_blocking, key)
    was = bool(st and st["firing"])
    if firing == was:
        await asyncio.to_thread(_set_state_blocking, key, firing, False)
        return None

    if firing:
        last = st["last_sent"] if st and st["last_sent"] else None
        if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < COOLDOWN:
            # Flapping around a threshold: record the state, stay quiet.
            await asyncio.to_thread(_set_state_blocking, key, True, False)
            return None
        await asyncio.to_thread(_set_state_blocking, key, True, True)
        return "fire"

    await asyncio.to_thread(_set_state_blocking, key, False, False)
    return "clear"


def _hours_on(rows: list[dict]) -> float:
    """How long the most recent contiguous run of Status='On' has lasted."""
    on = 0.0
    prev_ts = None
    for r in reversed(rows):
        if (r.get("status") or "").strip().lower() != "on":
            break
        ts = datetime.fromisoformat(r["ts"])
        if prev_ts is not None:
            on += (prev_ts - ts).total_seconds() / 3600.0
        prev_ts = ts
    return on


async def evaluate(latest: list[dict], recent: dict[str, list[dict]]) -> list[dict]:
    """-> notifications to send. `recent` is per-location history, oldest first."""
    out: list[dict] = []
    now = datetime.now(timezone.utc)

    for row in latest:
        loc = row["location"]
        temp = row.get("temperature")
        ts = row.get("ts")

        # --- sensor gone quiet ------------------------------------------
        silent = False
        if ts:
            age = (now - datetime.fromisoformat(ts)).total_seconds() / 60
            silent = age > SILENT_MINUTES
        edge = await _transition(f"silent:{loc}", silent)
        if edge == "fire":
            out.append({
                "title": f"{loc}: senzorul tace",
                "body": f"Nicio măsurătoare de peste {SILENT_MINUTES} de minute.",
                "tag": f"silent-{loc}", "priority": "high",
            })
        elif edge == "clear":
            out.append({
                "title": f"{loc}: senzorul a revenit",
                "body": f"Măsurători din nou; {temp:.1f}°C." if temp is not None else "Măsurători din nou.",
                "tag": f"silent-{loc}", "priority": "default",
            })

        if silent or temp is None:
            continue

        # --- too cold ---------------------------------------------------
        edge = await _transition(f"cold:{loc}", temp <= COLD_C)
        if edge == "fire":
            out.append({
                "title": f"{loc}: {temp:.1f}°C",
                "body": f"Sub {COLD_C:.0f}°C — risc de îngheț.",
                "tag": f"cold-{loc}", "priority": "high",
            })
        elif edge == "clear":
            out.append({
                "title": f"{loc}: {temp:.1f}°C",
                "body": "Temperatura a revenit peste prag.",
                "tag": f"cold-{loc}", "priority": "low",
            })

        # --- too hot ----------------------------------------------------
        edge = await _transition(f"hot:{loc}", temp >= HOT_C)
        if edge == "fire":
            out.append({
                "title": f"{loc}: {temp:.1f}°C",
                "body": f"Peste {HOT_C:.0f}°C.",
                "tag": f"hot-{loc}", "priority": "default",
            })

        # --- heating stuck on -------------------------------------------
        hours = _hours_on(recent.get(loc, []))
        edge = await _transition(f"stuck:{loc}", hours >= STUCK_HOURS)
        if edge == "fire":
            out.append({
                "title": f"{loc}: încălzirea merge de {hours:.0f} h",
                "body": f"Continuu de peste {STUCK_HOURS:.0f} ore, acum {temp:.1f}°C.",
                "tag": f"stuck-{loc}", "priority": "high",
            })
        elif edge == "clear":
            out.append({
                "title": f"{loc}: încălzirea s-a oprit",
                "body": f"Acum {temp:.1f}°C.",
                "tag": f"stuck-{loc}", "priority": "low",
            })

    return out
