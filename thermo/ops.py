"""Operational alerts over ntfy.

Reports state *changes* only. A source that is down for six hours should
produce one message, not one per retry -- an alert channel that cries wolf
gets muted, and then it is worth nothing when something real happens.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

log = logging.getLogger("thermo.ops")

NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "")
APP_NAME = os.getenv("APP_NAME", "Termometru")

_enabled = bool(NTFY_TOPIC)
if not _enabled:
    log.info("ntfy alerts disabled (no NTFY_TOPIC set)")


PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5}


async def send(
    message: str,
    *,
    title: str | None = None,
    tags: str = "",
    priority: str = "default",
) -> None:
    """Fire and forget. An alert that fails must never take the app with it.

    Published as JSON rather than through ntfy's header API: HTTP headers are
    latin-1, so a title containing "Întârzieri" cannot be sent that way.
    """
    if not _enabled:
        return
    payload = {
        "topic": NTFY_TOPIC,
        "title": title or APP_NAME,
        "message": message,
        "priority": PRIORITY.get(priority, 3),
    }
    if tags:
        payload["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(NTFY_SERVER, json=payload, headers=headers)
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("ntfy send failed: %s", exc)


class Flapper:
    """Edge detector for a health signal.

    Holds one boolean and reports only when it flips, so repeated failures
    are silent after the first and recovery is announced exactly once.
    """

    def __init__(self, name: str, *, down: str, up: str) -> None:
        self.name = name
        self.down = down     # what to say when the signal goes bad
        self.up = up         # ... and when it comes back
        self.ok: bool | None = None

    async def set(self, ok: bool, detail: str = "") -> None:
        if self.ok is ok:
            return
        first = self.ok is None
        self.ok = ok
        if first and ok:
            return                       # healthy at startup is not news
        if ok:
            await send(
                f"{self.name} {self.up}" + (f"\n{detail}" if detail else ""),
                title=f"{APP_NAME}: revenit",
                tags="white_check_mark",
                priority="default",
            )
        else:
            await send(
                f"{self.name} {self.down}" + (f"\n{detail}" if detail else ""),
                title=f"{APP_NAME}: problemă",
                tags="rotating_light",
                priority="high",
            )


# Tracks whether a poll can read the device clouds at all -- Salus and Tuya.
# It is deliberately *not* about what those clouds report: a sensor that is
# switched off is a monitored condition with its own alert, not a failure of
# the collector. Conflating the two would pin this permanently unhealthy and,
# because it is edge-triggered, hide the next real outage behind a state it
# never left.
upstream = Flapper(
    "Citirea senzorilor",
    down="a eșuat.",
    up="funcționează din nou.",
)


def fire(coro) -> None:
    """Schedule an alert without making the caller wait for it."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        pass
