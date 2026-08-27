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
  battery  a flat battery *becomes* a silent sensor, at a property nobody is
           visiting; warning beforehand turns a post-mortem into an errand
  trial    the Tuya cloud subscription expires on a date, and when it does
           three sensors stop at once -- worth saying so in advance rather
           than letting it look like three simultaneous hardware failures
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
BATTERY_PCT = float(os.getenv("ALERT_BATTERY_PCT", "15"))
# ISO date, e.g. 2027-02-15. Empty disables the reminder.
TRIAL_EXPIRES = os.getenv("TUYA_TRIAL_EXPIRES", "").strip()
TRIAL_WARN_DAYS = [int(d) for d in
                   os.getenv("TRIAL_WARN_DAYS", "30,14,3").split(",") if d.strip()]


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


# Statuses that mean the upstream cloud is vouching for the device being
# reachable right now. "On"/"Off" are heating states, which the fetcher only
# infers for a device it is actually hearing from.
LIVENESS_KNOWN = {"online", "on", "off"}


def sensor_age_minutes(row: dict, now: datetime) -> float | None:
    """How long ago this reading was last confirmed.

    For a device we poll and that the cloud says is reachable, that is our own
    poll time: we asked, and this is what came back. `reported_at` cannot be
    used for it. Tuya's per-device `update_time` tracks datapoint reports on
    some devices and not on others -- the Home thermostat returns a changing
    `temp_current` on every poll while its `update_time` sits six days in the
    past, which showed a healthy sensor as "acum 6 zile".

    When the cloud says the device is *offline*, `reported_at` becomes the
    honest number and our poll time the misleading one: nothing was confirmed,
    and what matters is how long ago the device was last heard from.

    Sources that push to us are covered by the same rule from the other side.
    They write no row when they go quiet, so their newest `ts` stops advancing
    and its age grows on its own -- which is exactly what SILENT_MINUTES reads.
    """
    ts = row.get("reported_at") if is_offline(row) else row.get("ts")
    ts = ts or row.get("ts")
    if not ts:
        return None
    return (now - datetime.fromisoformat(ts)).total_seconds() / 60


def is_offline(row: dict) -> bool:
    return (row.get("status") or "").strip().lower().startswith("offline")


def is_silent(row: dict, now: datetime) -> bool:
    """A sensor we have stopped hearing from.

    Sources differ in what they can tell us, so this splits three ways:

      * the cloud says the device is offline -- authoritative, and true the
        moment it is reported rather than after a silence window;
      * the cloud vouches for it being online -- trust that over age. A
        battery T&H sensor legitimately goes hours between datapoints, and
        timing those out would cry wolf on a perfectly healthy sensor;
      * no liveness information at all, which is every push source -- fall
        back to the age timer, where arrival time really is report time.
    """
    if is_offline(row):
        return True
    if (row.get("status") or "").strip().lower() in LIVENESS_KNOWN:
        return False
    age = sensor_age_minutes(row, now)
    return age is not None and age > SILENT_MINUTES


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
        # --- sensor gone quiet ------------------------------------------
        silent = is_silent(row, now)
        edge = await _transition(f"silent:{loc}", silent)
        if edge == "fire":
            age = sensor_age_minutes(row, now)
            if age is None:
                since = "Nicio măsurătoare recentă."
            elif age < 120:
                since = f"Nicio măsurătoare de {int(age)} de minute."
            elif age < 48 * 60:
                since = f"Nicio măsurătoare de {int(age // 60)} de ore."
            else:
                since = f"Nicio măsurătoare de {int(age // 1440)} zile."
            out.append({
                "title": (f"{loc}: senzor deconectat" if is_offline(row)
                          else f"{loc}: senzorul tace"),
                "body": since,
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

        # --- battery running out ----------------------------------------
        batt = row.get("battery")
        if batt is not None:
            edge = await _transition(f"battery:{loc}", batt <= BATTERY_PCT)
            if edge == "fire":
                out.append({
                    "title": f"{loc}: baterie {batt:.0f}%",
                    "body": f"Sub {BATTERY_PCT:.0f}% — schimb-o înainte să tacă "
                            "senzorul.",
                    "tag": f"battery-{loc}", "priority": "high",
                })
            elif edge == "clear":
                out.append({
                    "title": f"{loc}: baterie schimbată",
                    "body": f"Acum {batt:.0f}%.",
                    "tag": f"battery-{loc}", "priority": "low",
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

    # --- the cloud subscription's own expiry ----------------------------
    if TRIAL_EXPIRES:
        try:
            expires = datetime.fromisoformat(TRIAL_EXPIRES).replace(tzinfo=timezone.utc)
            days = (expires - now).days
            # One rule per threshold, so each fires once as it is crossed
            # rather than repeating every poll for the last month.
            for d in sorted(TRIAL_WARN_DAYS, reverse=True):
                edge = await _transition(f"trial:{d}", 0 <= days <= d)
                if edge == "fire":
                    out.append({
                        "title": f"Abonamentul Tuya expiră în {days} zile",
                        "body": f"După {TRIAL_EXPIRES} senzorii Tuya se opresc. "
                                "Prelungește-l sau mută-i pe /api/ingest.",
                        "tag": "tuya-trial", "priority": "high",
                    })
                    break
            if days < 0:
                edge = await _transition("trial:expired", True)
                if edge == "fire":
                    out.append({
                        "title": "Abonamentul Tuya a expirat",
                        "body": "Senzorii Tuya nu mai răspund.",
                        "tag": "tuya-trial", "priority": "high",
                    })
        except ValueError:
            log.warning("TUYA_TRIAL_EXPIRES is not an ISO date: %r", TRIAL_EXPIRES)

    return out
