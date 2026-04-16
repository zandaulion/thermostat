import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
from datetime import datetime, timedelta
try:
    from scipy.ndimage import gaussian_filter1d
except ImportError:
    gaussian_filter1d = None

LOG_FILE = os.environ.get("LOG_FILE", "temp_log.csv")
OUTPUT_PLOT = os.environ.get("OUTPUT_PLOT", "temp_plot.png")

def create_plot(days=7, location=None, smooth=False):
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

    # If no location is provided, pick the last one recorded
    if not location:
        location = df['Location'].iloc[-1]

    # Filter by location unless "all" is specified
    target_location = location.strip().lower()
    if target_location != "all":
        df = df[df['Location'].str.lower() == target_location]
        if df.empty:
            return None, f"No data found for location: {location}"
        title_location = df['Location'].iloc[0] # Use proper casing from data
    else:
        title_location = "All Locations"

    # Create the plot
    try:
        plt.figure(figsize=(12, 6))
        ax = plt.gca()

        # Plot for each Location/Room/Zone combination
        for label, group in df.groupby(['Location', 'Room', 'Zone']):
            loc_name = label[0]
            room_name = label[1]
            zone_name = label[2]
            
            if target_location == "all":
                legend_label = f"{loc_name} - {room_name}"
            else:
                legend_label = f"{room_name} ({zone_name})"
            
            y_values = group['Temperature'].values
            
            # Apply smoothing if requested and scipy is available
            if smooth and gaussian_filter1d and len(y_values) > 1:
                # Sigma=2 provides a nice balance between smoothing and accuracy
                y_values = gaussian_filter1d(y_values, sigma=2)
            
            plt.plot(group['Timestamp'], y_values, label=f"{legend_label} (Actual)", marker='o', markersize=2 if not smooth else 0)
            
            # Only plot setpoint if it's not empty
            if not group['Setpoint'].isnull().all() and (group['Setpoint'] != "").all():
                plt.plot(group['Timestamp'], group['Setpoint'], label=f"{legend_label} (Setpoint)", linestyle='--', alpha=0.7)
            
            # Add red overlay when heating is ON
            plt.fill_between(group['Timestamp'], 0, 1, where=(group['Status'] == 'On'), 
                             color='red', alpha=0.1, transform=ax.get_xaxis_transform(), 
                             label=f"{legend_label} (Heating Active)")

        plt.title(f'Thermostat Temperature - {title_location} (Last {days} Days{" - Smoothed" if smooth else ""})')
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
    smooth = False
    
    args = sys.argv[1:]
    
    # Process "smooth" flag first
    if "smooth" in [a.lower() for a in args]:
        smooth = True
        args = [a for a in args if a.lower() != "smooth"]
        
    if len(args) > 0:
        try:
            days = int(args[0])
        except ValueError:
            location = args[0]
            days = 7
    
    if len(args) > 1 and not location:
        location = " ".join(args[1:])
    elif len(args) > 1:
        try:
            days = int(args[1])
        except ValueError:
            pass

    path, error = create_plot(days=days, location=location, smooth=smooth)
    if error:
        print(f"Error: {error}")
    else:
        print(f"Plot saved to {path} (Range: last {days} days, Smooth: {smooth})")
