import asyncio
import aiohttp
import os
import sys
from dotenv import load_dotenv
from pyit500.pyit500 import PyIt500
from pyit500.auth import Auth

# Load credentials from .env file
load_dotenv()

async def main():
    email = os.environ.get("SALUS_EMAIL")
    password = os.environ.get("SALUS_PASSWORD")

    if not email or not password:
        print("Error: Please set SALUS_EMAIL and SALUS_PASSWORD environment variables.")
        print("Example: SALUS_EMAIL=user@example.com SALUS_PASSWORD=secret venv/bin/python read_temp.py")
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        auth = Auth(session, email, password)
        try:
            print("Authenticating...")
            await auth.refresh_token()
        except Exception as e:
            print(f"Authentication failed: {e}")
            sys.exit(1)
        
        pyit = PyIt500(auth)
        try:
            print("Fetching devices...")
            devices = await pyit.async_get_device_list()
        except Exception as e:
            print(f"Failed to fetch device list: {e}")
            sys.exit(1)
        
        if not devices:
            print("No devices found on this account.")
            return
            
        for device_item in devices:
            print(f"\nDevice: {device_item.name} (ID: {device_item.device_id})")
            try:
                device = await pyit.async_get_device(device_item.device_id)
                
                # CH1 is always present for IT500
                print(f"  CH1 Temperature: {device.ch1.current_room_temp}°C")
                print(f"  CH1 Setpoint:    {device.ch1.current_setpoint}°C")
                print(f"  CH1 Status:      {'On' if device.ch1.relay_status == 1 else 'Off'}")
                
                # Check SystemType for CH2
                # 0 = CH1, 1 = CH1+CH2, 2 = CH1 + Hot Water
                if device.system_type.value == 1:
                    print(f"  CH2 Temperature: {device.ch2.current_room_temp}°C")
                    print(f"  CH2 Setpoint:    {device.ch2.current_setpoint}°C")
                    print(f"  CH2 Status:      {'On' if device.ch2.relay_status == 1 else 'Off'}")
                elif device.system_type.value == 2:
                    print(f"  Hot Water Status: {'On' if device.hw.relay_status == 1 else 'Off'}")
                    
            except Exception as e:
                print(f"  Failed to fetch device details: {e}")

if __name__ == "__main__":
    asyncio.run(main())
