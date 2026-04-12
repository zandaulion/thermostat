# Plan: Integrate Smart Life (Tuya) Sensors (Improved)

## Objective
Enable the logger and Discord bot to fetch and display data from Smart Life (Tuya) temperature and humidity sensors in addition to the Salus iT500, with support for multiple locations and rooms.

## Prerequisites (User to Provide)
- `TUYA_API_KEY` (Access ID)
- `TUYA_API_SECRET` (Access Secret)
- `TUYA_REGION` (e.g., `us`, `eu`)
- `TUYA_USER_ID` (Your Tuya account UID)

## Key Files & Context
- `devices.json`: **New** configuration file to map Device IDs to `Location` and `Room`.
- `tuya_temp.py`: New script for fetching Tuya device status using the **Tuya Cloud API**.
- `log_temp.py`: Updated for dual-system logging with new CSV schema.
- `plot_temp.py`: Updated to support filtering by **Location**.
- `discord_bot.py`: Updated commands to support a `location` parameter.
- `temp_log.csv`: Updated schema to include `Location`, `Room`, and `Humidity`.

## Implementation Steps

### 1. Configuration (`devices.json`)
Create a mapping file to handle multiple apartments:
```json
{
  "Salus": {
    "device_id": "YOUR_SALUS_ID",
    "location": "Main Home",
    "room": "Living Room"
  },
  "Tuya": [
    { "id": "tuya_id_1", "location": "Apartment A", "room": "Bedroom" },
    { "id": "tuya_id_2", "location": "Apartment B", "room": "Kitchen" }
  ]
}
```

### 2. Refined CSV Schema
Update `log_temp.py` to use the following header:
`Timestamp, Location, Room, Device Name, Zone, Temperature, Humidity, Setpoint, Status`

### 3. Handle Sleepy Sensors
In `tuya_temp.py`:
- Use the Tuya Cloud API to fetch the latest status.
- If a sensor is unreachable, return its **last known value** and set `Status` to `Offline (Last Known)`.

### 4. Discord Bot Commands
Update `discord_bot.py` to accept an optional `location` parameter:
- `!temp [location]`: If location is provided, only show data for that apartment.
- `!plot [days] [location]`: Generate a plot for a specific location.
- `!data [location]`: Send a filtered CSV or just the full one.

### 5. Plotting Improvements
Update `plot_temp.py`:
- Accept a `--location` argument.
- Filter the DataFrame by the requested location before plotting.
- Plot multiple rooms within the same location as separate lines on one graph.

## Verification & Testing
1.  **Dry Run**: Test the Tuya Cloud fetcher independently.
2.  **Log Check**: Verify that `temp_log.csv` is correctly populating the `Location`, `Room`, and `Humidity` columns.
3.  **Discord Check**: Test `!plot 7 Apartment A` to ensure it only shows relevant data.
