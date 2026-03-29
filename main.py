#!/usr/bin/env python3
"""
AprilTag Finder with Bluetooth Guidance
Detects AprilTags and sends direction guidance via Bluetooth
"""

from picamera2 import Picamera2
from dt_apriltags import Detector

# Try to import BLE - we'll handle if it fails
try:
    from ble_service import BLEServer
    BLE_AVAILABLE = True
except ImportError as e:
    BLE_AVAILABLE = False
    print(f"BLE not available - running in camera-only mode: {e}")


class Main:
    def __init__(self, use_bluetooth=True):
        self.detector = None
        self.use_bluetooth = use_bluetooth and BLE_AVAILABLE

        # Camera setup
        print("Initializing camera...")
        self.camera = Picamera2()
        config = self.camera.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        self.camera.configure(config)

        print("Starting detector...")
        self.detector = Detector(
            families="tag36h11",
            nthreads=4,
            quad_decimate=1.0,
            quad_sigma=0.0,
            refine_edges=1,
            decode_sharpening=0.25,
            debug=0
        )

        # Frame dimensions
        self.frame_width = 640
        self.frame_height = 480
        self.center_x = self.frame_width // 2

        # Dead zone (how close to center is "good enough")
        self.dead_zone = 50  # pixels

        # Bluetooth
        self.ble_server = None
        if self.use_bluetooth:
            print("Initializing Bluetooth...")
            try:
                self.ble_server = BLEServer()
                self.ble_server.start()
            except Exception as e:
                print(f"Bluetooth init failed: {e}")
                self.use_bluetooth = False

        # Rate limiting for BLE updates
        self.last_ble_update = 0
        self.ble_update_interval = 0.1  # 100ms between updates

        # Last known state
        self.last_direction = None

    def calculate_direction(self, tag_center_x):
        """
        Calculate which direction to move based on tag position
        Returns: (direction_string, offset_value)
        """
        offset = tag_center_x - self.center_x

        if abs(offset) <= self.dead_zone:
            return "CENTERED", offset
        elif offset < 0:
            return "LEFT", offset
        else:
            return "RIGHT", offset

    def format_message(self, direction, offset, tag_id):
        """Format message to send via Bluetooth"""
        #