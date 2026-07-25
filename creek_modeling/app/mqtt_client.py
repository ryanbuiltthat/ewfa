"""MQTT client for the modeling service.

Publishes retained JSON model outputs / status to `<base_topic>/<name>` (HA MQTT
sensors subscribe), and optionally subscribes to `<base_topic>/cmd/#` so the
dashboard's buttons can drive the pipeline on demand. Broker host/credentials
come from Mosquitto service discovery (via run.sh).

Targets paho-mqtt 2.x (see requirements.txt): the client is constructed with an
explicit `CallbackAPIVersion` and uses the v2 callback signatures.
"""
from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from .commands import CommandQueue

log = logging.getLogger("app.mqtt")


class MqttClient:
    def __init__(self, host: str, port: int, user: str, password: str, base_topic: str):
        self._base = base_topic.rstrip("/")
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="creek_modeling",
            protocol=mqtt.MQTTv311,
        )
        if user:
            self._client.username_pw_set(user, password)
        self._host, self._port = host, port
        self._cmd_queue: CommandQueue | None = None
        self._client.on_connect = self._on_connect

    # --- lifecycle -------------------------------------------------------
    def connect(self) -> None:
        log.info("Connecting to MQTT %s:%s", self._host, self._port)
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    # --- publish ---------------------------------------------------------
    def publish(self, name: str, payload: dict, retain: bool = True) -> None:
        topic = f"{self._base}/{name}"
        self._client.publish(topic, json.dumps(payload), qos=1, retain=retain)
        log.debug("Published %s -> %s", topic, payload)

    # --- subscribe (commands) -------------------------------------------
    def subscribe_commands(self, cmd_queue: CommandQueue) -> None:
        """Route `<base>/cmd/<name>` messages onto `cmd_queue`. The actual broker
        subscription happens in `_on_connect` so it survives reconnects; call this
        before `connect()`."""
        self._cmd_queue = cmd_queue
        self._client.on_message = self._on_message

    @property
    def _cmd_topic(self) -> str:
        return f"{self._base}/cmd/#"

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        log.info("MQTT connected (rc=%s)", reason_code)
        if self._cmd_queue is not None:
            self._client.subscribe(self._cmd_topic, qos=1)
            log.info("Subscribed to %s", self._cmd_topic)

    def _on_message(self, _client, _userdata, msg: mqtt.MQTTMessage) -> None:
        command = CommandQueue.command_from_topic(msg.topic)
        if command is None:
            return
        log.info("Command received on %s -> %s", msg.topic, command)
        if self._cmd_queue is not None:
            self._cmd_queue.offer(command)
