# -*- coding: utf-8 -*-
"""
Created on Thu Nov 30 17:03:03 2023

@author: Martin
"""
import time
import json
import paho.mqtt.client as mqtt


# -- MQTT Wrapper -------------------------------------------------------------
class mqtt_wrapper:
    '''
    '''
    _debug = False      # defaults to no debug print out
    _topic = "mqtt"

    def debug_mode(debug: bool):
        mqtt_wrapper._debug = debug

    def set_topic(topic: str):
        mqtt_wrapper._topic = topic

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
        if rc==0:
            client.connected_flag = True
            print("MQTT: connected")
        else:
            print("MQTT: connection FAILED with return code = ", rc)
            if rc == 1:
                print("incorrect protocol version")
            elif rc == 2:
                print("invalid client identifier")
            elif rc == 3:
                print("server unavailable")
            elif rc == 4:
                print("bad username or password")
            elif rc == 5:
                print("not authorised")
            else:
                print("Unknown return code")

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
        mqtt.Client.connected_flag = False # create flag in mqtt class

        # Establish connection to MQTT broker
        self.client = mqtt.Client(transport="tcp",
                                  protocol=mqtt.MQTTv311,
                                  clean_session=True)

        self.topic = topic_prefix + mqtt_wrapper._topic

        self.client.on_connect = mqtt_wrapper.on_connect   # class function
        self.client.loop_start()
        self.client.connect(broker, port)

        while not self.client.connected_flag:   # set by call on_connect func
            print("MQTT: waiting for connection")
            time.sleep(1)
        time.sleep(5)

        # mqtt client should now be up
        self.pub(self.topic,
            json.dumps({
                "system": "MQTT connected",
                "timestamp": time.time()
            }), retain=True)

    def pub(self, topic, message, qos=0, retain=False):
        """

        Publish a message to mqtt.
        Prints to stdout in case of not succeeding.
        Echos message to stdout if mqtt_wrapper._debug is True.

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
            print(f"MQTT: Failed to send message to topic {topic}")

        if mqtt_wrapper._debug:
            print(str(topic))
            print('   ', str(message))

    def close(self):
        self.pub(self.topic,
                 json.dumps({
                     "remark": "MQTT connection closing now",
                     "timestamp": time.time(),
                     }), retain=True)
        self.client.loop_stop()
        self.client.disconnect()
