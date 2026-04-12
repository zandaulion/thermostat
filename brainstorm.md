1. Data Structure (CSV Change)
let's add a humidity column, empty if missing. my Salus IT500 does not have humidity, so it will be empty

2. Handling Sleepy Sensors
log the last value, and mark the sensor as offline

3. Device Naming
let's add two columns: location (configurable per sensor), room (configurable per sensor)

4. New Discord Commands
let's add the location paraameter to all commands, to be able to query just an apartment

5. Local vs. Cloud
I need to go the cloud route, as my home server running docker is not in all appartments

6. plotting teh graph should take as input the location and plot the temperature only from that location
