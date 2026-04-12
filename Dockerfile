# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Disable Python output buffering
ENV PYTHONUNBUFFERED=1

# Install git so we can fetch the pyit500 library
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Ensure data files are written to a mounted volume for persistence
# This is where temp_log.csv and temp_plot.png will live
VOLUME /app/data

# Environment variable to specify where logs go
ENV LOG_FILE=/app/data/temp_log.csv
ENV OUTPUT_PLOT=/app/data/temp_plot.png

# The command to run the logger (we'll modify log_temp.py slightly for Docker)
CMD ["python", "log_temp.py"]
