# -*- coding: utf-8 -*-
"""

"""
import time
import json
from pathlib import Path
from mqtt_wrapper import mqtt_wrapper
from graceful_killer import GracefulKiller
import goodwe as gw
import asyncio

DEBUG = True
JSONCONFIG = "./goodwe_config.json"

class Config():
    """
    Container class for "global" parameters.
    Global parameters are provided as class variables.
    """
    goodwe = {}                 # dictionary for json configuration of GOODWE
    mqtt = {}                   # dictionary for parameters to run MQTT
    mqtt_client = None

    # sensors not working in goodwe module or unwanted
    blacklist = []

    selections = {              # only parameters of following kinds are forwarded to MQTT
        "PV": gw.inverter.SensorKind.PV,
        "AC": gw.inverter.SensorKind.AC,
        "GRID": gw.inverter.SensorKind.GRID,
    }

    def read(path='./goodwe_config.json'):
        """
        function to read the configuration
        """
        try:
            # -- read and process program configuraton parameters -----------------
            fp = open(Path(path))
            config = json.load(fp)
            fp.close()

            # set class properties
            Config.mqtt = config["mqtt"]
            Config.goodwe = config["goodwe"]
            # for convenience: whitelist and blacklist are items of the goodwe
            Config.whitelist = Config.goodwe["sensor"]["whitelist"]
            Config.blacklist = Config.goodwe["blacklist"]

        except KeyError as e:
            print(f'caught {type(e)} with nested {e.exceptions}')
            exit()
        except FileNotFoundError as e:
            print(f'caught {type(e)} with nested {e.exceptions}')
            exit()


def sensor_kind_label(sensor_kind):
    """
    translate Enums to strings
    """
    labels = {
        gw.inverter.SensorKind.PV: "PV",
        gw.inverter.SensorKind.AC: "AC",
        gw.inverter.SensorKind.UPS: "UPS",
        gw.inverter.SensorKind.BAT: "BAT",
        gw.inverter.SensorKind.GRID: "GRID",
    }
    if sensor_kind in labels:
        return labels[sensor_kind]
    else:
        return None


async def get_config(inverter):
    """
    get inverter configuration and push it to MQTT

    Parameters
    ----------
    inverter : Inverter object

    Returns
    -------
    None.

    """
    configs = {
        "model_name":       inverter.model_name,
        "serial_number":    inverter.serial_number,
        "arm_version":      inverter.arm_version,
        "arm_svn_version":  inverter.arm_svn_version,
        "arm_firmware":     inverter.arm_firmware,
        "dsp1_version":     inverter.dsp1_version,
        "dsp2_version":     inverter.dsp2_version,
        "dsp_svn_version":  inverter.dsp_svn_version,
        "firmware":         inverter.firmware,
        "modbus_version":   inverter.modbus_version,
        "rated_power":      inverter.rated_power,
        "ac_output_type":   inverter.ac_output_type,
    }

    topic = Config.goodwe["topic_prefix"] + Config.goodwe["config"]["topic"]
    Config.mqtt_client.pub(topic, json.dumps(configs), 
                           retain=Config.goodwe["config"]["retain"])


async def get_settings(inverter):
    """
    Read settings of inverter and push them to MQTT.
    The available settings provided by the inverter object are filtered 
    by a blacklist (Config.blacklist).

    Parameters
    ----------
    inverter : Inverter object

    Returns
    -------
    None.

    """
    settings = {}
    for sensor in inverter.settings():
        if sensor.id_ not in Config.blacklist:    # filter settings
            settings[sensor.id_] = {
                        "value": str(await inverter.read_setting(sensor.id_)),
                        "unit": sensor.unit,
                        "name": sensor.name,
                        "kind": sensor_kind_label(sensor.kind),
                    }
    
    topic = Config.goodwe["topic_prefix"] + Config.goodwe["setting"]["topic"]
    Config.mqtt_client.pub(topic, json.dumps(settings),
                           retain=Config.goodwe["setting"]["retain"])


async def read_sensors(inverter):
    """
    Read sensor values of inverter and push them to MQTT.

    The available  sensors presented by inverter are filtered and tagged and 
    then send to MQTT.
    
    Filters are sensor.kind (Cinfig.selections) and the sensor whitelist.
    Tagging is provided by the whitelist.
    
    Parameters
    ----------
    inverter : Inverter object
        source of sensor values

    Returns
    -------
    None.

    """
    response = await inverter.read_runtime_data()

    for key, kind in Config.selections.items():
        label = sensor_kind_label(kind)

        currents = {}
        voltages = {}
        powers = {}
        energies = {}
        frequencies = {}
        states = {}

        for sensor in inverter.sensors():
            if sensor.kind == kind and \
               sensor.id_ in response and \
               sensor.id_ in Config.whitelist:

                data = {
                        "value": response[sensor.id_],
                        "unit": sensor.unit,
                        "name": sensor.name,
                        # "kind": label,
                    }
                if Config.whitelist[sensor.id_] == "current":
                    currents[sensor.id_] = data
                elif Config.whitelist[sensor.id_] == "voltage":
                    voltages[sensor.id_] = data
                elif Config.whitelist[sensor.id_] == "power":
                    powers[sensor.id_] = data
                elif Config.whitelist[sensor.id_] == "energy":
                    energies[sensor.id_] = data
                elif Config.whitelist[sensor.id_] == "frequency":
                    frequencies[sensor.id_] = data
                elif Config.whitelist[sensor.id_] == "state":
                    states[sensor.id_] = data
        
        topic = Config.goodwe["topic_prefix"] + Config.goodwe["sensor"][label]["topic"]
        retain = Config.goodwe["sensor"]["retain"]
        
        Config.mqtt_client.pub(topic + "current", json.dumps(currents), retain=retain)
        Config.mqtt_client.pub(topic + "voltage", json.dumps(voltages), retain=retain)
        Config.mqtt_client.pub(topic + "power", json.dumps(powers), retain=retain)
        Config.mqtt_client.pub(topic + "energy", json.dumps(energies), retain=retain)
        Config.mqtt_client.pub(topic + "frequency", json.dumps(frequencies), retain=retain)
        Config.mqtt_client.pub(topic + "state", json.dumps(states), retain=retain)


async def co4ever(period, cofn, name, *args):
    """
    Run the awaitable cofn repeatedly with given period.

    Parameters
    ----------
    period : float
        DESCRIPTION.
    cofn : awaitable 
        coroutine, async function, ... to be run periodically
    name : string
        for echo print
    *args :
        arguments for cofn

    Returns
    -------
    None.

    """
    while True:
        then = time.time()
        await cofn(*args)
        elapsed = time.time() - then
        remains = period - elapsed
        print(f"{name:20} elapsed: {elapsed} s -- sleep {remains} s")
        if remains > 0:
            await asyncio.sleep(remains)


async def main():
    """
    Start and controll the asyncio run loop.

    Returns
    -------
    None.

    """
    # connect to goodwe inverter
    inverter =  await gw.connect(Config.goodwe["ip_address"],
                                 Config.goodwe["com_addr"],
                                 Config.goodwe["family"],
                                 Config.goodwe["timeout"],
                                 Config.goodwe["retries"])
    # run functions with different intervals until killed
    killer = GracefulKiller()
    while not killer.kill_now:
        await asyncio.gather(
            co4ever(Config.goodwe["config"]["interval"], get_config, "config", inverter),
            co4ever(Config.goodwe["setting"]["interval"], get_settings, "setting", inverter),
            co4ever(Config.goodwe["sensor"]["interval"], read_sensors, "sensor", inverter)
            )


if __name__ == '__main__':
    """
    """
    # read and process program configuraton parameters (provided as json file).
    Config.read(JSONCONFIG)

    # propagate debugging mode to mqtt_wrapper classs
    mqtt_wrapper.debug_mode(DEBUG)
    # set up mqtt connection
    Config.mqtt_client = mqtt_wrapper(Config.mqtt["broker"],
                                      Config.mqtt["port"],
                                      Config.mqtt["topic_prefix"])

    # explore the goodwe configs and sensors forever
    asyncio.run(main())

    # tidy up MQTT  after ^C (SIGINT) or killed (SIGTERM)
    Config.mqtt_client.close()
