#!/usr/bin/env python3
"""
BLE Service using bless library
Provides a GATT server for AprilTag direction data
"""

import asyncio
import threading
from typing import Any
from bless import (
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions,
)

# Custom UUIDs for our service
APRILTAG_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
DIRECTION_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"

DEVICE_NAME = "DAV Camera Alignment"


class BLEServer:
    def __init__(self):
        self.server: BlessServer = None
        self.loop: asyncio.AbstractEventLoop = None
        self._thread: threading.Thread = None
        self._running = False
        self._current_value = bytearray(b"NO_TAG:0:0")

    def _read_request(self, characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
        """Handle read requests from connected clients"""
        print(f"ReadValue called, returning: {self._current_value}")
        return self._current_value

    def _write_request(self, characteristic: BlessGATTCharacteristic, value: Any, **kwargs):
        """Handle write requests (not used in this application)"""
        print(f"WriteValue called with: {value}")

    async def _setup_server(self):
        """Set up the BLE GATT server"""
        self.server = BlessServer(name=DEVICE_NAME, loop=self.loop)
        self.server.read_request_func = self._read_request
        self.server.write_request_func = self._write_request

        await self.server.add_new_service(APRILTAG_SERVICE_UUID)

        # Add direction characteristic with read and notify
        char_flags = (
            GATTCharacteristicProperties.read |
            GATTCharacteristicProperties.notify
        )
        permissions = (
            GATTAttributePermissions.readable
        )

        await self.server.add_new_characteristic(
            APRILTAG_SERVICE_UUID,
            DIRECTION_CHAR_UUID,
            char_flags,
            self._current_value,
            permissions,
        )

        print(f"Service {APRILTAG_SERVICE_UUID} added")
        print(f"Characteristic {DIRECTION_CHAR_UUID} added")

        await self.server.start()

        print("\n" + "=" * 40)
        print("BLE Server started!")
        print(f"Device name: {DEVICE_NAME}")
        print("=" * 40 + "\n")

    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._setup_server())
            self._running = True
            self.loop.run_forever()
        except Exception as e:
            print(f"Event loop error: {e}")
        finally:
            self._running = False

    def start(self):
        """Start the BLE server in a background thread"""
        print("Starting BLE server...")
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

        # Wait for server to be ready
        import time
        timeout = 5.0
        start_time = time.time()
        while not self._running and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        if not self._running:
            raise Exception("BLE server failed to start within timeout")

        print("BLE server started successfully")

    def send_direction(self, direction: str):
        """Send direction update to connected clients via notification"""
        if not self._running or not self.server:
            return

        if isinstance(direction, str):
            self._current_value = bytearray(direction.encode('utf-8'))
        else:
            self._current_value = bytearray(direction)

        # Schedule the notification on the event loop
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._send_notification(),
                self.loop
            )

    async def _send_notification(self):
        """Send notification to subscribed clients"""
        try:
            self.server.get_characteristic(DIRECTION_CHAR_UUID)
            self.server.update_value(
                APRILTAG_SERVICE_UUID,
                DIRECTION_CHAR_UUID
            )
        except Exception as e:
            # Silently ignore notification errors (e.g., no clients connected)
            pass

    def stop(self):
        """Stop the BLE server"""
        print("Stopping BLE server...")
        if self.loop and self.loop.is_running():
            # Schedule server stop
            async def _stop():
                if self.server:
                    await self.server.stop()

            future = asyncio.run_coroutine_threadsafe(_stop(), self.loop)
            try:
                future.result(timeout=2.0)
            except:
                pass

            self.loop.call_soon_threadsafe(self.loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._running = False
        print("BLE server stopped")


# Test if run directly
if __name__ == '__main__':
    import time

    server = BLEServer()
    try:
        server.start()
        print("BLE server running. Press Ctrl+C to stop")
        print("Sending test messages every 2 seconds...")

        counter = 0
        directions = ["LEFT:-100:1", "CENTERED:0:1", "RIGHT:100:1", "NO_TAG:0:0"]

        while True:
            msg = directions[counter % len(directions)]
            print(f"Sending: {msg}")
            server.send_direction(msg)
            counter += 1
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.stop()