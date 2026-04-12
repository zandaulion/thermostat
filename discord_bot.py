import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from log_temp import fetch_and_log_data, LOG_FILE
from plot_temp import create_plot
import asyncio

# Load credentials from .env file
load_dotenv()

TOKEN = os.environ.get("DISCORD_TOKEN")

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
async def plot(ctx, days: int = 7, *, location: str = None):
    """Generate and send the temperature plot for N days. Optional location filter."""
    await ctx.send(f"Generating plot for the last {days} days...")
    
    path, error = create_plot(days=days, location=location)
    
    if error:
        await ctx.send(f"❌ Error: {error}")
        return

    if path and os.path.exists(path):
        await ctx.send(file=discord.File(path))
    else:
        await ctx.send("❌ Error: Plot file not found.")

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
