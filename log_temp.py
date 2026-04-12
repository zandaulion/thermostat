import asyncio
import aiohttp
import os
import csv
import sys
from datetime import datetime
from dotenv import load_dotenv
from pyit500.pyit500 import PyIt500
from pyit500.auth import Auth

# Load credentials from .env file
load_dotenv()

LOG_FILE = os.environ.get("LOG_FILE", "temp_log.csv")
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", 600))

async def fetch_and_log_data():
    email = os.environ.get("SALUS_EMAIL")
    password = os.environ.get("SALUS_PASSWORD")

    if not email or not password:
        return None, "Error: SALUS_EMAIL and SALUS_PASSWORD not set in .env."

    results = []
    async with aiohttp.ClientSession() as session:
        auth = Auth(session, email, password)
        try:
            await auth.refresh_token()
        except Exception as e:
            return None, f"Authentication failed: {e}"
            
        pyit = PyIt500(auth)
        try:
            devices = await pyit.async_get_device_list()
        except Exception as e:
            return None, f"Failed to fetch device list: {e}"
            
        if not devices:
            return None, "No devices found."

        # Ensure CSV header exists
        file_exists = os.path.isfile(LOG_FILE)
        
        try:
            with open(LOG_FILE, mode='a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "Device Name", "Zone", "Temperature", "Setpoint", "Status"])

                for device_item in devices:
                    try:
                        device = await pyit.async_get_device(device_item.device_id)
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Log CH1
                        data_ch1 = [
                            timestamp, 
                            device_item.name, 
                            "CH1", 
                            device.ch1.current_room_temp, 
                            device.ch1.current_setpoint, 
                            "On" if device.ch1.relay_status == 1 else "Off"
                        ]
                        writer.writerow(data_ch1)
                        results.append(data_ch1)
                        
                        # Log CH2 if present
                        if device.system_type.value == 1:
                            data_ch2 = [
                                timestamp, 
                                device_item.name, 
                                "CH2", 
                                device.ch2.current_room_temp, 
                                device.ch2.current_setpoint, 
                                "On" if device.ch2.relay_status == 1 else "Off"
                            ]
                            writer.writerow(data_ch2)
                            results.append(data_ch2)
                    except Exception as e:
                        print(f"[{datetime.now()}] Error fetching details for {device_item.name}: {e}")
            
            return results, None
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
