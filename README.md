# Salus iT500 Thermostat Logger & Discord Bot

A containerized Python application that logs temperature data from a Salus iT500 thermostat, generates visual plots, and provides a Discord bot interface for remote monitoring.

## 🚀 Features
- **Automatic Logging**: Records temperature, setpoint, and relay status every 10 minutes to a CSV file.
- **Discord Bot**: 
  - `!temp`: Get current readings instantly.
  - `!plot [days]`: Generate and receive a temperature graph (defaults to last 7 days).
  - `!data`: Download the raw CSV log file.
- **Visual Plots**: Generates a professional graph with `matplotlib`, including a red shaded overlay when the heating is active.
- **Dockerized**: Easy to deploy on any system (Raspberry Pi, Server, etc.) with `docker-compose`.
- **Local Time Support**: Logs and plots are automatically synced to your local timezone.

## 🛠️ Setup & Installation

### 1. Prerequisites
- A Salus iT500 Thermostat account.
- [Optional] A Discord Bot Token (follow [this guide](https://discordpy.readthedocs.io/en/stable/discord.html) to create one).
- Docker and Docker Compose installed on your system.

### 2. Configuration
Create a `.env` file in the root directory:
```env
SALUS_EMAIL="your_email@example.com"
SALUS_PASSWORD="your_password"
DISCORD_TOKEN="your_discord_bot_token"
TZ="Europe/Bucharest" # Set your local timezone
```

### 3. Start the Application
Build and start the containers using Docker Compose:
```bash
docker compose up -d --build
```

## 🤖 Discord Bot Commands
Invite the bot to your server and use the following commands:
- `!temp`: Fetches the current temperature and logs it.
- `!plot <days>`: Sends a graph for the last N days (e.g., `!plot 1` for the last 24 hours).
- `!data`: Sends the `temp_log.csv` file as an attachment.
- `!ping`: Health check.

## 📊 Manual Commands (via Docker)
If you prefer to run commands manually through the container:
- **Force a log entry**: `docker exec it500-logger python log_temp.py`
- **Generate a 7-day plot**: `docker exec it500-logger python plot_temp.py`
- **Generate a custom plot**: `docker exec it500-logger python plot_temp.py 14` (for 14 days)

## 📁 Project Structure
- `log_temp.py`: Core logic for fetching and logging data.
- `plot_temp.py`: Logic for generating the Matplotlib graph.
- `discord_bot.py`: The Discord bot interface.
- `data/`: (Volume) Stores your `temp_log.csv` and `temp_plot.png`.
- `Dockerfile` & `docker-compose.yml`: Container configuration.

## 🛡️ Security
Your credentials in `.env` and the data in `data/` are automatically ignored by Git (via `.gitignore`) to prevent accidental exposure of your account details.

## 📜 License
This project is for personal use and is not affiliated with Salus Controls.
