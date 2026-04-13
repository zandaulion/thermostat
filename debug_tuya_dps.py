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
    
    # getstatus() usually has the codes, let's see if we can find raw DP IDs
    status = c.getstatus(dev_id)
    print("\n--- Current Status (Result) ---")
    print(json.dumps(status, indent=2))
    
    # Some devices expose more info in the 'properties' or through a different request
    # Let's try to get the mapping
    mapping = c.getmapping(dev_id)
    print("\n--- Mapping ---")
    print(json.dumps(mapping, indent=2))

if __name__ == "__main__":
    get_raw_dps()
