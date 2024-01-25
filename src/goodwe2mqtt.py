# -*- coding: utf-8 -*-
"""

"""
import time
import json
import logging
import logging.config
from pathlib import Path
from mqtt_wrapper import mqtt_wrapper
from graceful_killer import GracefulKiller
import goodwe as gw
import asyncio

JSONCONFIG = "./goodwe2mqtt.json"


def ftime():
    return time.strftime("%y-%m-%d %H:%M:%S +0000", time.gmtime())


class Config():
    """
    Container class for "global" parameters provided as class variables.
    """
    mqtt_client = None
    mqtt = {}                   # dictionary for parameters to run MQTT
    goodwe = {}                 # dictionary for json configuration of GOODWE
    logging = {}                # dictionary for the configuration of the logging

    # sensors not working in goodwe module or unwanted
    blacklist = []

    selections = {              # only parameters of following kinds are forwarded to MQTT
        "PV": gw.inverter.SensorKind.PV,
        "AC": gw.inverter.SensorKind.AC,
        "UPS": gw.inverter.SensorKind.UPS,
        "BAT": gw.inverter.SensorKind.BAT,
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
            Config.logging = config["logging"]
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


async def connect_inverter(config) -> gw.Inverter:
    topic = Config.goodwe["topic_prefix"] + Config.goodwe["state"]["topic"]
    retain = Config.goodwe["state"]["retain"]
    try:
        inverter = await gw.connect(config["ip_address"],
                                    config["family"],
                                    config["com_addr"],
                                    config["timeout"],
                                    config["retries"],
                                    False)
    except gw.RequestFailedException as e:
        inverter = None
        Config.mqtt_client.pub(topic,
                               json.dumps({
                                   "state": "unavailable",
                                   "exception": "RequestFailedException",
                                   "message": str(e.message),
                                   "time": ftime(),
                               }), retain)
        logging.exception(e.message)
    except gw.RequestRejectedException as e:
        inverter = None
        Config.mqtt_client.pub(topic,
                               json.dumps({
                                   "state": "unavailable",
                                   "exception": "RequestRejectedException",
                                   "message": str(e.message),
                                   "time": ftime(),
                               }), retain)
        logging.exception(e.message)
    return inverter


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

        # prepare dict to assemble response into slots as defined by whitelist
        slots = {
            "current": {},
            "energy": {},
            "frequency": {},
            "power": {},
            "state": {},
            "temperature": {},
            "voltage": {}
            }
        # fill the slots with entries from inverter's response
        for sensor in inverter.sensors():
            if sensor.kind == kind and \
               sensor.id_ in response and \
               sensor.id_ in Config.whitelist and \
               Config.whitelist[sensor.id_] in slots:

                slots[Config.whitelist[sensor.id_]][sensor.id_] = {
                    "value": response[sensor.id_],
                    "unit": sensor.unit,
                    "name": sensor.name,
                    # "kind": label,
                }

        # push collected datas to mqtt
        # topic:  ../<label of kind>/<key value of slot>
        topic = Config.goodwe["topic_prefix"] + Config.goodwe["sensor"][label]["topic"]
        retain = Config.goodwe["sensor"]["retain"]
        for slot, datas in slots.items():
            if datas:
                Config.mqtt_client.pub(topic + slot, json.dumps(datas), retain=retain)


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
        logging.debug(f"co4ever->{name}: elapsed = {elapsed:7.3f} s -- sleep {remains:7.3f} s")
        if remains > 0:
            await asyncio.sleep(remains)


async def main():
    """
    Start and controll the asyncio run loop.

    Returns
    -------
    None.

    """
    topic = Config.goodwe["topic_prefix"] + Config.goodwe["state"]["topic"]
    retain = Config.goodwe["state"]["retain"]

    Config.mqtt_client.pub(topic, json.dumps({
        "state": "init",
        "time": ftime(),
        "timestamp": time.time(),
        }), retain)

    # establish a connection to the inverter
    inverter = await connect_inverter(Config.goodwe)
    if inverter:
        Config.mqtt_client.pub(topic, json.dumps({
            "state": "connected",
            "inverter": str(inverter.serial_number),
            "address": Config.goodwe["ip_address"],
            "time": ftime(),
            "timestamp": time.time(),
        }), retain)
        logging.info(f"Connected to inverter {inverter.serial_number}.")
    else:
        Config.mqtt_client.pub(topic, json.dumps({"state": "stopped"}), retain)
        logging.critical("Connection to inverter could not be established!")
        logging.info("goodwe2mqtt stops now!")
        return

    # run functions with different intervals until killed
    killer = GracefulKiller()
    try:
        while not killer.kill_now:
            await asyncio.gather(
                co4ever(Config.goodwe["config"]["interval"],
                        get_config, "get_config", inverter),
                co4ever(Config.goodwe["setting"]["interval"],
                        get_settings, "get_setting", inverter),
                co4ever(Config.goodwe["sensor"]["interval"],
                        read_sensors, "read_sensors", inverter),
            )
    # TODO: check exception chain
    except gw.RequestFailedException as e:
        Config.mqtt_client.pub(topic,
                               json.dumps({
                                   "state": "connection lost",
                                   "exception": "RequestFailedException",
                                   "message": str(e.message),
                                   "time": ftime(),
                               }), retain)
        logging.exception(str(e.message))
        logging.critical("connection to inverter lost!")
        logging.critical("goodwe2mqtt stops now!")
        Config.mqtt_client.pub(topic, json.dumps({
                                        "state": "stopped",
                                        "time": ftime(),
                                        }), retain)
        return

if __name__ == '__main__':
    """
    """
    # read and process program configuraton parameters (provided as json file).
    Config.read(JSONCONFIG)

    # setup logging
    logging.config.dictConfig(Config.logging)
    logging.info("Configuration of goodwe2mqtt finalized.")

    # set up mqtt connection
    Config.mqtt_client = mqtt_wrapper(Config.mqtt["broker"],
                                      Config.mqtt["port"],
                                      Config.mqtt["topic_prefix"])

    # explore the goodwe configs and sensors forever
    asyncio.run(main())

    # tidy up MQTT  after ^C (SIGINT) or killed (SIGTERM)
    Config.mqtt_client.close()
