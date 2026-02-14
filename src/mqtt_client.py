import asyncio
import json
import logging
from typing import Callable

import aiomqtt

logger = logging.getLogger(__name__)


class MqttClient:
    def __init__(self, broker: str, port: int, client_id: str, topic_prefix: str):
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.topic_prefix = topic_prefix
        self._client: aiomqtt.Client | None = None
        self._handlers: dict[str, Callable] = {}
        self._connected = asyncio.Event()

    def on_topic(self, pattern: str, handler: Callable):
        self._handlers[pattern] = handler

    async def connect(self):
        will = aiomqtt.Will(
            topic=f"{self.topic_prefix}/status",
            payload="offline",
            qos=1,
            retain=True,
        )
        self._client = aiomqtt.Client(
            hostname=self.broker,
            port=self.port,
            identifier=self.client_id,
            will=will,
        )

    async def run(self):
        retry_delay = 1
        max_delay = 30

        while True:
            try:
                await self.connect()
                async with self._client:
                    logger.info("MQTT connected to %s:%d", self.broker, self.port)
                    self._connected.set()
                    retry_delay = 1

                    await self._client.publish(
                        f"{self.topic_prefix}/status",
                        payload="online",
                        qos=1,
                        retain=True,
                    )

                    for pattern in self._handlers:
                        await self._client.subscribe(pattern)
                        logger.info("Subscribed to %s", pattern)

                    async for message in self._client.messages:
                        topic_str = str(message.topic)
                        payload = message.payload
                        if isinstance(payload, bytes):
                            payload = payload.decode("utf-8", errors="replace")

                        for pattern, handler in self._handlers.items():
                            if aiomqtt.Topic(topic_str).matches(pattern):
                                try:
                                    await handler(topic_str, payload)
                                except Exception:
                                    logger.exception(
                                        "Handler error for topic %s", topic_str
                                    )

            except aiomqtt.MqttError as e:
                self._connected.clear()
                logger.warning(
                    "MQTT connection lost: %s — retrying in %ds", e, retry_delay
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)

    async def publish(self, topic: str, payload, qos: int = 0, retain: bool = False):
        await self._connected.wait()
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        await self._client.publish(topic, payload=payload, qos=qos, retain=retain)

    async def publish_state(self, key: str, value):
        await self.publish(
            f"{self.topic_prefix}/state/{key}", str(value), qos=1, retain=True
        )

    async def publish_inverter_state(self, idx: int, key: str, value):
        await self.publish(
            f"{self.topic_prefix}/state/inverter/{idx}/{key}",
            str(value),
            qos=1,
            retain=True,
        )
