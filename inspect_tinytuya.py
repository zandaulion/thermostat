import tinytuya
import os
from dotenv import load_dotenv

load_dotenv()

def inspect_cloud():
    api_key = os.environ.get("TUYA_API_KEY")
    api_secret = os.environ.get("TUYA_API_SECRET")
    uid = os.environ.get("TUYA_USER_ID")
    region = os.environ.get("TUYA_REGION", "eu")

    c = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret, uid=uid)
    print("Available methods in tinytuya.Cloud:")
    for method in sorted(dir(c)):
        if not method.startswith("_"):
            print(f" - {method}")

if __name__ == "__main__":
    inspect_cloud()
