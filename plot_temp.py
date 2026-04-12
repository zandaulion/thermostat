import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
from datetime import datetime, timedelta

LOG_FILE = os.environ.get("LOG_FILE", "temp_log.csv")
OUTPUT_PLOT = os.environ.get("OUTPUT_PLOT", "temp_plot.png")

def create_plot(days=7, location=None):
    if not os.path.exists(LOG_FILE):
        return None, f"Error: {LOG_FILE} not found. Run the logger first."

    # Load the data
    try:
        df = pd.read_csv(LOG_FILE)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    except Exception as e:
        return None, f"Error reading CSV: {e}"

    if df.empty:
        return None, "CSV is empty."

    # If no location is provided, pick the first one available
    if not location:
        location = df['Location'].iloc[-1]

    # Filter data for the last N days and specified location
    cutoff_date = datetime.now() - timedelta(days=days)
    df = df[(df['Timestamp'] >= cutoff_date) & (df['Location'] == location)]

    if df.empty:
        return None, f"No data found for the last {days} days at location: {location}."

    # Create the plot
    try:
        plt.figure(figsize=(12, 6))
        ax = plt.gca()

        # Plot for each Room/Zone combination in the specified location
        for label, group in df.groupby(['Room', 'Zone']):
            # label is (Room, Zone)
            room_name = label[0]
            zone_name = label[1]
            legend_label = f"{room_name} ({zone_name})"
            
            plt.plot(group['Timestamp'], group['Temperature'], label=f"{legend_label} (Actual)", marker='o', markersize=2)
            
            # Only plot setpoint if it's not empty (Salus has it, Tuya sensors won't)
            if not group['Setpoint'].isnull().all() and (group['Setpoint'] != "").all():
                plt.plot(group['Timestamp'], group['Setpoint'], label=f"{legend_label} (Setpoint)", linestyle='--', alpha=0.7)
            
            # Add red overlay when heating is ON
            plt.fill_between(group['Timestamp'], 0, 1, where=(group['Status'] == 'On'), 
                             color='red', alpha=0.1, transform=ax.get_xaxis_transform(), 
                             label=f"{legend_label} (Heating Active)")

        plt.title(f'Thermostat Temperature - {location} (Last {days} Days)')
        plt.xlabel('Time')
        plt.ylabel('Temperature (°C)')
        
        # Avoid duplicate labels in legend
        handles, labels = plt.gca().get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        plt.legend(by_label.values(), by_label.keys())
        
        plt.grid(True, which='both', linestyle='--', alpha=0.5)
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Save the plot
        plt.savefig(OUTPUT_PLOT)
        return OUTPUT_PLOT, None
    except Exception as e:
        return None, f"Error generating plot: {e}"

if __name__ == "__main__":
    days = 7
    location = None
    
    # Simple argument parsing
    # Usage: python plot_temp.py [days] [location]
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"Invalid days argument: {sys.argv[1]}. Using default of 7.")
    
    if len(sys.argv) > 2:
        location = " ".join(sys.argv[2:])

    path, error = create_plot(days=days, location=location)
    if error:
        print(error)
    else:
        print(f"Plot saved to {path} (Location: {location}, Range: last {days} days)")
