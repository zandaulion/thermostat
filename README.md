# Thermostat — logger, web app, and Discord bot

Logs temperature from a Salus iT500 thermostat and Tuya sensors across
several properties, and surfaces it three ways: a **progressive web app**
with live readings, interactive charts and push alerts; a Discord bot; and a
plain CSV.

## 🚀 Features
- **Web app (PWA)**: current readings per location, interactive charts, and
  push notifications. See [Web app](#-web-app) below.
- **Automatic Logging**: Records temperature, setpoint, and relay status every 10 minutes to a CSV file.
- **Discord Bot**: 
  - `!temp`: Get current readings instantly.
  - `!plot [days]`: Generate and receive a temperature graph (defaults to last 7 days).
  - `!data`: Download the raw CSV log file.
- **Visual Plots**: Generates a professional graph with `matplotlib`, including a red shaded overlay when the heating is active.
- **Dockerized**: Easy to deploy on any system (Raspberry Pi, Server, etc.) with `docker-compose`.
- **Local Time Support**: Logs and plots are automatically synced to your local timezone.

## 🛠️ Setup & Installation

### 1. Prerequisites
- A Salus iT500 Thermostat account.
- [Optional] A Discord Bot Token (follow [this guide](https://discordpy.readthedocs.io/en/stable/discord.html) to create one).
- Docker and Docker Compose installed on your system.

### 2. Configuration
Two files, neither of them tracked by Git.

**Credentials** — a `.env` file in the root directory:
```env
SALUS_EMAIL="your_email@example.com"
SALUS_PASSWORD="your_password"
DISCORD_TOKEN="your_discord_bot_token"
TZ="Europe/Bucharest" # Set your local timezone
```

**Device inventory** — `devices.json`, which maps cloud device ids to the
rooms they sit in:
```bash
cp devices.example.json devices.json   # then fill it in
```
It is deployment data rather than source: it names your rooms and carries
your device ids, so the repository ships only the example. The fetchers look
for it in this order, first hit wins:

| Order | Location | Used by |
| ----- | -------- | ------- |
| 1 | `$DEVICES_FILE` | explicit override, tests |
| 2 | `$DATA_DIR/devices.json` | the deployed container (`/data/devices.json`) |
| 3 | `./devices.json` | a checkout run from the working tree |

If none of them exists the fetchers raise rather than returning an empty
inventory — see [Failure modes](#-failure-modes-worth-knowing) for why.

### 3. Start the Application
Build and start the containers using Docker Compose:
```bash
docker compose up -d --build
```

## 🤖 Discord Bot Commands
Invite the bot to your server and use the following commands:
- `!temp`: Fetches the current temperature and logs it.
- `!plot <days> [location] [smooth]`: Sends a graph for the last N days. Use `all` as the location to see all apartments on one graph, and add `smooth` to apply Gaussian smoothing (e.g., `!plot 7 snagov smooth`).
- `!data`: Sends the `temp_log.csv` file as an attachment.
- `!ping`: Health check.

## 📱 Web app

A self-contained PWA — install it to a phone's home screen and it behaves
like an app, including notifications.

It exists because a bot can only answer when asked. The chart is the smaller
half of the value; the useful half is being told **without asking**:

| Alert | Why it earns a notification |
|---|---|
| below `ALERT_COLD_C` (8°C) | an unheated property in winter is a burst-pipe risk, and nobody is there to notice |
| heating on for `ALERT_STUCK_HOURS` (6h) | a stuck relay or a door left open, costing money quietly |
| silent for `ALERT_SILENT_MINUTES` (90) | a sensor that stops reporting looks exactly like "everything is fine" — the dangerous failure |
| battery below `ALERT_BATTERY_PCT` (15%) | a flat battery *becomes* a silent sensor, at a property nobody is visiting |
| `TUYA_TRIAL_EXPIRES` approaching | when the cloud subscription lapses, several sensors stop at once; warning beforehand stops that looking like simultaneous hardware failure |

A tile also carries a battery badge below the threshold, so the reminder is
present every time you open the app rather than only when the alert fired.

Alerts are **edge-triggered**: a condition that persists produces one message,
not one per poll, and recovery is reported once. A channel that repeats itself
gets muted, and a muted channel is worth nothing.

Access is per-device by invite — no shared password, and notifications can be
targeted. `./admin.sh invite "Ana"` mints one, or use
[pwa-invite-console](https://github.com/zandaulion/pwa-invite-console), the graphical
console that fronts every app behind this invite mechanism and therefore lives
in none of their repos.

Charts are drawn client-side as plain SVG, one path per series. The viewBox
is measured from the element rather than fixed, and the SVG is never
stretched — `preserveAspectRatio="none"` against a fixed-width viewBox
squashes the axis text along with the drawing, which on a 360px phone meant
labels compressed to half width. Tick count and height adapt to the
available width instead. That drops
`pandas`, `matplotlib` and `scipy` from the web image entirely — they remain
only for the Discord bot's server-rendered PNGs.

### Running it

```bash
podman build -t thermo:latest -f deploy/Containerfile .

install -d -m 700 ~/.config/thermo
cp deploy/thermo.env.example ~/.config/thermo/thermo.env   # then fill it in
chmod 600 ~/.config/thermo/thermo.env

cp deploy/quadlet/thermo.container ~/.config/containers/systemd/
systemctl --user daemon-reload && systemctl --user start thermo.service
./deploy/deploy.sh            # publish the PWA to /var/www/thermo
```

The container reads its inventory from the volume, so put it there once —
`podman unshare` because the volume is owned by the container's user, not
yours:

```bash
VOL=$(podman volume inspect thermo-data --format '{{.Mountpoint}}')
podman unshare cp devices.json "$VOL/devices.json"
podman unshare chown 10003:10003 "$VOL/devices.json"
podman unshare chmod 600 "$VOL/devices.json"
```

It listens on `127.0.0.1:8093`; put a reverse proxy in front to reach it from
elsewhere. Everything mutable lives in the named volume `thermo-data`: the
readings database, the VAPID key, the Tuya token cache, and `devices.json`.
**The VAPID key must survive rebuilds** — regenerating it silently
invalidates every push subscription already granted.

### Which location opens first

`DEFAULT_LOCATION` decides, because which property matters most is a
property of the household rather than of the code. After anyone taps a
different one it is remembered in their browser, so each viewer settles on
their own without affecting the others.

### Pushing readings in

Polling a vendor's cloud makes the app hostage to that vendor's pricing —
which is how three sensors went dark when Tuya moved its API behind an
enterprise contract. `POST` (or `GET`) `/api/ingest` lets anything send a
reading instead:

```bash
./admin.sh source "Shelly H&T salon" "Basarabia" "Living Room"
# prints a token and a ready-made URL, once
```

```
/api/ingest?token=<secret>&temp=21.4&hum=53
```

`GET` is supported because most sensors can only build a URL with
placeholders, not a JSON body — a Shelly webhook, for instance. The token is
a bearer secret scoped to one sensor and revocable on its own. Field names
are matched liberally (`temp`/`temperature`/`tC`, `hum`/`humidity`/`rh`), so
a new device rarely needs an adapter.

Pushed readings are indistinguishable from polled ones afterwards: same
table, same charts, same alerts.

### Importing existing history

```bash
podman cp temp_log.csv thermo:/tmp/ && \
podman exec thermo python /tmp/import-csv.py /tmp/temp_log.csv
```

CSV timestamps are naive local time and the database stores UTC, so the
importer converts explicitly — getting that wrong shifts every historical
point by two or three hours depending on the season, which looks entirely
plausible on a chart.

## 📊 Manual Commands (via Docker)
If you prefer to run commands manually through the container:
- **Force a log entry**: `docker exec it500-logger python log_temp.py`
- **Generate a 7-day plot**: `docker exec it500-logger python plot_temp.py`
- **Generate a custom plot**: `docker exec it500-logger python plot_temp.py 14` (for 14 days)

## 📁 Project Structure
- `log_temp.py`: Core logic for fetching and logging data. `fetch_all()`
  collects without writing, so the web app and the CSV logger share one code
  path rather than two that can drift.
- `read_temp.py` / `tuya_temp.py`: the Salus and Tuya cloud clients.
- `devices_config.py`: resolves where `devices.json` lives, so both fetchers
  agree on one answer.
- `devices.example.json`: template for the untracked `devices.json`.
- `plot_temp.py`: Logic for generating the Matplotlib graph (Discord only).
- `discord_bot.py`: The Discord bot interface.
- `thermo/`: the web app — storage, poller, alert rules, API.
- `web/`: the PWA itself (no build step, no framework).
- `deploy/`: Containerfile, quadlet unit, CSV importer.
- `data/`: (Volume) Stores your `temp_log.csv` and `temp_plot.png`.
- `Dockerfile` & `docker-compose.yml`: Container configuration.

## ⚠️ Failure modes worth knowing

A monitoring app that hides its own blindness is worse than none. Four ways
this one used to do exactly that, all now fixed:

- **A source that fails while another succeeds.** `fetch_all()` caught the
  Tuya error, printed it, and returned success because Salus had worked — so
  a poll that lost three quarters of its data reported none.
- **A source that returns nothing, quietly.** When a Tuya IoT Core
  subscription expires, authentication still succeeds and every device query
  is refused; the loop yielded zero rows and reported no error. Unreadable
  devices are now named in the error.
- **Stale values that look live.** The dashboard shows the last known reading
  per location, so an expired subscription leaves four confident numbers on
  screen. Sensors that stop reporting are now marked in the UI and raise an
  alert — see below for how that is decided.
- **An empty device inventory.** A missing `devices.json` used to yield an
  empty config, which made every fetcher return "no devices, no error" —
  indistinguishable from a healthy poll of an empty house. It now raises, and
  the poller surfaces the exception through `/api/health`.

### How a dead sensor is detected

Not by age alone, because that gets it wrong in both directions.

A device cloud will happily serve a dead device's last readings forever. Tuya
answered for five days after one sensor went offline, re-dating the same
values on every poll, so the reading always looked minutes old. Liveness
therefore comes from the device record (`online`, `update_time`), not from the
fact that a status query succeeded.

The opposite mistake is just as easy: a battery temperature/humidity sensor
legitimately goes hours between datapoints, so timing it out on
`ALERT_SILENT_MINUTES` would cry wolf on a perfectly healthy sensor. So:

- the cloud reports the device **offline** → alert immediately;
- the cloud vouches for it being **online** → trust that, whatever the age;
- **no liveness information** (every push source) → fall back to the
  `ALERT_SILENT_MINUTES` timer, where arrival time really is report time.

Rows carry two clocks: `ts` is when we wrote the row, and `reported_at` is
Tuya's `update_time` for the device.

**`reported_at` is not a reliable "last spoke" clock**, and the displayed age no
longer comes from it while a device is reachable. Tuya refreshes `update_time`
on datapoint reports for some devices and not others: the Home thermostat
returns a changing `temp_current` on every poll while its `update_time` sits
days in the past, which showed a healthy sensor as "acum 6 zile". So:

* **device reachable** → age is our own poll time. We asked, and this is what
  came back; that is the honest claim.
* **device offline** → age is `reported_at`. Nothing was confirmed, and what
  matters is how long ago it was last heard from.

Push sources need no special case. They write no row when they go quiet, so
their newest `ts` stops advancing and its age grows by itself.

Tuya's free **IoT Core trial lasts one month** and cannot be re-subscribed on
the same account; past it, their pricing is enterprise-scale. When it lapses
those sensors stop, and the `silent` alert is what tells you. The durable
answer is `/api/ingest` above — a sensor that pushes to your own endpoint has
no vendor to lose.

One SQLite detail worth remembering: **NULLs are distinct in a UNIQUE
index**, so the deduplicating index on readings has to `COALESCE` room and
device. Without that it silently stops deduplicating for any source that
leaves them unset — which is most push sources.

## 🛡️ Security
`.gitignore` keeps three things out of the repository: your credentials
(`.env`), the collected data (`data/`), and your device inventory
(`devices.json`). The inventory matters as much as the other two — it names
your rooms and lists your cloud device ids. The ids are not usable on their
own, since the cloud APIs also want the key and secret from `.env`, but they
describe your setup and there is no reason to publish them.

## 📜 License
This project is for personal use and is not affiliated with Salus Controls.
