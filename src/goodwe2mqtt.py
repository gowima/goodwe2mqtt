# -*- coding: utf-8 -*-
"""
@author: gowima
"""
import sys
import argparse
from pathlib import Path
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import logging
import logging.config
import asyncio
import pprint

from mqtt_wrapper import mqtt_wrapper
from graceful_killer import GracefulKiller
import goodwe as gw

'''
GOODWE2MQTT

This module acts as a link between the Modbus interface of Goodwe inverters to
a MQTT broker. It provides

- the inverter configuration
- the inverter settings
- sensor definitions (for Home Assistant device discovery)
- sensor values

Most of the parameters needed to set up connections (Inverter/Modbus, MQTT
broker) are defined in a json file that must be provided by the user.

The propagation of sensor definitions and values to MQTT is controlled by a
set of sensors, defined as whitlist in the json-configuration.

'''
VERSION = 20250312

# =========================================================================
# argument handling definitions
DESCRIPTION = '''
Push configuration, settings and sensor definitions of a Goodwe inverter
to a mqtt broker and/or print the same once to a file.
'''
parser = argparse.ArgumentParser(
    description=DESCRIPTION,
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument(
    '-p', '--print', default=False,
    action=argparse.BooleanOptionalAction,
    help="Print sensor definitions once at startup.")
parser.add_argument(
    '-m', '--mqtt', default=True,
    action=argparse.BooleanOptionalAction,
    help="Push MQTT messages. --no-mqtt suppresses MQTT")
parser.add_argument(
    '-j', '--jsonfile', type=str,
    default="./goodwe2mqtt.json",
    help='Json file with inverter definitions.')
parser.add_argument(
    '-o', '--outfile', type=str,
    default="./goodwe2mqtt.txt",
    help='Print inverter configuration and sensors definitions to given file.')
args = parser.parse_args()

# =========================================================================
# some constants
SENSORKINDLABELS = {
    gw.inverter.SensorKind.PV: "PV",
    gw.inverter.SensorKind.AC: "AC",
    gw.inverter.SensorKind.UPS: "UPS",
    gw.inverter.SensorKind.BAT: "BAT",
    gw.inverter.SensorKind.GRID: "GRID",
    None: "ANY"
}
UNITS = ["kWh", "A", "V", "W", "var", "VA", "C", "Hz", "%", "h"]
UNITS_X = {"C": "°C"}
STATE_CLASS = {
    "kWh": "total",
    "A": "measurement",
    "V": "measurement",
    "W": "measurement",
    "var": "measurement",
    "VA": "measurement",
    "C": "measurement",
    "Hz": "measurement",
    "%": "measurement",
    "h": "total_increasing",
    }
DEVICE_CLASS = {
    "kWh": "energy",
    "A": "current",
    "V": "voltage",
    "W": "power",
    "var": "reactive_power",
    "VA": "apparent_power",
    "C": "temperature",
    "Hz": "frequency",
    "%": "battery",
    "h": "duration",
    }

# =========================================================================


def system_time_as_str():
    '''
    Get system time formatted as string for local timezone.
    Local timezone is Europe/Berlin
    '''
    date = datetime.now(ZoneInfo("Europe/Berlin"))
    return date.isoformat()


def get_time_from_response(unaware: datetime):
    '''
        make unaware datetime obj aware of timezone
        assumptions are:  unaware is given in local time
                          local timezone is Europe/Berlin
    '''
    aware = datetime(unaware.year, unaware.month, unaware.day,
                     unaware.hour, unaware.minute, unaware.second,
                     tzinfo=ZoneInfo("Europe/Berlin"))
    timestamp = aware.timestamp()
    time_as_str = aware.isoformat()
    return timestamp, time_as_str


def sensor_kind_label(sensor_kind):
    """
    translate Enums to strings
    """
    if sensor_kind in SENSORKINDLABELS:
        return SENSORKINDLABELS[sensor_kind]
    return None


class Config():
    """
    Container class for "global" parameters provided as class variables.
    """
    mqtt_client = None
    mqtt = {}               # dictionary for parameters to run MQTT
    goodwe = {}             # dictionary for json configuration of GOODWE
    logging = {}            # dictionary for the configuration of the logging

    # sensors not working in goodwe module or unwanted
    blacklist = []

    def read(path=args.jsonfile):
        """
        function to read the configuration
        """
        try:
            # -- read and process program configuraton parameters -------------
            fp = open(Path(path))
            config = json.load(fp)
            fp.close()

            # set class properties
            Config.mqtt = config["mqtt"]
            Config.goodwe = config["goodwe"]
            Config.logging = config["logging"]
            Config.blacklist = Config.goodwe["settings"]["blacklist"]
            # for convenience: whitelist and blacklist are items of the goodwe
            Config.whitelist = Config.goodwe["sensors"]["whitelist"]
            # generate a set with slots for sensors given as value of sensor id
            Config.slots = set(Config.whitelist.values())
        except KeyError as e:
            print(f'caught {type(e)} with nested {e.exceptions}')
            sys.exit(1)
        except FileNotFoundError as e:
            print(f'caught {type(e)} with nested {e.exceptions}')
            sys.exit(2)


async def connect_inverter(config) -> gw.Inverter:
    '''
    Set up a connection to the Modbus (UDP or TCP) interface of a
    Goodwe inverter.

    Parameters
    ----------
    config : dict
        Configuration parameters for the connection.

    Returns
    -------
    inverter : Inverter object (goodwe)
        inverter object from goodwe module
    '''
    topic = Config.goodwe["topic_prefix"] + Config.goodwe["state"]["topic"]
    retain = Config.goodwe["state"]["retain"]
    try:
        inverter = await gw.connect(host=config["ip_address"],
                                    port=config["port"],
                                    family=config["family"],
                                    comm_addr=config["comm_addr"],
                                    timeout=config["timeout"],
                                    retries=config["retries"],
                                    do_discover=False)
    except gw.RequestFailedException as e:
        inverter = None
        Config.mqtt_client.pub(topic,
                               json.dumps({
                                   "state": "unavailable",
                                   "exception": "RequestFailedException",
                                   "message": str(e.message),
                                   "time": system_time_as_str(),
                               }), retain)
        logging.exception(e.message)
    except gw.RequestRejectedException as e:
        inverter = None
        Config.mqtt_client.pub(topic,
                               json.dumps({
                                   "state": "unavailable",
                                   "exception": "RequestRejectedException",
                                   "message": str(e.message),
                                   "time": system_time_as_str(),
                               }), retain)
        logging.exception(e.message)
    return inverter


def set_inverter_config(inverter):
    '''
    Enhance device configuration for HA device discovery in Config
    with inverter parameters provided by the inverter itself.

    Parameters
    ----------
    inverter : Inverter object (goodwe)
        inverter object from goodwe module

    Returns
    -------
    None.
    '''
    Config.goodwe["HA_device"]["serial_number"] = inverter.serial_number
    Config.goodwe["HA_device"]["sw_version"] = \
        str(inverter.arm_version) + "." + str(inverter.arm_svn_version)
    return


async def publish_config(inverter):
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


async def publish_settings(inverter):
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
    settings = []
    for sensor in inverter.settings():
        if sensor.id_ not in Config.blacklist:    # filter settings
            settings.append({
                "id": sensor.id_,
                "value": str(await inverter.read_setting(sensor.id_)),
                "unit": sensor.unit,
                "name": sensor.name,
                "kind": sensor_kind_label(sensor.kind),
            })

    topic = Config.goodwe["topic_prefix"] + Config.goodwe["settings"]["topic"]
    Config.mqtt_client.pub(topic, json.dumps(settings),
                           retain=Config.goodwe["settings"]["retain"])


async def publish_sensor_values(inverter):
    """
    Read sensor values of inverter and push them to MQTT.

    The available  sensors presented by inverter are filtered and tagged and
    then send to MQTT.

    Filters are sensor.kind (Config.selections) and the sensor whitelist.
    Tagging is provided by the whitelist.

    Parameters
    ----------
    inverter : Inverter object
        source of sensors (config and values)

    Returns
    -------
    None.

    """
    retain = Config.goodwe["sensors"]["retain"]

    datas = await inverter.read_runtime_data()

    # timestamp sensor result is provided as datatime obj -> posix timestamp
    # assumption is here: datetime tupel values are is given wrt local time
    timestamp, time_as_str = get_time_from_response(datas["timestamp"])

    for kind, label in SENSORKINDLABELS.items():
        # topic:  ../<label of kind>/<key value of slot>
        topic = Config.goodwe["topic_prefix"] + \
            Config.goodwe["sensors"][label]["topic"]

        # prepare dict to assemble response into slots as defined by whitelist
        slot_ds = {}
        for slot in Config.slots:
            slot_ds[slot] = {}

        # fill the slot_ds with entries from inverter's response
        for sensor in inverter.sensors():
            if sensor.kind == kind and \
                    sensor.id_ in Config.whitelist and \
                    sensor.id_ in datas:

                slot_ds[Config.whitelist[sensor.id_]][sensor.id_] = {
                        "value": datas[sensor.id_],
                        "unit": sensor.unit,
                        "name": sensor.name,
                        }
        # push collected datas to mqtt
        for slot, ds in slot_ds.items():
            if ds:
                message = {"timestamp": timestamp,
                           "inverter_time": time_as_str,
                           "sensors": ds}
                Config.mqtt_client.pub(
                    topic + slot, json.dumps(message), retain=retain)


def ha_sensor_config(s, slot):
    """
    Format sensor configuration for MQTT Device Discovery (Home Assistent).

    Parameters
    ----------
    s :     Sensor object
    slot :  Slot as defined for this sensor in whitelist.

    Returns
    -------
    sensor.config: dict for MQTT payload
    """

    state_topic = "{}{}{}".format(
        Config.goodwe["topic_prefix"],
        Config.goodwe["sensors"][sensor_kind_label(s.kind)]["topic"],
        slot)
    sensor_config = {
        "name": s.name,
        "unique_id": "GW_" + s.id_,
        "object_id": "GW_" + s.id_,
        "state_topic": state_topic,
        "value_template": "{}value_json.sensors.{}.value{}".format(
            "{{", s.id_, "}}")
        }

    if s.unit in UNITS:
        if s.unit in UNITS_X:
            sensor_config["unit_of_measurement"] = UNITS_X[s.unit]
        else:
            sensor_config["unit_of_measurement"] = s.unit
        sensor_config["state_class"] = STATE_CLASS[s.unit]
        sensor_config["device_class"] = DEVICE_CLASS[s.unit]

    sensor_config["device"] = Config.goodwe["HA_device"]
    sensor_config["origin"] = Config.goodwe["HA_origin"]

    return sensor_config


async def publish_ha_sensor_discovery(inverter):
    """
    Read sensor definition and push HomeAssistant Device Discovery messages
    to a MQTT broker.

    The discovery messages for HomeAssistant of available sensors (presented
    by inverter) are pushed to MQTT only if whitelisted. An additional filter
    is sensor.kind, which must be defined in Config.selections.

    Tagging (slot) is provided by the whitelist.

    Parameters
    ----------
    inverter : Inverter object (goodwe)
        inverter object from goodwe module

    Returns
    -------
    None.
    """
    for s_id, slot in Config.whitelist.items():
        s = inverter._get_sensor(s_id)

        if s is not None:
            sensor_config = ha_sensor_config(s, slot)
            Config.mqtt_client.pub(
                "homeassistant/sensor/goodwe_{}/{}/config".format(slot, s_id),
                json.dumps(sensor_config),
                retain=Config.goodwe["config"]["retain"])


def print_sensor_definitions(inverter, ofp):
    '''
    Parameters
    ----------
    inverter : Inverter (module goodwe)
        goodwe Inverter object
    ofp : file pointer
        Stream where printing is going to.

    Returns
    -------
    None.
    '''
    json.dump(Config.goodwe["HA_device"], fp=ofp, indent=2)
    print("\nsensors of inverter:", file=ofp)

    sensors = {}
    for s in inverter.sensors():
        sensors[s.id_] = {"name": s.name, "unit": s.unit, "kind": s.kind}

    pp = pprint.PrettyPrinter(stream=ofp, indent=2, width=120, sort_dicts=False)
    pp.pprint(sorted(sensors.items()))


async def print_runtime_data(inverter, ofp):
    '''
    Print the Modbus response of an inverter for the whitelisted sensors.
    Print sensor configuration that are according to HA device discovery. The
    list of sensor configuration  is confined to sensors that are whitelisted.

    Parameters
    ----------
    inverter : Inverter object (goodwe)
        inverter object from goodwe module
    ofp : file pointer
        Stream where printout is going to.

    Returns
    -------
    None.
    '''
    print("\nrun time data\n", file=ofp)
    datas = await inverter.read_runtime_data()

    sensor_configs = {}
    for s_id, slot in Config.whitelist.items():
        s = inverter._get_sensor(s_id)
        if s is not None and s_id in datas:
            print(f"\t{s_id:30}:\t{s.name} = {datas[s_id]} {s.unit}",
                  file=ofp)
            sensor_configs[s_id] = ha_sensor_config(s, slot)

    print("\nHA device discovery config data\n", file=ofp)
    json.dump(sensor_configs, ofp, indent=2)


async def print_all(inverter):
    '''
    Print configuration, settings, sensor definitions and sensor values of
    inverter. The output stream is (pre)configured by the argument sttings.

    Parameters
    ----------
    inverter : Inverter (goodwe module)
        Inverter object.

    Returns
    -------
    None.
    '''
    if args.print:
        ofp = open(args.outfile, mode='wt')

        print_sensor_definitions(inverter, ofp)
        await print_runtime_data(inverter, ofp)

        ofp.close()
    return


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
        logging.debug(
            f"co4ever->{name}: elapsed = {elapsed:7.3f} s -- sleep {remains:7.3f} s")
        if remains > 0:
            await asyncio.sleep(remains)


async def main():
    """
    Start and control the asyncio run loop.

    Returns
    -------
    None.

    """
    topic = Config.goodwe["topic_prefix"] + Config.goodwe["state"]["topic"]
    retain = Config.goodwe["state"]["retain"]

    # establish connection to inverter
    inverter = await connect_inverter(Config.goodwe)
    if inverter:
        set_inverter_config(inverter)
        logging.info(f"Connected to inverter {inverter.serial_number}.")
        if args.mqtt:
            Config.mqtt_client.pub(topic, json.dumps({
                "state": "connected",
                "inverter": str(inverter.serial_number),
                "address": Config.goodwe["ip_address"],
                "system_time": system_time_as_str(),
                "timestamp": time.time(),
                }), retain)
    else:
        logging.critical("Connection to inverter could not be established!")
        logging.info("goodwe2mqtt stops now!")
        if args.mqtt:
            Config.mqtt_client.pub(topic,
                                   json.dumps({"state": "stopped"}),
                                   retain)
        return

    # print inverter configuratio, settings, sensor definitions and values.
    if args.print: await print_all(inverter)

    if args.mqtt:
        # run functions with different intervals until killed
        killer = GracefulKiller()
        try:
            while not killer.kill_now:
                await asyncio.gather(
                    # publish HA device discovery configurations
                    co4ever(Config.goodwe["config"]["interval"],
                            publish_ha_sensor_discovery,
                            "publish_ha_sensor_discovery", inverter),
                    # publish static inverter data
                    co4ever(Config.goodwe["config"]["interval"],
                            publish_config, "publish_config", inverter),
                    co4ever(Config.goodwe["settings"]["interval"],
                            publish_settings, "publish_setting", inverter),
                    # publish measurements
                    co4ever(Config.goodwe["sensors"]["interval"],
                            publish_sensor_values,
                            "publish_sensor_values", inverter)
                    )
        # TODO: check exception chain
        except gw.RequestFailedException as e:
            Config.mqtt_client.pub(topic,
                                   json.dumps({
                                       "state": "connection lost",
                                       "exception": "RequestFailedException",
                                       "message": str(e.message),
                                       "system_time": system_time_as_str(),
                                   }), retain)
            logging.exception(str(e.message))
            logging.critical("connection to inverter lost!")
            logging.critical("goodwe2mqtt stops now!")
            Config.mqtt_client.pub(topic, json.dumps({
                "state": "stopped",
                "system_time": system_time_as_str(),
            }), retain)
    return

if __name__ == '__main__':
    """
    """
    # read and process program configuraton parameters (provided as json file).
    Config.read(args.jsonfile)

    # setup logging
    logging.config.dictConfig(Config.logging)
    logging.info("Configuration of goodwe2mqtt finalized.")

    # set up mqtt connection
    if args.mqtt:
        Config.mqtt_client = mqtt_wrapper(Config.mqtt["broker"],
                                          Config.mqtt["port"],
                                          Config.mqtt["topic_prefix"])

    # explore the goodwe configs and sensors forever
    asyncio.run(main())

    # tidy up MQTT  after ^C (SIGINT) or killed (SIGTERM)
    if args.mqtt:
        Config.mqtt_client.close()
