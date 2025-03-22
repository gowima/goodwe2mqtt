# -*- coding: utf-8 -*-
"""
Created on Thu Nov 30 17:03:03 2023

@author: gowima
"""
import time
import logging
import json
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


def ftime():
    return time.strftime("%y-%m-%d %H:%M:%S +0000", time.gmtime())


# -- MQTT Wrapper -------------------------------------------------------------
class mqtt_wrapper:
    '''
    '''
    _topic = "mqtt"

    @classmethod
    def set_topic(topic: str):
        mqtt_wrapper._topic = topic

    @staticmethod
    def on_connect(client, userdata, flags, rc):
        """
        Call back funtion for the connection status of a mqtt.Client.
        Provides the error handling on connection to a mqtt broker.

        Parameters
        ----------
        client : mqtt.Client
        userdata : TYPE
        flags : TYPE
        rc : int
            return code when connecting to mqtt
        """
        # TODO: exception handling on error
        client.on_connect_rc = rc
        if rc == 0:
            client.connected_flag = True
        else:
            logger.error(f"MQTT: connection FAILED with return code = {rc}")
            if rc == 1:
                logger.error("MQTT connect: Incorrect protocol version")
            elif rc == 2:
                logger.error("MQTT connect: Invalid client identifier")
            elif rc == 3:
                logger.error("MQTT connect: Server unavailable")
            elif rc == 4:
                logger.error("MQTT connect: Bad username or password")
            elif rc == 5:
                logger.error("MQTT connect: Not authorised")
            else:
                logger.error("MQTT connect: Unknown return code")

    def __init__(self, broker, port, topic_prefix=""):
        """
        Initiate a connection to a mqtt broker.
        When the conection has been established a note is published to
        mqtt broker with the topic <topic_prefix + mqtt_wrapper._topic>

        Parameters
        ----------
        broker : str
            ip address of mqtt broker.
        port : int
            port number of mqtt broker
        topic_prefix : TYPE, optional
            DESCRIPTION. The default is "".

        """

        mqtt.Client.connected_flag = False  # create flag in mqtt class
        mqtt.Client.on_connect_rc = 0       # create variable for return code

        # Establish connection to MQTT broker
        self.client = mqtt.Client(transport="tcp",
                                  protocol=mqtt.MQTTv311,
                                  clean_session=True)

        self.topic = topic_prefix + mqtt_wrapper._topic

        self.client.on_connect = mqtt_wrapper.on_connect   # class function
        self.client.loop_start()
        self.client.connect(broker, port)

        # TODO loop forever? What if connection fails?
        while not self.client.connected_flag:   # set by call on_connect func
            logger.info(f"Waiting for connection to mqtt broker, rc = {self.client.on_connect_rc}")
            time.sleep(1)
        time.sleep(5)

        # mqtt client should now be up
        logger.info(f"Connected to mqtt broker at {broker}")
        self.pub(self.topic,
                 json.dumps({"system": "MQTT connected",
                             "address": str(broker),
                             "time": ftime(),
                             "timestamp": time.time()
                             }),
                 retain=True)

    def pub(self, topic, message, qos=0, retain=False):
        """
        Publish a message to mqtt.

        Parameters
        ----------
        topic : str
            mqtt topic
        message : str
            payload as str
        qos : int, optional
            quality of service. The default is 0.
        retain : bool, optional
            retain topic if set to True. The default is False.

            See mqtt documentation for quos and retain.

        Returns
        -------
        None.

        """
        res = self.client.publish(topic, message, qos=qos, retain=retain)
        status = res[0]
        if not status == 0:
            logger.warning(f"MQTT: Failed to send message to topic {topic}")
            logger.debug('   ' + str(message))

    def close(self):
        self.pub(self.topic,
                 json.dumps({
                     "remark": "MQTT connection closing now",
                     "time": ftime(),
                     "timestamp": time.time(),
                     }), retain=True)
        self.client.loop_stop()
        self.client.disconnect()
        self.client = None
        self.topic = ""
        logger.info("MQTT connection closed")
