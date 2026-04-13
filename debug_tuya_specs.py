import tinytuya
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_device_specs():
    api_key = os.environ.get("TUYA_API_KEY")
    api_secret = os.environ.get("TUYA_API_SECRET")
    uid = os.environ.get("TUYA_USER_ID")
    region = os.environ.get("TUYA_REGION", "eu")

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    dev_id = "bf205e09e2fba9d0e1wb8t"

    print(f"Fetching data for device: {dev_id}...")
    
    # Get functions
    try:
        funcs = c.getfunctions(dev_id)
        print("\n--- Device Functions ---")
        print(json.dumps(funcs, indent=2))
    except Exception as e:
        print(f"Error getting functions: {e}")
    
    # Get properties
    try:
        props = c.getproperties(dev_id)
        print("\n--- Device Properties ---")
        print(json.dumps(props, indent=2))
    except Exception as e:
        print(f"Error getting properties: {e}")
    
    # Latest status
    status = c.getstatus(dev_id)
    print("\n--- Current Status ---")
    print(json.dumps(status, indent=2))

if __name__ == "__main__":
    get_device_specs()
