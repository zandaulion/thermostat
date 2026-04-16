import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from log_temp import fetch_and_log_data, LOG_FILE
from plot_temp import create_plot
import asyncio
from ewelink import EWeLinkClient

# Load credentials from .env file
load_dotenv()

TOKEN = os.environ.get("DISCORD_TOKEN")
EWELINK_EMAIL = os.environ.get("EWELINK_EMAIL")
EWELINK_PASSWORD = os.environ.get("EWELINK_PASSWORD")
EWELINK_REGION = os.environ.get("EWELINK_REGION", "eu")

if not TOKEN:
    print("Error: DISCORD_TOKEN not set in .env.")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')

@bot.command()
async def temp(ctx, location: str = None):
    """Fetch current temperature and log it. Optional location filter."""
    await ctx.send("Fetching current temperature...")
    results, error = await fetch_and_log_data()
    
    if error:
        await ctx.send(f"❌ Error: {error}")
        return

    if not results:
        await ctx.send("❓ No data received.")
        return

    msg = "**Current Temperature:**\n"
    found = False
    for row in results:
        # row: [timestamp, location, room, device_name, zone, temp, humidity, setpoint, status]
        if location and location.lower() not in row[1].lower():
            continue
            
        found = True
        line = f"🏠 **{row[1]}** - {row[2]} ({row[4]}): {row[5]}°C"
        if row[6]: # Humidity
            line += f" (💧 {row[6]}%)"
        if row[7]: # Setpoint
            line += f" [Setpoint: {row[7]}°C]"
        line += f" - Status: {row[8]}\n"
        msg += line
    
    if not found and location:
        await ctx.send(f"❓ No data found for location: {location}")
    else:
        await ctx.send(msg)

@bot.command()
async def plot(ctx, *args):
    """Generate and send the temperature plot. Usage: !plot [days] [location] [smooth]"""
    days = 7
    location = None
    smooth = False
    
    # Process args
    args_list = list(args)
    if "smooth" in [a.lower() for a in args_list]:
        smooth = True
        args_list = [a for a in args_list if a.lower() != "smooth"]

    for arg in args_list:
        try:
            days = int(arg)
        except ValueError:
            location = arg

    status_msg = f"over the last {days} days"
    if smooth:
        status_msg += " (smoothed)"
    
    await ctx.send(f"Generating plot for {location if location else 'default location'} {status_msg}...")
    
    path, error = create_plot(days=days, location=location, smooth=smooth)
    
    if error:
        await ctx.send(f"❌ Error: {error}")
        return

    if path and os.path.exists(path):
        await ctx.send(file=discord.File(path))
    else:
        await ctx.send("❌ Error: Plot file not found.")

@bot.command()
async def switch(ctx, action: str = None, *, device_name: str = "bucatarie"):
    """Control eWeLink switches. Usage: !switch [on|off|status] [name]"""
    if not EWELINK_EMAIL or not EWELINK_PASSWORD:
        await ctx.send("❌ Error: eWeLink credentials not configured.")
        return

    if not action or action.lower() not in ["on", "off", "status"]:
        await ctx.send("❓ Usage: `!switch <on|off|status> [device_name]`")
        return

    action = action.lower()
    # Support both original name and ewelink name
    target_names = [device_name.lower()]
    if device_name.lower() == "bucatarie":
        target_names.append("kitchen light")

    await ctx.send(f"⏳ Processing `{action}` for `{device_name}`...")

    try:
        async with EWeLinkClient() as client:
            await client.login(username=EWELINK_EMAIL, password=EWELINK_PASSWORD, region=EWELINK_REGION, country_code="+40")
            devices = await client.get_devices()
            
            target_dev = None
            for dev in devices:
                if dev.get('name', '').lower() in target_names:
                    target_dev = dev
                    break
            
            if not target_dev:
                await ctx.send(f"❌ Error: Device `{device_name}` not found.")
                return

            device_id = target_dev['deviceid']
            name = target_dev['name']

            if action == "status":
                current_status = target_dev.get('params', {}).get('switch', 'unknown')
                await ctx.send(f"💡 `{name}` is currently **{current_status.upper()}**.")
            else:
                await client.set_switch(device_id, action)
                await ctx.send(f"✅ Successfully turned `{name}` **{action.upper()}**.")

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command()
async def data(ctx):
    """Send the temp_log.csv file."""
    if os.path.exists(LOG_FILE):
        await ctx.send("Here is the latest log data:", file=discord.File(LOG_FILE))
    else:
        await ctx.send("❌ Error: Log file not found.")

@bot.command()
async def ping(ctx):
    """Simple health check."""
    await ctx.send("Pong! 🏓")

if __name__ == "__main__":
    bot.run(TOKEN)
