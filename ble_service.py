from pydbus import SystemBus
from pydbus.generic import signal
from gi.repository import GLib
import threading

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
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, index):
        self.path = self.PATH_BASE + str(index)
        self._type = 'peripheral'
        self._local_name = 'AprilTagFinder'
        self._service_uuids = [APRILTAG_SERVICE_UUID]

        self._includes = ['tx-power']  # Include TX Power in adv data
        self._tx_power = 0  # dBm - adjust based on your hardware

        self._min_interval = 32  # 20ms
        self._max_interval = 32  # 20ms

    @property
    def Type(self):
        return self._type

    @property
    def LocalName(self):
        return self._local_name

    @property
    def ServiceUUIDs(self):
        return self._service_uuids

    @property
    def Includes(self):
        """Include tx-power and flags in advertising data"""
        return self._includes

    @property
    def TxPower(self):
        """TX Power Level in dBm"""
        return self._tx_power

    @property
    def MinInterval(self):
        """Minimum advertising interval (units of 0.625ms)"""
        return self._min_interval

    @property
    def MaxInterval(self):
        """Maximum advertising interval (units of 0.625ms)"""
        return self._max_interval

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
            <property name='Value' type='ay' access='read'/>
        </interface>
        <interface name='org.freedesktop.DBus.Properties'>
            <signal name='PropertiesChanged'>
                <arg name='interface' type='s'/>
                <arg name='changed_properties' type='a{sv}'/>
                <arg name='invalidated_properties' type='as'/>
            </signal>
        </interface>
    </node>
    """

    PropertiesChanged = signal()

    def __init__(self, index, service_path):
        self.path = service_path + '/char' + str(index)
        self._service_path = service_path
        self._uuid = DIRECTION_CHAR_UUID
        self._flags = ['read', 'notify']
        self._value = [0]
        self.notifying = False

    @property
    def Service(self):
        return self._service_path

    @property
    def UUID(self):
        return self._uuid

    @property
    def Flags(self):
        return self._flags

    @property
    def Value(self):
        return self._value

    def ReadValue(self, options):
        return self._value

    def StartNotify(self):
        self.notifying = True
        print("Notifications started")

    def StopNotify(self):
        self.notifying = False
        print("Notifications stopped")

    def set_value(self, value):
        self._value = [ord(b) for b in value]

    def notify(self, value):
        if self.notifying:
            self._value = [ord(b) for b in value]
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
            <property name='Characteristics' type='ao' access='read'/>
        </interface>
    </node>
    """
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, index):
        self.path = self.PATH_BASE + str(index)
        self._uuid = APRILTAG_SERVICE_UUID
        self._primary = True
        self.direction_char = DirectionCharacteristic(0, self.path)
        self._characteristics = [self.direction_char.path]

    @property
    def UUID(self):
        return self._uuid

    @property
    def Primary(self):
        return self._primary

    @property
    def Characteristics(self):
        return self._characteristics


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
        self.path = '/'
        self.services = []

    def add_service(self, service):
        self.services.append(service)

    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            # Add service properties
            response[service.path] = {
                GATT_SERVICE_IFACE: {
                    'UUID': GLib.Variant('s', service.UUID),
                    'Primary': GLib.Variant('b', service.Primary),
                    'Characteristics': GLib.Variant('ao', service.Characteristics)
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
        self.bus = SystemBus()
        self.mainloop = None
        self.app = None
        self.service = None
        self.advertisement = None
        self._registrations = []

    def start(self):
        adapter_path = self.find_adapter()
        if not adapter_path:
            raise Exception('BLE adapter not found')

        # Power on the adapter
        adapter = self.bus.get(BLUEZ_SERVICE_NAME, adapter_path)
        adapter_props = adapter['org.freedesktop.DBus.Properties']
        adapter_props.Set('org.bluez.Adapter1', 'Powered', GLib.Variant('b', True))

        # Create application and service
        self.app = Application()
        self.service = AprilTagService(0)
        self.app.add_service(self.service)

        # Register objects on the bus
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

        # Register GATT application
        gatt_manager = self.bus.get(BLUEZ_SERVICE_NAME, adapter_path)[GATT_MANAGER_IFACE]
        gatt_manager.RegisterApplication(self.app.path, {})
        print("GATT application registered")

        # Create and register advertisement
        self.advertisement = Advertisement(0)
        self._registrations.append(
            self.bus.register_object(self.advertisement.path, self.advertisement, None)
        )

        ad_manager = self.bus.get(BLUEZ_SERVICE_NAME, adapter_path)[LE_ADVERTISING_MANAGER_IFACE]
        ad_manager.RegisterAdvertisement(self.advertisement.path, {})
        print("Advertisement registered")

        print("BLE Server started. Device name: AprilTagFinder")

        # Run main loop in a separate thread
        self.mainloop = GLib.MainLoop()
        thread = threading.Thread(target=self.mainloop.run)
        thread.daemon = True
        thread.start()

    def find_adapter(self):
        bluez = self.bus.get(BLUEZ_SERVICE_NAME, '/')
        om = bluez[DBUS_OM_IFACE]
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if GATT_MANAGER_IFACE in interfaces:
                return path
        return None

    def send_direction(self, direction):
        """Send direction update to connected phone"""
        if self.service:
            self.service.direction_char.notify(direction)

    def stop(self):
        if self.mainloop:
            self.mainloop.quit()
        # Unregister objects
        for reg in self._registrations:
            reg.unregister()
        self._registrations.clear()