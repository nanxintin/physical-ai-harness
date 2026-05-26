#!/usr/bin/env python3
"""Minimal MQTT broker for testing (MQTT 3.1.1 subset).

Supports: CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT.
No persistence, no retained messages, no will messages.
Good enough for integration testing with paho-mqtt clients.

Usage:
    python tests/mini_mqtt_broker.py [--port 1883]
"""

from __future__ import annotations

import asyncio
import struct
import sys
from typing import Any


def _decode_remaining_length(data: bytes, offset: int) -> tuple[int, int]:
    multiplier = 1
    value = 0
    idx = offset
    while True:
        encoded_byte = data[idx]
        value += (encoded_byte & 0x7F) * multiplier
        idx += 1
        if (encoded_byte & 0x80) == 0:
            break
        multiplier *= 128
    return value, idx


def _encode_remaining_length(length: int) -> bytes:
    result = bytearray()
    while True:
        encoded_byte = length % 128
        length = length // 128
        if length > 0:
            encoded_byte |= 0x80
        result.append(encoded_byte)
        if length == 0:
            break
    return bytes(result)


def _read_utf8_string(data: bytes, offset: int) -> tuple[str, int]:
    str_len = struct.unpack("!H", data[offset:offset + 2])[0]
    offset += 2
    s = data[offset:offset + str_len].decode("utf-8", errors="replace")
    return s, offset + str_len


class MiniMQTTBroker:
    """Minimal async MQTT broker."""

    def __init__(self, host: str = "0.0.0.0", port: int = 1883):
        self._host = host
        self._port = port
        self._clients: dict[str, _ClientSession] = {}
        self._subscriptions: dict[str, list[_ClientSession]] = {}  # topic -> clients
        self._server: asyncio.Server | None = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )
        return self

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for client in list(self._clients.values()):
            client.writer.close()

    def _match_topic(self, subscription: str, topic: str) -> bool:
        """Simple topic matching with + and # wildcards."""
        sub_parts = subscription.split("/")
        topic_parts = topic.split("/")

        i = 0
        for i, sp in enumerate(sub_parts):
            if sp == "#":
                return True
            if i >= len(topic_parts):
                return False
            if sp == "+":
                continue
            if sp != topic_parts[i]:
                return False

        return i + 1 == len(topic_parts)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        session = _ClientSession(reader, writer, self)
        try:
            await session.run()
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._remove_client(session)

    def _remove_client(self, session: _ClientSession):
        if session.client_id and session.client_id in self._clients:
            del self._clients[session.client_id]
        for topic in list(self._subscriptions.keys()):
            if session in self._subscriptions[topic]:
                self._subscriptions[topic].remove(session)
                if not self._subscriptions[topic]:
                    del self._subscriptions[topic]

    def publish(self, topic: str, payload: bytes, qos: int = 0):
        """Distribute a PUBLISH to all matching subscribers."""
        for sub_topic, clients in self._subscriptions.items():
            if self._match_topic(sub_topic, topic):
                for client in clients:
                    client.send_publish(topic, payload, qos)


class _ClientSession:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, broker: MiniMQTTBroker):
        self.reader = reader
        self.writer = writer
        self.broker = broker
        self.client_id: str = ""
        self._packet_id_counter = 0

    async def run(self):
        while True:
            header_byte = await self.reader.readexactly(1)
            packet_type = (header_byte[0] >> 4) & 0x0F
            flags = header_byte[0] & 0x0F

            remaining_length, consumed = await self._read_remaining_length()
            payload = await self.reader.readexactly(remaining_length) if remaining_length > 0 else b""

            if packet_type == 1:  # CONNECT
                await self._handle_connect(payload)
            elif packet_type == 3:  # PUBLISH
                await self._handle_publish(flags, payload)
            elif packet_type == 8:  # SUBSCRIBE
                await self._handle_subscribe(payload)
            elif packet_type == 12:  # PINGREQ
                self._send_pingresp()
            elif packet_type == 14:  # DISCONNECT
                break

    async def _read_remaining_length(self) -> tuple[int, int]:
        multiplier = 1
        value = 0
        consumed = 0
        while True:
            byte_data = await self.reader.readexactly(1)
            encoded_byte = byte_data[0]
            value += (encoded_byte & 0x7F) * multiplier
            consumed += 1
            if (encoded_byte & 0x80) == 0:
                break
            multiplier *= 128
        return value, consumed

    async def _handle_connect(self, payload: bytes):
        offset = 0
        # Protocol name
        _, offset = _read_utf8_string(payload, offset)
        # Protocol level
        offset += 1  # protocol level byte
        # Connect flags
        offset += 1
        # Keep alive
        offset += 2
        # Client ID
        self.client_id, offset = _read_utf8_string(payload, offset)

        self.broker._clients[self.client_id] = self

        # CONNACK: session present=0, return code=0
        connack = bytes([0x20, 0x02, 0x00, 0x00])
        self.writer.write(connack)
        await self.writer.drain()

    async def _handle_publish(self, flags: int, payload: bytes):
        qos = (flags >> 1) & 0x03
        offset = 0
        topic, offset = _read_utf8_string(payload, offset)

        packet_id = None
        if qos > 0:
            packet_id = struct.unpack("!H", payload[offset:offset + 2])[0]
            offset += 2

        msg_payload = payload[offset:]

        # Distribute to subscribers
        self.broker.publish(topic, msg_payload, qos)

        # PUBACK for QoS 1
        if qos == 1 and packet_id is not None:
            puback = struct.pack("!BBH", 0x40, 0x02, packet_id)
            self.writer.write(puback)
            await self.writer.drain()

    async def _handle_subscribe(self, payload: bytes):
        offset = 0
        packet_id = struct.unpack("!H", payload[offset:offset + 2])[0]
        offset += 2

        granted_qos = []
        while offset < len(payload):
            topic, offset = _read_utf8_string(payload, offset)
            req_qos = payload[offset]
            offset += 1

            if topic not in self.broker._subscriptions:
                self.broker._subscriptions[topic] = []
            if self not in self.broker._subscriptions[topic]:
                self.broker._subscriptions[topic].append(self)

            granted_qos.append(min(req_qos, 1))

        # SUBACK
        suback = struct.pack("!BBH", 0x90, 2 + len(granted_qos), packet_id)
        suback += bytes(granted_qos)
        self.writer.write(suback)
        await self.writer.drain()

    def _send_pingresp(self):
        self.writer.write(bytes([0xD0, 0x00]))
        asyncio.ensure_future(self.writer.drain())

    def send_publish(self, topic: str, payload: bytes, qos: int = 0):
        topic_bytes = topic.encode("utf-8")
        variable_header = struct.pack("!H", len(topic_bytes)) + topic_bytes

        if qos > 0:
            self._packet_id_counter += 1
            variable_header += struct.pack("!H", self._packet_id_counter)

        remaining = variable_header + payload
        first_byte = 0x30 | ((qos & 0x03) << 1)
        packet = bytes([first_byte]) + _encode_remaining_length(len(remaining)) + remaining

        try:
            self.writer.write(packet)
            asyncio.ensure_future(self.writer.drain())
        except (ConnectionResetError, BrokenPipeError):
            pass


async def run_broker(port: int = 1883):
    broker = MiniMQTTBroker(port=port)
    await broker.start()
    print(f"Mini MQTT Broker running on port {port}")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await broker.stop()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1883
    asyncio.run(run_broker(port))
