# Plan: Add Discord Bot for Thermostat Control

## Objective
Create a Discord bot that allows the user to query the thermostat's temperature, generate plots, and download the log data via commands.

## Key Files & Context
- `discord_bot.py`: New script that implements the Discord bot and handles user commands.
- `log_temp.py`: Existing script, will be refactored to make its core logic importable.
- `plot_temp.py`: Existing script, will be refactored to make its core logic importable.
- `docker-compose.yml`: Update to include the Discord bot service.
- `requirements.txt`: Update to include `discord.py`.
- `.env`: Update to include the `DISCORD_TOKEN`.

## Implementation Steps
1.  **Update `requirements.txt`**: Add `discord.py`.
2.  **Refactor `log_temp.py`**:
    - Wrap the core logic of `fetch_and_log()` into an importable function that returns the logged data.
3.  **Refactor `plot_temp.py`**:
    - Wrap the core logic of `create_plot()` into an importable function.
4.  **Create `discord_bot.py`**:
    - Implement `!temp` command: Calls `fetch_and_log()` and sends a message with the results.
    - Implement `!plot` command: Calls `create_plot()` and sends the resulting PNG file.
    - Implement `!data` command: Sends the `temp_log.csv` file as an attachment.
5.  **Update `docker-compose.yml`**:
    - Add a `discord-bot` service that runs `python discord_bot.py`.
    - Ensure it has access to the same volumes and environment variables as the logger.
6.  **Update `.env`**:
    - Add a placeholder for `DISCORD_TOKEN`.

## Verification & Testing
1.  **Local Test**: Run the bot locally with a valid token and test the commands.
2.  **Docker Test**: Build and start the updated Docker services and verify the bot's functionality from within Discord.
3.  **Credential Check**: Ensure all sensitive tokens and passwords are correctly loaded from `.env`.
