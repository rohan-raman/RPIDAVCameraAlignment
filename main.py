#!/usr/bin/env python3
"""
AprilTag Finder with Bluetooth Guidance
Detects AprilTags and sends direction guidance via Bluetooth
"""

from picamera2 import Picamera2
from libcamera import controls
from dt_apriltags import Detector
import cv2
import time

# Try to import BLE - we'll handle if it fails
try:
    from ble_service import BLEServer
    BLE_AVAILABLE = True
except ImportError as e:
    BLE_AVAILABLE = False
    print(f"BLE not available - running in camera-only mode: {e}")

class Main:

    DIRECTION_MAP = [
        None,          # 0 (unused)
        "FAR LEFT",    # 1
        "FAR LEFT",    # 2
        "FAR LEFT",    # 3
        "FAR LEFT",    # 4
        "FAR LEFT",    # 5
        "LEFT",        # 6
        "LEFT",        # 7
        "LEFT",        # 8
        "SLIGHTLY LEFT",  # 9
        "SLIGHTLY LEFT",  # 10
        "5 LEFT",      # 11
        "CENTER",      # 12
        "5 RIGHT",     # 13
        "SLIGHTLY RIGHT", # 14
        "SLIGHTLY RIGHT", # 15
        "RIGHT",       # 16
        "RIGHT",       # 17
        "RIGHT",       # 18
        "FAR RIGHT",   # 19
        "FAR RIGHT",   # 20
        "FAR RIGHT",   # 21
        "FAR RIGHT",   # 22
        "FAR RIGHT",   # 23
    ]

    def __init__(self, use_bluetooth=True):
        self.detector = None
        self.use_bluetooth = use_bluetooth and BLE_AVAILABLE

        self.frame_width = 1920
        self.frame_height = 1080
        self.center_x = self.frame_width // 2

        # Camera setup
        print("Initializing camera...")
        self.camera = Picamera2()
        config = self.camera.create_preview_configuration(
            main={"size": (self.frame_width, self.frame_height)}
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


        # Dead zone (how close to center is "good enough")
        self.hysteresis = self.frame_width // 23  # pixels

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

        # Focus tracking
        self.last_focus_time = 0
        self.focus_interval = 0.5  # Re-focus every 500ms max
        self.last_focus_window = None

    def get_tag_focus_window(self, tag, padding=1.5):
        """
        Calculate a focus window around the detected AprilTag.

        Args:
            tag: Detected AprilTag object
            padding: Multiplier to expand the window (1.5 = 50% larger)

        Returns:
            Tuple (x, y, width, height) normalized to 0-1 range for AfWindows,
            or None if invalid
        """
        # Get the corner points of the tag
        corners = tag.corners

        # Calculate bounding box
        min_x = int(min(c[0] for c in corners))
        max_x = int(max(c[0] for c in corners))
        min_y = int(min(c[1] for c in corners))
        max_y = int(max(c[1] for c in corners))

        # Calculate dimensions with padding
        tag_width = max_x - min_x
        tag_height = max_y - min_y

        pad_x = int(tag_width * (padding - 1) / 2)
        pad_y = int(tag_height * (padding - 1) / 2)

        # Apply padding and clamp to frame bounds
        x1 = max(0, min_x - pad_x)
        y1 = max(0, min_y - pad_y)
        x2 = min(self.frame_width, max_x + pad_x)
        y2 = min(self.frame_height, max_y + pad_y)

        width = x2 - x1
        height = y2 - y1

        # Return as pixel coordinates (for AfWindows)
        return (x1, y1, width, height)

    def focus_on_tag(self, tag):
        """
        Set the camera's autofocus window to the AprilTag location.
        """
        current_time = time.time()

        # Rate limit focus changes
        if current_time - self.last_focus_time < self.focus_interval:
            return

        focus_window = self.get_tag_focus_window(tag)

        if focus_window is None:
            return

        # Only update if window has changed significantly
        if self.last_focus_window is not None:
            old = self.last_focus_window
            # Check if window moved more than 10% of frame
            if (abs(focus_window[0] - old[0]) < self.frame_width * 0.1 and
                    abs(focus_window[1] - old[1]) < self.frame_height * 0.1):
                return

        try:
            # Set the autofocus window to the tag region
            self.camera.set_controls({
                "AfMode": controls.AfModeEnum.Continuous,
                "AfMetering": controls.AfMeteringEnum.Windows,
                "AfWindows": [focus_window]
            })

            self.last_focus_window = focus_window
            self.last_focus_time = current_time

            print(f"  [Focus] Window set to: {focus_window}")

        except Exception as e:
            print(f"  [Focus] Error setting focus window: {e}")

    def reset_focus_to_center(self):
        """Reset focus to center of frame when no tag is detected."""
        current_time = time.time()

        if current_time - self.last_focus_time < self.focus_interval:
            return

        if self.last_focus_window is None:
            return  # Already reset

        try:
            # Reset to auto metering (whole frame)
            self.camera.set_controls({
                "AfMode": controls.AfModeEnum.Continuous,
                "AfMetering": controls.AfMeteringEnum.Auto
            })

            self.last_focus_window = None
            self.last_focus_time = current_time

            print("  [Focus] Reset to auto")

        except Exception as e:
            print(f"  [Focus] Error resetting focus: {e}")

    def calculate_direction(self, tag_center_x):
        """
        Calculate which direction to move based on tag position
        Returns: 
            1, 2, 3, 4, 5 - far left
            6, 7, 8 - left
            9, 10 - slightly left
            11 - hole is less than 5 degrees left (5 left)
            12 (center)
            13 - hole is less than 5 degrees right (5 right)
            14, 15 - slightly right
            16, 17, 18 - right
            19, 20, 21, 22, 23 - far right
        """
        return tag_center_x // self.hysteresis + 1

    def format_direction(self, direction):
        """Format message to send in console"""
        return self.DIRECTION_MAP[direction]

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
        self.camera.set_controls({
            "AfMode": controls.AfModeEnum.Continuous,
            "AfSpeed": controls.AfSpeedEnum.Fast
        })

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
                    # Use the largest tag (most likely closest/most important)
                    tag = max(tags, key=lambda t: self._tag_area(t))

                    center_x = int(tag.center[0])
                    direction = self.calculate_direction(center_x)

                    # Focus on the detected tag
                    self.focus_on_tag(tag)

                    if direction != self.last_direction:
                        # Console output
                        print(self.format_direction(direction))
                        self.last_direction = direction
                        # Bluetooth update
                        if self.use_bluetooth:
                            self.send_bluetooth_update(f"{self.format_direction(direction)}")
                else:
                    # No tag detected - reset focus
                    self.reset_focus_to_center()

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

    def _tag_area(self, tag):
        """Calculate approximate area of a tag (for sorting by size)."""
        corners = tag.corners
        # Shoelace formula for polygon area
        n = len(corners)
        area = 0
        for i in range(n):
            j = (i + 1) % n
            area += corners[i][0] * corners[j][1]
            area -= corners[j][0] * corners[i][1]
        return abs(area) / 2

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