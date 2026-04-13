import tinytuya
import os
import json
from dotenv import load_dotenv
import time

load_dotenv()

def get_logs():
    api_key = os.environ.get("TUYA_API_KEY")
    api_secret = os.environ.get("TUYA_API_SECRET")
    uid = os.environ.get("TUYA_USER_ID")
    region = os.environ.get("TUYA_REGION", "eu")

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    dev_id = "bf205e09e2fba9d0e1wb8t"

    print(f"Fetching logs for device: {dev_id}...")
    
    # Get logs for the last 24 hours
    end_time = int(time.time())
    start_time = end_time - (24 * 3600)
    
    logs = c.getdevicelog(dev_id, start=start_time, end=end_time)
    print("\n--- Device Logs (last 24h) ---")
    print(json.dumps(logs, indent=2))

if __name__ == "__main__":
    get_logs()
