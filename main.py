#!/usr/bin/env python3
"""
AprilTag Finder with Bluetooth Guidance
Detects AprilTags and sends direction guidance via Bluetooth
"""

from picamera2 import Picamera2
import cv2
from dt_apriltags import Detector
import time

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
        self.hysteresis = self.frame_width // 5  # pixels

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
        Returns: 1 (left), 2 (little left), 3 (center), 4 (little right), 5 (right)
        """
        return tag_center_x // self.hysteresis + 1

    def format_direction(self, direction):
        """Format message to send in console"""
        arr = ["LEFT", "LITTLE LEFT", "CENTER", "LITTLE RIGHT", "RIGHT"]
        return arr[direction - 1]

    def send_bluetooth_update(self, message):
        """Send update via Bluetooth if enough time has passed"""
        current_time = time.time()
        if current_time - self.last_ble_update >= self.ble_update_interval:
            if self.ble_server:
                self.ble_server.send(message)
            self.last_ble_update = current_time

    def run(self):
        """Main loop"""
        print("\n" + "=" * 50)
        print("AprilTag Finder Started!")
        print("=" * 50)
        print(f"Camera resolution: {self.frame_width}x{self.frame_height}")
        print(f"Hysteresis: {self.hysteresis} pixels")
        print(f"Bluetooth: {'Enabled' if self.use_bluetooth else 'Disabled'}")
        print("\nPress Ctrl+C to quit")
        print("=" * 50 + "\n")

        self.camera.start()

        try:
            while True:
                # Capture frame
                frame = self.camera.capture_array()

                # Convert to grayscale for detection
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

                # Detect AprilTags
                tags = self.detector.detect(gray)

                # Process first detected tag (you could handle multiple)
                if tags:
                    tag = tags[0]  # Use first tag
                    center_x = int(tag.center[0])
                    direction = self.calculate_direction(center_x)


                    if direction != self.last_direction:
                        # Console output
                        print(self.format_direction(direction))
                        self.last_direction = direction
                        # Bluetooth update
                        if self.use_bluetooth:
                            self.send_bluetooth_update(f"{self.format_direction(direction)}")
                else:
                    # No tag detected
                    if self.last_direction != 0:
                        # Console output
                        print("NO TAG")
                        self.last_direction = 0
                        # Bluetooth update
                        if self.use_bluetooth:
                            self.send_bluetooth_update(f"NO TAG")

                # Small delay to prevent CPU spinning
                time.sleep(0.01)

        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        print("Cleaning up...")
        self.camera.stop()
        print("Camera stopped")
        if self.ble_server:
            self.ble_server.stop()
        print("Done!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='AprilTag Finder with Bluetooth')
    parser.add_argument('--no-bluetooth', action='store_true',
                        help='Disable Bluetooth')
    args = parser.parse_args()

    finder = Main(use_bluetooth=not args.no_bluetooth)
    finder.run()


if __name__ == "__main__":
    main()