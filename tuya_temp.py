import tinytuya
import os
import json
from dotenv import load_dotenv
from devices_config import load_devices
from datetime import datetime, timezone

load_dotenv()

# Overridable so a container can point it at a writable volume; the default
# keeps the old behaviour for the docker-compose setup.
CACHE_DIR = os.environ.get("TUYA_CACHE_DIR", "data")
CACHE_FILE = os.path.join(CACHE_DIR, "tuya_cache.json")

def get_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

async def fetch_tuya_data_all():
    api_key = os.environ.get("TUYA_API_KEY")
    api_secret = os.environ.get("TUYA_API_SECRET")
    uid = os.environ.get("TUYA_USER_ID")
    region = os.environ.get("TUYA_REGION", "eu")

    if not all([api_key, api_secret, uid]):
        return [], "Tuya credentials not fully set."

    # Load device config
    config = load_devices()
    
    tuya_devices = config.get("Tuya", [])
    if not tuya_devices:
        return [], None

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    cache = get_cache()

    def device_liveness(dev_id):
        """-> (online, reported_at_iso).

        getstatus() succeeds for a device that has been unplugged for days --
        Tuya's cloud keeps serving the last datapoints it ever received, with
        no marker that they are historical. The device record is the only
        place that carries the truth, so ask it rather than inferring
        liveness from "the API answered".
        """
        try:
            r = c.cloudrequest("/v1.0/devices/%s" % dev_id)
        except Exception:
            return None, None
        if not isinstance(r, dict) or not r.get("success"):
            return None, None
        res = r.get("result") or {}
        online = res.get("online")
        seen = res.get("update_time")
        iso = None
        if isinstance(seen, (int, float)) and seen > 0:
            iso = datetime.fromtimestamp(seen, timezone.utc).isoformat(timespec="seconds")
        return (bool(online) if online is not None else None), iso
    
    results = []
    # A device we cannot read must be reported, not silently omitted. An
    # expired cloud subscription produces exactly this: authentication
    # succeeds, every query is refused, and the loop yields nothing while
    # claiming success.
    failures = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for dev_conf in tuya_devices:
        dev_id = dev_conf['id']
        location = dev_conf['location']
        room = dev_conf['room']
        name = dev_conf['name']
        
        status = c.getstatus(dev_id)
        online, reported_at = device_liveness(dev_id)

        temp = None
        hum = None
        battery = None
        setpoint = ""
        power_on = True
        mode = "Offline (Last Known)"
        
        if not status.get('success'):
            failures.append(
                f"{location}: {status.get('Payload') or status.get('msg') or 'no data'}")

        # `online is None` means we could not reach the device record; fall
        # back to the old behaviour rather than declaring a live sensor dead.
        #
        # An offline device is NOT a collection failure. We read the cloud
        # successfully; the cloud told us the sensor is unreachable. It travels
        # in the row's Status, raises its own "senzor deconectat" alert, and is
        # visible in /api/health. Putting it in `failures` would pin the
        # operational health flag permanently unhealthy and, since that flag is
        # edge-triggered, silence the next genuine outage.
        if online is False:
            print(f"[{location}] device offline since {reported_at or 'unknown'}")

        if status.get('success') and 'result' in status:
            if online is not False:
                mode = "Online"
            # Extract data based on known codes
            for item in status['result']:
                code = item['code']
                val = item['value']

                if code in ('battery_percentage', 'battery_percent'):
                    battery = val
                elif code == 'battery_state':
                    # Coarse devices report a word; map it to something a
                    # threshold can be applied to.
                    battery = {'low': 10, 'middle': 50, 'high': 90}.get(val)
                
                if code in ['va_temperature', 'temp_current']:
                    temp = val / 10.0
                elif code == 'va_humidity':
                    hum = val
                elif code == 'temp_set':
                    setpoint = val / 10.0
                elif code == 'switch':
                    power_on = val
            
            # Update cache if we got new data
            if temp is not None:
                cache[dev_id] = {
                    "temp": temp,
                    "hum": hum,
                    "setpoint": setpoint,
                    "power_on": power_on,
                    "battery": battery,
                    # The sensor's own clock where Tuya gives us one. Storing
                    # the run clock here made every cached value look fresh.
                    "timestamp": reported_at or timestamp
                }
        else:
            # Fetch from cache if available
            cached = cache.get(dev_id)
            if cached:
                temp = cached.get("temp")
                hum = cached.get("hum")
                setpoint = cached.get("setpoint")
                power_on = cached.get("power_on", True)
                battery = cached.get("battery")
                reported_at = reported_at or cached.get("timestamp")
        
        if temp is not None:
            # Infer heating status for thermostats (devices with a setpoint)
            status_val = mode
            # An offline thermostat must keep saying so: inferring On/Off from
            # its last-known temperature would paint a dead device as healthy.
            if setpoint != "" and mode == "Online":
                if not power_on:
                    status_val = "Off" # Or "Power Off"
                else:
                    try:
                        # Added a small 0.2C hysteresis to avoid flickering
                        if float(temp) < float(setpoint):
                            status_val = "On"
                        else:
                            status_val = "Off"
                    except (ValueError, TypeError):
                        pass

            results.append([
                timestamp,
                location,
                room,
                name,
                "Main", # Zone for Tuya
                temp,
                hum if hum is not None else "",
                setpoint,
                status_val,
                battery if battery is not None else "",
                reported_at or ""
            ])

    save_cache(cache)
    return results, ('; '.join(failures) if failures else None)

if __name__ == "__main__":
    import asyncio
    res, err = asyncio.run(fetch_tuya_data_all())
    if err:
        print(f"Error: {err}")
    else:
        print(json.dumps(res, indent=2))
