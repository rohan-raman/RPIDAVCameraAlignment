from pydbus import SystemBus
from pydbus.generic import signal
from gi.repository import GLib
import threading
import time

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

# Custom UUIDs for our service
APRILTAG_SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
DIRECTION_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'

# Base path for all our objects (NOT root!)
APP_PATH = '/org/bluez/example'


class Advertisement:
    """
    <node>
        <interface name='org.bluez.LEAdvertisement1'>
            <method name='Release'/>
            <property name='Type' type='s' access='read'/>
            <property name='LocalName' type='s' access='read'/>
            <property name='ServiceUUIDs' type='as' access='read'/>
        </interface>
    </node>
    """

    def __init__(self, index):
        self.path = APP_PATH + '/advertisement' + str(index)

    @property
    def Type(self):
        return 'peripheral'

    @property
    def LocalName(self):
        return 'AprilTagFinder'

    @property
    def ServiceUUIDs(self):
        return [APRILTAG_SERVICE_UUID]

    def Release(self):
        print('Advertisement released')


class DirectionCharacteristic:
    """
    <node>
        <interface name='org.bluez.GattCharacteristic1'>
            <method name='ReadValue'>
                <arg name='options' type='a{sv}' direction='in'/>
                <arg name='value' type='ay' direction='out'/>
            </method>
            <method name='StartNotify'/>
            <method name='StopNotify'/>
            <property name='Service' type='o' access='read'/>
            <property name='UUID' type='s' access='read'/>
            <property name='Flags' type='as' access='read'/>
        </interface>
    </node>
    """

    PropertiesChanged = signal()

    def __init__(self, index, service_path):
        self.path = service_path + '/char' + str(index)
        self._service_path = service_path
        self._value = [0]
        self.notifying = False

    @property
    def Service(self):
        return self._service_path

    @property
    def UUID(self):
        return DIRECTION_CHAR_UUID

    @property
    def Flags(self):
        return ['read', 'notify']

    def ReadValue(self, options):
        print(f"ReadValue called, returning: {self._value}")
        return self._value

    def StartNotify(self):
        self.notifying = True
        print("Notifications started")

    def StopNotify(self):
        self.notifying = False
        print("Notifications stopped")

    def set_value(self, value):
        if isinstance(value, str):
            self._value = [ord(b) for b in value]
        else:
            self._value = list(value)

    def notify(self, value):
        if self.notifying:
            if isinstance(value, str):
                self._value = [ord(b) for b in value]
            else:
                self._value = list(value)
            self.PropertiesChanged(
                GATT_CHRC_IFACE,
                {'Value': GLib.Variant('ay', self._value)},
                []
            )


class AprilTagService:
    """
    <node>
        <interface name='org.bluez.GattService1'>
            <property name='UUID' type='s' access='read'/>
            <property name='Primary' type='b' access='read'/>
        </interface>
    </node>
    """

    def __init__(self, index):
        self.path = APP_PATH + '/service' + str(index)
        self.direction_char = DirectionCharacteristic(0, self.path)

    @property
    def UUID(self):
        return APRILTAG_SERVICE_UUID

    @property
    def Primary(self):
        return True


class Application:
    """
    <node>
        <interface name='org.freedesktop.DBus.ObjectManager'>
            <method name='GetManagedObjects'>
                <arg name='objects' type='a{oa{sa{sv}}}' direction='out'/>
            </method>
        </interface>
    </node>
    """

    def __init__(self):
        self.path = APP_PATH  # FIX: Not root '/', use our base path
        self.services = []

    def add_service(self, service):
        self.services.append(service)

    def GetManagedObjects(self):
        print("GetManagedObjects called by BlueZ")
        response = {}
        for service in self.services:
            # Add service properties (removed Characteristics property)
            response[service.path] = {
                GATT_SERVICE_IFACE: {
                    'UUID': GLib.Variant('s', service.UUID),
                    'Primary': GLib.Variant('b', service.Primary),
                }
            }
            # Add characteristic properties
            char = service.direction_char
            response[char.path] = {
                GATT_CHRC_IFACE: {
                    'Service': GLib.Variant('o', char.Service),
                    'UUID': GLib.Variant('s', char.UUID),
                    'Flags': GLib.Variant('as', char.Flags),
                }
            }
        return response


class BLEServer:
    def __init__(self):
        self.bus = None
        self.mainloop = None
        self.app = None
        self.service = None
        self.advertisement = None
        self._registrations = []
        self._adapter_path = None

    def find_adapter(self):
        bluez = self.bus.get(BLUEZ_SERVICE_NAME, '/')
        om = bluez[DBUS_OM_IFACE]
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if GATT_MANAGER_IFACE in interfaces:
                return path
        return None

    def start(self):
        self.bus = SystemBus()

        self._adapter_path = self.find_adapter()
        if not self._adapter_path:
            raise Exception('BLE adapter not found')

        print(f"Using adapter: {self._adapter_path}")

        # Power on the adapter and set name
        adapter = self.bus.get(BLUEZ_SERVICE_NAME, self._adapter_path)
        adapter_props = adapter['org.freedesktop.DBus.Properties']
        adapter_props.Set('org.bluez.Adapter1', 'Powered', GLib.Variant('b', True))
        adapter_props.Set('org.bluez.Adapter1', 'Alias', GLib.Variant('s', 'AprilTagFinder'))
        adapter_props.Set('org.bluez.Adapter1', 'Discoverable', GLib.Variant('b', True))
        print("Adapter powered on and configured")

        # Create application and service
        self.app = Application()
        self.service = AprilTagService(0)
        self.app.add_service(self.service)

        # Create advertisement
        self.advertisement = Advertisement(0)

        # Register all objects on the bus FIRST
        print("Registering D-Bus objects...")
        self._registrations.append(
            self.bus.register_object(self.app.path, self.app, None)
        )
        self._registrations.append(
            self.bus.register_object(self.service.path, self.service, None)
        )
        self._registrations.append(
            self.bus.register_object(
                self.service.direction_char.path,
                self.service.direction_char,
                None
            )
        )
        self._registrations.append(
            self.bus.register_object(self.advertisement.path, self.advertisement, None)
        )
        print("D-Bus objects registered")

        # FIX: Start main loop BEFORE registering with BlueZ
        print("Starting GLib main loop...")
        self.mainloop = GLib.MainLoop()
        thread = threading.Thread(target=self.mainloop.run, daemon=True)
        thread.start()
        time.sleep(0.1)  # Give loop time to start

        # Now register with BlueZ
        print("Registering GATT application with BlueZ...")
        gatt_manager = self.bus.get(BLUEZ_SERVICE_NAME, self._adapter_path)[GATT_MANAGER_IFACE]
        gatt_manager.RegisterApplication(self.app.path, {})
        print("GATT application registered")

        print("Registering advertisement with BlueZ...")
        ad_manager = self.bus.get(BLUEZ_SERVICE_NAME, self._adapter_path)[LE_ADVERTISING_MANAGER_IFACE]
        ad_manager.RegisterAdvertisement(self.advertisement.path, {})
        print("Advertisement registered")

        print("\n" + "=" * 40)
        print("BLE Server started!")
        print("Device name: AprilTagFinder")
        print("=" * 40 + "\n")

    def send_direction(self, direction):
        """Send direction update to connected phone"""
        if self.service:
            self.service.direction_char.notify(direction)

    def stop(self):
        if self.mainloop:
            self.mainloop.quit()
        # Unregister objects
        for reg in self._registrations:
            try:
                reg.unregister()
            except:
                pass
        self._registrations.clear()


# Test if run directly
if __name__ == '__main__':
    server = BLEServer()
    try:
        server.start()
        print("Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        server.stop()