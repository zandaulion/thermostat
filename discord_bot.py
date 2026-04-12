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
async def temp(ctx):
    """Fetch current temperature and log it."""
    await ctx.send("Fetching current temperature...")
    results, error = await fetch_and_log_data()
    
    if error:
        await ctx.send(f"❌ Error: {error}")
        return

    if not results:
        await ctx.send("❓ No data received.")
        return

    msg = "**Current Temperature:**\n"
    for row in results:
        msg += f"🏠 {row[1]} ({row[2]}): {row[3]}°C (Setpoint: {row[4]}°C) - Status: {row[5]}\n"
    
    await ctx.send(msg)

@bot.command()
async def plot(ctx, days: int = 7):
    """Generate and send the temperature plot for N days."""
    await ctx.send(f"Generating plot for the last {days} days...")
    # Ensure plot is generated in a thread if it's heavy, but for now direct call
    path, error = create_plot(days=days)
    
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
