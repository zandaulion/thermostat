import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
from datetime import datetime, timedelta

LOG_FILE = os.environ.get("LOG_FILE", "temp_log.csv")
OUTPUT_PLOT = os.environ.get("OUTPUT_PLOT", "temp_plot.png")

def create_plot(days=7):
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

    # Filter data for the last N days
    cutoff_date = datetime.now() - timedelta(days=days)
    df = df[df['Timestamp'] >= cutoff_date]

    if df.empty:
        return None, f"No data found for the last {days} days."

    # Create the plot
    try:
        plt.figure(figsize=(12, 6))
        ax = plt.gca()

        # Plot for each Zone/Device combination
        for label, group in df.groupby(['Device Name', 'Zone']):
            name = f"{label[0]} - {label[1]}"
            plt.plot(group['Timestamp'], group['Temperature'], label=f"{name} (Actual)", marker='o', markersize=2)
            plt.plot(group['Timestamp'], group['Setpoint'], label=f"{name} (Setpoint)", linestyle='--', alpha=0.7)
            
            # Add red overlay when heating is ON
            # We use fill_between with a boolean mask. 
            # transform=ax.get_xaxis_transform() allows us to specify y=0 to y=1 (full height)
            plt.fill_between(group['Timestamp'], 0, 1, where=(group['Status'] == 'On'), 
                             color='red', alpha=0.1, transform=ax.get_xaxis_transform(), 
                             label=f"{name} (Heating Active)")

        plt.title(f'Thermostat Temperature (Last {days} Days)')
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
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"Invalid days argument: {sys.argv[1]}. Using default of 7.")

    path, error = create_plot(days=days)
    if error:
        print(error)
    else:
        print(f"Plot saved to {path} (Range: last {days} days)")
