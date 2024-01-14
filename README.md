# goodwe2mqtt

 Publish configuration, settings and running data of a GoodWe inverter to a mqtt broker.
 The software is based on pypi module goodwe (authors: Marcel Blijleven, Martin Letenay). 
 See also https://github.com/marcelblijleven/goodwe.

 Files:
 
 - goodwe2mqtt.py     The SCRIPT.
 - goodwe_config.json Configuration parameters for mqtt and GoodWe.
 - goodwe.sh          Shell script to set the python environment and run goodwe2mqtt.
 - goodwe.service     Configuration of a systemctl service running goodwe2mqtt in background (Raspian, Debian).
 - mqtt_wrapper.py    Provides the class mqtt_wrapper for convenience with the paho.mqtt api.
 - graceful_killer    Handle Signal handler to stop/kill goodwe2mqtt "softly".

Developed for and tested with GoodWe GW29K9-ET.
