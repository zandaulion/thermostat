import tinytuya
import os
import json
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

CACHE_FILE = "data/tuya_cache.json"

def get_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    os.makedirs("data", exist_ok=True)
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
    with open("devices.json", 'r') as f:
        config = json.load(f)
    
    tuya_devices = config.get("Tuya", [])
    if not tuya_devices:
        return [], None

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    cache = get_cache()
    
    results = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for dev_conf in tuya_devices:
        dev_id = dev_conf['id']
        location = dev_conf['location']
        room = dev_conf['room']
        name = dev_conf['name']
        
        status = c.getstatus(dev_id)
        
        temp = None
        hum = None
        setpoint = ""
        power_on = True
        mode = "Offline (Last Known)"
        
        if status.get('success') and 'result' in status:
            mode = "Online"
            # Extract data based on known codes
            for item in status['result']:
                code = item['code']
                val = item['value']
                
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
                    "timestamp": timestamp
                }
        else:
            # Fetch from cache if available
            cached = cache.get(dev_id)
            if cached:
                temp = cached.get("temp")
                hum = cached.get("hum")
                setpoint = cached.get("setpoint")
                power_on = cached.get("power_on", True)
        
        if temp is not None:
            # Infer heating status for thermostats (devices with a setpoint)
            status_val = mode
            if setpoint != "":
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
                status_val
            ])

    save_cache(cache)
    return results, None

if __name__ == "__main__":
    import asyncio
    res, err = asyncio.run(fetch_tuya_data_all())
    if err:
        print(f"Error: {err}")
    else:
        print(json.dumps(res, indent=2))
