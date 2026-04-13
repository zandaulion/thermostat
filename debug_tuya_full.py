import tinytuya
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_full_state():
    api_key = os.environ.get("TUYA_API_KEY")
    api_secret = os.environ.get("TUYA_API_SECRET")
    uid = os.environ.get("TUYA_USER_ID")
    region = os.environ.get("TUYA_REGION", "eu")

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    dev_id = "bf205e09e2fba9d0e1wb8t"

    print(f"Requesting full state for device: {dev_id} via raw cloudrequest...")
    
    # Try the specific status endpoint
    res = c.cloudrequest(f"/v1.0/devices/{dev_id}/status")
    print("\n--- Full Status Response ---")
    print(json.dumps(res, indent=2))

    # Try the device information endpoint
    res2 = c.cloudrequest(f"/v1.0/devices/{dev_id}")
    print("\n--- Device Info Response ---")
    print(json.dumps(res2, indent=2))

if __name__ == "__main__":
    get_full_state()
