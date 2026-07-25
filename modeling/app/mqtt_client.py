"""Thin MQTT publisher for model outputs.

Publishes retained JSON to `<base_topic>/<name>` so HA MQTT sensors can subscribe.
Broker host/credentials come from Mosquitto service discovery (via run.sh).
"""
from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

log = logging.getLogger("app.mqtt")


class MqttPublisher:
    def __init__(self, host: str, port: int, user: str, password: str, base_topic: str):
        self._base = base_topic.rstrip("/")
        self._client = mqtt.Client(
            client_id="creek_modeling", protocol=mqtt.MQTTv311
        )
        if user:
            self._client.username_pw_set(user, password)
        self._host, self._port = host, port

    def connect(self) -> None:
        log.info("Connecting to MQTT %s:%s", self._host, self._port)
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish(self, name: str, payload: dict, retain: bool = True) -> None:
        topic = f"{self._base}/{name}"
        self._client.publish(topic, json.dumps(payload), qos=1, retain=retain)
        log.debug("Published %s -> %s", topic, payload)
