# bless_server.py - Raspberry Pi BLE Server (modified)

import asyncio
import threading
import logging
from typing import Any
from bless import (
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions,
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# UUIDs
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"

DEVICE_NAME = "PiDataServer"


class BLEServer:
    def __init__(self):
        self.server: BlessServer = None
        self.loop: asyncio.AbstractEventLoop = None
        self.thread: threading.Thread = None
        self.running = False

        # Stored value (what clients read + receive)
        self.current_value = bytearray(b"NO_TAG:0:0")

    # -----------------------
    # Callbacks
    # -----------------------
    def read_request(self, characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
        logger.info(f"Read request -> {self.current_value}")
        return self.current_value

    def write_request(self, characteristic: BlessGATTCharacteristic, value: Any, **kwargs):
        logger.info(f"Write request -> {value}")

    # -----------------------
    # Setup
    # -----------------------
    async def setup(self):
        self.server = BlessServer(name=DEVICE_NAME, loop=self.loop)

        self.server.read_request_func = self.read_request
        self.server.write_request_func = self.write_request

        await self.server.add_new_service(SERVICE_UUID)

        # Single characteristic: READ + NOTIFY
        await self.server.add_new_characteristic(
            SERVICE_UUID,
            CHAR_UUID,
            GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
            self.current_value,
            GATTAttributePermissions.readable,
        )

        await self.server.start()

        logger.info("BLE Server started")
        logger.info(f"Service: {SERVICE_UUID}")
        logger.info(f"Characteristic: {CHAR_UUID}")

    # -----------------------
    # Thread / loop handling
    # -----------------------
    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self.setup())
            self.running = True
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Loop error: {e}")
        finally:
            self.running = False

    def start(self):
        logger.info("Starting BLE server...")

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        # Wait until running
        import time
        start = time.time()
        while not self.running and time.time() - start < 5:
            time.sleep(0.1)

        if not self.running:
            raise RuntimeError("Server failed to start")

        logger.info("Server started successfully")

    # -----------------------
    # Send notifications
    # -----------------------
    def send(self, data: str):
        if not self.running or not self.server:
            return

        self.current_value = bytearray(data.encode("utf-8"))

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._notify(), self.loop)

    async def _notify(self):
        try:
            # Update stored value
            self.server.get_characteristic(CHAR_UUID).value = self.current_value

            # Notify clients
            self.server.update_value(SERVICE_UUID, CHAR_UUID)

            logger.info(f"Notified: {self.current_value}")
        except Exception:
            pass  # Ignore if no clients connected

    # -----------------------
    # Stop
    # -----------------------
    def stop(self):
        logger.info("Stopping server...")

        if self.loop and self.loop.is_running():

            async def _stop():
                if self.server:
                    await self.server.stop()

            future = asyncio.run_coroutine_threadsafe(_stop(), self.loop)
            try:
                future.result(timeout=2)
            except:
                pass

            self.loop.call_soon_threadsafe(self.loop.stop)

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

        self.running = False
        logger.info("Server stopped")


# -----------------------
# Test mode
# -----------------------
if __name__ == "__main__":
    import time

    server = BLEServer()

    try:
        server.start()

        directions = [
            "LEFT:-100:1",
            "CENTERED:0:1",
            "RIGHT:100:1",
            "NO_TAG:0:0"
        ]

        i = 0
        while True:
            msg = directions[i % len(directions)]
            logger.info(f"Sending: {msg}")
            server.send(msg)
            i += 1
            time.sleep(2)

    except KeyboardInterrupt:
        pass
    finally:
        server.stop()