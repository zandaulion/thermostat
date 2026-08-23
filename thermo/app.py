"""Temperature monitor API.

Polls the Salus and Tuya clouds on a fixed interval, stores readings, serves
them to a PWA, and pushes alerts when something needs attention. Access is
per-device by invite, the same model as the sibling project: no shared
password, and notifications can be targeted at one device.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import (Body, Depends, FastAPI, Header, HTTPException, Query,
                     Request, Response)
from fastapi.responses import ORJSONResponse

from . import accounts, alerts, ops, poller, push, store
from .db import connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("thermo")

POLL_SECONDS = poller.POLL_SECONDS


# --------------------------------------------------------------------------
# access control
# --------------------------------------------------------------------------
async def current_device(request: Request) -> dict:
    token = request.cookies.get(accounts.COOKIE_NAME)
    device = await accounts.device_by_token(token) if token else None
    if not device:
        raise HTTPException(
            401, "Acest dispozitiv nu este înregistrat. Ai nevoie de o invitație."
        )
    return device


async def admin_only(x_admin: str | None = Header(None)) -> None:
    """Admin is reachable only through the tailnet-only listener, which sets
    this header; the public site refuses those paths and strips it."""
    if x_admin != "1":
        raise HTTPException(404, "Not Found")


# --------------------------------------------------------------------------
# background work
# --------------------------------------------------------------------------
async def broadcast(items: list[dict]) -> None:
    """Alerts go to every registered device -- there is one household."""
    if not items:
        return
    with connect() as con:
        subs = [
            {"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}}
            for r in con.execute(
                """SELECT p.endpoint, p.p256dh, p.auth FROM push_subs p
                   JOIN devices d ON d.id = p.device_id AND d.revoked = 0"""
            )
        ]
    for item in items:
        for sub in subs:
            ok, status = await push.send(sub, item)
            if not ok and status in push.DEAD:
                with connect() as con:
                    con.execute("DELETE FROM push_subs WHERE endpoint = ?",
                                (sub["endpoint"],))
        log.info("alert sent to %d device(s): %s", len(subs), item["title"])


async def poll_once() -> dict:
    rows, errors = await poller.collect()
    written = await store.insert(rows)

    latest = await store.latest()
    recent = {}
    for loc in {r["location"] for r in latest}:
        recent[loc] = await store.history(loc, hours=int(alerts.STUCK_HOURS) + 2, max_points=200)
    try:
        await broadcast(await alerts.evaluate(latest, recent))
    except Exception as exc:  # noqa: BLE001 - alerting must not stop logging
        log.warning("alert evaluation failed: %s", exc)

    # Healthy means *nothing* failed. `not errors or rows` reads as "no
    # errors, or we got something", which is true whenever any source works --
    # so a partial failure reported as healthy and no alert was ever sent.
    await ops.upstream.set(not errors, "; ".join(errors)[:200])
    return {
        "collected": len(rows), "written": written, "errors": errors,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def loop() -> None:
    while True:
        try:
            result = await poll_once()
            app.state.last_poll = result
            log.info("poll: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("poll failed: %s", exc)
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    with connect() as con:
        accounts.init_schema(con)
    app.state.last_poll = None
    task = asyncio.create_task(loop())
    ops.fire(ops.send("Serviciul a pornit.", title=f"{ops.APP_NAME}: pornit",
                      tags="arrow_up", priority="low"))
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Termometru", default_response_class=ORJSONResponse,
              lifespan=lifespan)


# --------------------------------------------------------------------------
# readings
# --------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    # Offline sensors are listed separately from `last_poll.errors`: the poll
    # itself succeeded, so they are not collection failures, but they are still
    # the first thing worth seeing when the numbers on screen look wrong.
    n = datetime.now(timezone.utc)
    offline = [
        {"location": r["location"],
         "since": r.get("reported_at"),
         "age_minutes": int(alerts.sensor_age_minutes(r, n) or 0)}
        for r in await store.latest() if alerts.is_offline(r)
    ]
    return {"ok": True, "last_poll": getattr(app.state, "last_poll", None),
            "poll_seconds": POLL_SECONDS, "offline_sensors": offline,
            **(await store.stats())}


@app.get("/api/now")
async def now(device: dict = Depends(current_device)):
    rows = await store.latest()
    n = datetime.now(timezone.utc)
    for r in rows:
        # `ts` only says when we last wrote a row, which a cloud that keeps
        # serving a dead device's last-known values refreshes forever. Age and
        # staleness both come from the sensor's own clock, via the same rules
        # the alerting uses -- the tile and the notification must not disagree.
        r["age_minutes"] = int(alerts.sensor_age_minutes(r, n) or 0)
        r["offline"] = alerts.is_offline(r)
        r["stale"] = alerts.is_silent(r, n)
    return {"readings": rows,
            # Which location to show first. Configurable rather than
            # hardcoded, since which one matters most is a property of the
            # household, not of the code.
            "default_location": os.getenv("DEFAULT_LOCATION", "").strip() or None,
            "thresholds": {
        "cold_c": alerts.COLD_C, "hot_c": alerts.HOT_C,
        "stuck_hours": alerts.STUCK_HOURS,
        "silent_minutes": alerts.SILENT_MINUTES,
        "battery_pct": alerts.BATTERY_PCT}}


@app.get("/api/history")
async def history(
    location: str | None = Query(None),
    hours: int = Query(24, ge=1, le=24 * 400),
    device: dict = Depends(current_device),
):
    return {"location": location, "hours": hours,
            "points": await store.history(location, hours)}


@app.get("/api/locations")
async def locations(device: dict = Depends(current_device)):
    return {"locations": await store.locations()}


@app.get("/api/me")
async def me(device: dict = Depends(current_device)):
    return {"device": {"id": device["id"], "label": device["label"]}}


# --------------------------------------------------------------------------
# push + invites
# --------------------------------------------------------------------------
@app.get("/api/vapid")
async def vapid_key(device: dict = Depends(current_device)):
    return {"publicKey": push.vapid.public_key}


@app.post("/api/push/subscribe")
async def push_subscribe(payload: dict = Body(...),
                         device: dict = Depends(current_device)):
    sub = payload.get("subscription") or {}
    if not sub.get("endpoint") or not (sub.get("keys") or {}).get("auth"):
        raise HTTPException(400, "Abonarea la notificări este incompletă.")
    keys = sub["keys"]
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    await asyncio.to_thread(_save_sub, device["id"], sub["endpoint"],
                            keys.get("p256dh", ""), keys.get("auth", ""), now_iso)
    return {"ok": True}


def _save_sub(device_id: int, endpoint: str, p256dh: str, auth: str, now_iso: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM push_subs WHERE endpoint = ? AND device_id IS NOT ?",
                    (endpoint, device_id))
        con.execute(
            """INSERT INTO push_subs (device_id, endpoint, p256dh, auth, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(device_id) DO UPDATE SET endpoint=excluded.endpoint,
                     p256dh=excluded.p256dh, auth=excluded.auth""",
            (device_id, endpoint, p256dh, auth, now_iso),
        )


@app.post("/api/push/test")
async def push_test(payload: dict = Body(default={}),
                    device: dict = Depends(current_device)):
    sub = payload.get("subscription") or {}
    if not sub.get("endpoint"):
        raise HTTPException(400, "Este necesară abonarea la notificări.")
    ok, status = await push.send(sub, {
        "title": "Notificările funcționează",
        "body": "Vei primi o alertă când o locuință se răcește prea tare, "
                "când încălzirea rămâne pornită sau când un senzor tace.",
        "tag": "test"})
    return {"delivered": ok, "status": status}


@app.post("/api/invites/redeem")
async def redeem_invite(response: Response, payload: dict = Body(...)):
    if accounts.throttled():
        raise HTTPException(429, "Prea multe încercări. Așteaptă un minut.")
    code = accounts.normalise_code(payload.get("code") or "")
    if not code:
        raise HTTPException(400, "Nu pare a fi un cod de invitație.")
    try:
        device_id, token = await accounts.redeem(code)
    except accounts.InviteError as exc:
        raise HTTPException(400, str(exc))
    response.set_cookie(accounts.COOKIE_NAME, token,
                        max_age=accounts.COOKIE_MAX_AGE, httponly=True,
                        secure=accounts.COOKIE_SECURE, samesite="lax", path="/")
    return {"ok": True, "device_id": device_id}


# --------------------------------------------------------------------------
# admin (tailnet only)
# --------------------------------------------------------------------------
@app.get("/api/admin/devices", dependencies=[Depends(admin_only)])
async def admin_devices():
    return {"devices": await accounts.list_devices()}


@app.post("/api/admin/devices/{device_id}/revoke", dependencies=[Depends(admin_only)])
async def admin_revoke(device_id: int, payload: dict = Body(default={})):
    if not await accounts.set_revoked(device_id, bool(payload.get("revoked", True))):
        raise HTTPException(404, "no such device")
    return {"id": device_id}


@app.delete("/api/admin/devices/{device_id}", dependencies=[Depends(admin_only)])
async def admin_delete(device_id: int):
    if not await accounts.delete_device(device_id):
        raise HTTPException(404, "no such device")
    return {"deleted": device_id}


@app.get("/api/admin/invites", dependencies=[Depends(admin_only)])
async def admin_invites():
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    invites = await accounts.list_invites()
    for i in invites:
        code = i.pop("code_plain", None)
        i["code"] = code
        i["url"] = f"{base}/i/{code}" if code and base else None
    return {"invites": invites, "ttl_days": accounts.INVITE_TTL.days}


@app.post("/api/admin/invites", dependencies=[Depends(admin_only)])
async def admin_create_invite(payload: dict = Body(default={})):
    label = (payload.get("label") or "").strip()[:60] or None
    code = await accounts.create_invite(label)
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return {"code": code, "url": f"{base}/i/{code}" if base else None,
            "expires_in_days": accounts.INVITE_TTL.days, "label": label}


@app.post("/api/admin/invites/{invite_id}/revoke", dependencies=[Depends(admin_only)])
async def admin_revoke_invite(invite_id: int):
    if not await accounts.revoke_invite(invite_id):
        raise HTTPException(404, "no such unused invite")
    return {"revoked": invite_id}


@app.post("/api/admin/devices/{device_id}/label", dependencies=[Depends(admin_only)])
async def admin_label_device(device_id: int, payload: dict = Body(...)):
    """A device's label comes from the invite that registered it, so it is
    often the wrong name -- whoever the invite was minted for rather than
    whoever redeemed it."""
    label = (payload.get("label") or "").strip()[:60]
    if not await accounts.rename_device(device_id, label):
        raise HTTPException(404, "no such device")
    return {"id": device_id, "label": label}


@app.post("/api/admin/devices/prune", dependencies=[Depends(admin_only)])
async def admin_prune_devices():
    """Deletes revoked devices. Revoking is the reversible step; this is the
    one that is not."""
    return {"deleted": await accounts.prune_devices()}


@app.post("/api/admin/invites/prune", dependencies=[Depends(admin_only)])
async def admin_prune_invites():
    """Drops invites that can no longer register anything -- used, or expired
    unused. Pending ones are left alone by the query itself."""
    return {"deleted": await accounts.prune_invites()}


@app.post("/api/admin/poll", dependencies=[Depends(admin_only)])
async def admin_poll():
    return await poll_once()


# --------------------------------------------------------------------------
# ingest — readings pushed in, rather than polled out
# --------------------------------------------------------------------------
def _first_float(payload: dict, *names) -> float | None:
    """Accept whatever a device calls the field.

    Shelly sends `temp`, some send `temperature`, Tasmota sends `Temperature`.
    Being liberal here costs nothing and saves a per-vendor adapter.
    """
    for n in names:
        for key in (n, n.lower(), n.upper(), n.capitalize()):
            if key in payload and payload[key] not in (None, ""):
                try:
                    return float(payload[key])
                except (TypeError, ValueError):
                    pass
    return None


@app.api_route("/api/ingest", methods=["GET", "POST"])
async def ingest(request: Request):
    """Accept a reading from a push source.

    GET as well as POST because most sensors -- Shelly's webhooks among them
    -- can only build a URL with placeholders, not a JSON body. The token
    travels in the query string in that case, which is why it is a bearer
    secret scoped to one sensor and revocable on its own.
    """
    data = dict(request.query_params)
    if request.method == "POST":
        try:
            body = await request.json()
            if isinstance(body, dict):
                data = {**data, **body}
        except Exception:  # noqa: BLE001 - form or empty bodies are fine
            try:
                data = {**data, **dict(await request.form())}
            except Exception:  # noqa: BLE001
                pass

    token = (data.get("token") or "").strip()
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(401, "Token lipsă.")

    src = await store.source_by_token(accounts._hash(token))
    if not src:
        raise HTTPException(401, "Token invalid.")

    temp = _first_float(data, "temp", "temperature", "tC", "t")
    hum = _first_float(data, "hum", "humidity", "rh", "h")
    if temp is None and hum is None:
        raise HTTPException(400, "Nicio valoare de temperatură sau umiditate.")

    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # The source decides where it is; the query string may override it for
        # a multi-sensor gateway posting on behalf of several rooms.
        "location": (data.get("location") or src["location"]).strip(),
        "room": (data.get("room") or src["room"] or None),
        "device": src["name"],
        "zone": data.get("zone") or None,
        "temperature": temp,
        "humidity": hum,
        "setpoint": _first_float(data, "setpoint", "target"),
        "status": (data.get("status") or "").strip() or None,
        "battery": _first_float(data, "batt", "battery", "battery_percent"),
        # A push source speaks for itself, so arrival time is report time.
        "reported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    written = await store.insert([row])
    log.info("ingest from %s: %s %.1f°C", src["name"], row["location"],
             temp if temp is not None else float("nan"))
    return {"ok": True, "stored": written}


@app.get("/api/admin/sources", dependencies=[Depends(admin_only)])
async def admin_sources():
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return {"sources": await store.list_sources(), "ingest_url": f"{base}/api/ingest"}


@app.post("/api/admin/sources", dependencies=[Depends(admin_only)])
async def admin_add_source(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    location = (payload.get("location") or "").strip()
    if not name or not location:
        raise HTTPException(400, "name and location are required")
    token = accounts.new_device_token()
    sid = await store.add_source(name, location,
                                 (payload.get("room") or "").strip() or None,
                                 accounts._hash(token))
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return {
        "id": sid, "name": name, "location": location,
        # Shown once: only the hash is stored.
        "token": token,
        "example_url": f"{base}/api/ingest?token={token}&temp=21.4&hum=53",
    }


@app.post("/api/admin/sources/{source_id}/revoke", dependencies=[Depends(admin_only)])
async def admin_revoke_source(source_id: int, payload: dict = Body(default={})):
    if not await store.revoke_source(source_id, bool(payload.get("revoked", True))):
        raise HTTPException(404, "no such source")
    return {"id": source_id}
