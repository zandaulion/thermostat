import tinytuya
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_raw_dps():
    api_key = os.environ.get("TUYA_API_KEY")
    api_secret = os.environ.get("TUYA_API_SECRET")
    uid = os.environ.get("TUYA_USER_ID")
    region = os.environ.get("TUYA_REGION", "eu")

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    dev_id = "bf205e09e2fba9d0e1wb8t"

    print(f"Fetching raw DPS for device: {dev_id}...")
    
    try:
        # In some versions of tinytuya, getdps might take different arguments
        dps = c.getdps(dev_id)
        print("\n--- Raw DPS ---")
        print(json.dumps(dps, indent=2))
    except Exception as e:
        print(f"Error getting DPS: {e}")

if __name__ == "__main__":
    get_raw_dps()
