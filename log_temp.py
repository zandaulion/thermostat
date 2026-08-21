import asyncio
import aiohttp
import os
import csv
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
from pyit500.pyit500 import PyIt500
from pyit500.auth import Auth
from tuya_temp import fetch_tuya_data_all
from devices_config import load_devices

# Load credentials from .env file
load_dotenv()

LOG_FILE = os.environ.get("LOG_FILE", "temp_log.csv")
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", 600))

def get_devices_config():
    return load_devices()

async def fetch_all():
    """Collect readings from every configured source.

    Split out from fetch_and_log_data so callers that do not want a CSV --
    the web app polls into SQLite -- share exactly this code rather than a
    reimplementation of it that can drift.

    Returns (rows, error) where each row is in HEADER order. `error` is set
    whenever *any* source failed, even if another succeeded -- a partial
    collection that reports success is indistinguishable from a healthy one,
    and that is how a dead sensor goes unnoticed.
    """
    problems = []
    email = os.environ.get("SALUS_EMAIL")
    password = os.environ.get("SALUS_PASSWORD")
    config = get_devices_config()
    
    salus_conf = config.get("Salus", {})
    location = salus_conf.get("location", "Unknown")
    room = salus_conf.get("room", "Unknown")

    all_results = []
    
    # 1. Fetch Salus Data
    if email and password:
        async with aiohttp.ClientSession() as session:
            auth = Auth(session, email, password)
            try:
                await auth.refresh_token()
                pyit = PyIt500(auth)
                devices = await pyit.async_get_device_list()
                
                for device_item in devices:
                    try:
                        device = await pyit.async_get_device(device_item.device_id)
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Log CH1
                        data_ch1 = [
                            timestamp, 
                            location,
                            room,
                            device_item.name, 
                            "CH1", 
                            device.ch1.current_room_temp, 
                            "", # No humidity for Salus
                            device.ch1.current_setpoint, 
                            "On" if device.ch1.relay_status == 1 else "Off",
                            "",  # mains powered
                            ""   # Salus exposes no per-device report clock
                        ]
                        all_results.append(data_ch1)
                        
                        # Log CH2 if present
                        if device.system_type.value == 1:
                            data_ch2 = [
                                timestamp, 
                                location,
                                room,
                                device_item.name, 
                                "CH2", 
                                device.ch2.current_room_temp, 
                                "",
                                device.ch2.current_setpoint, 
                                "On" if device.ch2.relay_status == 1 else "Off",
                                "",
                                ""
                            ]
                            all_results.append(data_ch2)
                    except Exception as e:
                        print(f"[{datetime.now()}] Error fetching Salus device {device_item.name}: {e}")
            except Exception as e:
                print(f"[{datetime.now()}] Salus authentication/fetch failed: {e}")

    # 2. Fetch Tuya Data
    try:
        tuya_results, tuya_err = await fetch_tuya_data_all()
        if tuya_err:
            problems.append(f"tuya: {tuya_err}")
            print(f"[{datetime.now()}] Tuya fetch failed: {tuya_err}")
        if tuya_results:
            all_results.extend(tuya_results)
    except Exception as e:
        problems.append(f"tuya: {e}")
        print(f"[{datetime.now()}] Error in Tuya fetch: {e}")

    if not all_results:
        return None, "; ".join(problems) or "No data collected from any source."
    return all_results, ("; ".join(problems) if problems else None)


async def fetch_and_log_data():
    all_results, err = await fetch_all()
    if err:
        return None, err

    # 3. Write all results to CSV
    file_exists = os.path.isfile(LOG_FILE)
    # Battery is appended, never inserted: the CSV is read by column name, so
    # adding at the end keeps older files and the plotter working.
    HEADER = ["Timestamp", "Location", "Room", "Device Name", "Zone",
              "Temperature", "Humidity", "Setpoint", "Status", "Battery",
              "Reported At"]
    
    try:
        with open(LOG_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(HEADER)
            for row in all_results:
                writer.writerow(row)
        return all_results, None
    except Exception as e:
        return None, f"Error writing to {LOG_FILE}: {e}"

async def fetch_and_log():
    results, error = await fetch_and_log_data()
    if error:
        print(f"[{datetime.now()}] {error}")
    elif results:
        print(f"[{datetime.now()}] Logged successfully to {LOG_FILE}")

if __name__ == "__main__":
    if "--loop" in sys.argv:
        print(f"Starting temperature logger in loop mode (every {INTERVAL_SECONDS // 60} minutes)...")
        async def loop_main():
            while True:
                await fetch_and_log()
                await asyncio.sleep(INTERVAL_SECONDS)
        try:
            asyncio.run(loop_main())
        except KeyboardInterrupt:
            print("\nLogger stopped.")
    else:
        asyncio.run(fetch_and_log())
