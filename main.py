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
except ImportError:
    BLE_AVAILABLE = False
    print("BLE not available - running in camera-only mode")


class Main:
    def __init__(self, use_bluetooth=True, show_video=True):
        self.detector = None
        self.show_video = show_video
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
        # Format: DIRECTION:OFFSET:TAG_ID
        return f"{direction}:{offset}:{tag_id}"

    def send_bluetooth_update(self, message):
        """Send update via Bluetooth if enough time has passed"""
        current_time = time.time()
        if current_time - self.last_ble_update >= self.ble_update_interval:
            if self.ble_server:
                self.ble_server.send_direction(message)
            self.last_ble_update = current_time

    def draw_overlay(self, frame, tags):
        """Draw visual overlay on the frame"""
        # Draw center line
        cv2.line(frame,
                 (self.center_x, 0),
                 (self.center_x, self.frame_height),
                 (100, 100, 100), 1)

        # Draw dead zone
        cv2.rectangle(frame,
                      (self.center_x - self.dead_zone, 0),
                      (self.center_x + self.dead_zone, self.frame_height),
                      (0, 100, 0), 1)

        for tag in tags:
            # Draw tag outline
            corners = tag.corners.astype(int)
            for i in range(4):
                cv2.line(frame,
                         tuple(corners[i]),
                         tuple(corners[(i + 1) % 4]),
                         (0, 255, 0), 2)

            # Draw center point
            center_x = int(tag.center[0])
            center_y = int(tag.center[1])
            cv2.circle(frame, (center_x, center_y), 8, (0, 0, 255), -1)

            # Draw line from frame center to tag center
            cv2.line(frame,
                     (self.center_x, self.frame_height // 2),
                     (center_x, center_y),
                     (255, 255, 0), 2)

            # Calculate and display direction
            direction, offset = self.calculate_direction(center_x)

            # Color based on direction
            if direction == "CENTERED":
                color = (0, 255, 0)  # Green
                arrow = "✓"
            elif direction == "LEFT":
                color = (0, 165, 255)  # Orange
                arrow = "← ← ←"
            else:
                color = (0, 165, 255)  # Orange
                arrow = "→ → →"

            # Display info
            cv2.putText(frame, f"Tag ID: {tag.tag_id}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"{arrow} {direction}",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.putText(frame, f"Offset: {offset:+d} px",
                        (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        if len(tags) == 0:
            cv2.putText(frame, "NO TAG DETECTED",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.putText(frame, "Searching...",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128, 128, 128), 2)

        # BLE status
        ble_status = "BLE: Connected" if self.use_bluetooth else "BLE: Off"
        cv2.putText(frame, ble_status,
                    (10, self.frame_height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)

        return frame

    def run(self):
        """Main loop"""
        print("\n" + "=" * 50)
        print("AprilTag Finder Started!")
        print("=" * 50)
        print(f"Camera resolution: {self.frame_width}x{self.frame_height}")
        print(f"Dead zone: ±{self.dead_zone} pixels")
        print(f"Bluetooth: {'Enabled' if self.use_bluetooth else 'Disabled'}")
        print("\nPress 'q' to quit")
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
                    direction, offset = self.calculate_direction(center_x)

                    # Send Bluetooth update
                    if self.use_bluetooth:
                        message = self.format_message(direction, offset, tag.tag_id)
                        self.send_bluetooth_update(message)

                    # Console output (rate limited)
                    if direction != self.last_direction:
                        print(f"Tag {tag.tag_id}: {direction} (offset: {offset:+d})")
                        self.last_direction = direction
                else:
                    # No tag detected
                    if self.use_bluetooth:
                        self.send_bluetooth_update("NO_TAG:0:0")
                    if self.last_direction != "NO_TAG":
                        print("No tag detected")
                        self.last_direction = "NO_TAG"

                # Show video if enabled
                if self.show_video:
                    display_frame = self.draw_overlay(frame.copy(), tags)
                    cv2.imshow("AprilTag Finder", display_frame)

                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                else:
                    # Small delay when not showing video
                    time.sleep(0.01)

        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        print("Cleaning up...")
        self.camera.stop()
        if self.show_video:
            cv2.destroyAllWindows()
        if self.ble_server:
            self.ble_server.stop()
        print("Done!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='AprilTag Finder with Bluetooth')
    parser.add_argument('--no-bluetooth', action='store_true',
                        help='Disable Bluetooth')
    parser.add_argument('--no-video', action='store_true',
                        help='Disable video display (headless mode)')
    args = parser.parse_args()

    finder = Main(
        use_bluetooth=not args.no_bluetooth,
        show_video=not args.no_video
    )
    finder.run()


if __name__ == "__main__":
    main()