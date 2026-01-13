import time
import logging
import os
import threading
from logging.handlers import RotatingFileHandler

import pyudev
import serial

from octoprint.plugin import (
    SettingsPlugin,
    EventHandlerPlugin,
    TemplatePlugin,
    StartupPlugin,
    ShutdownPlugin,
)
from octoprint.events import Events

class NullLogger:
    def section(self, *_, **__): pass
    def subsection(self, *_, **__): pass
    def event(self, *_, **__): pass
    def highlight(self, *_, **__): pass
    def info(self, *_, **__): pass
    def debug(self, *_, **__): pass
    def warning(self, *_, **__): pass
    def error(self, *_, **__): pass
    def kv(self, *_, **__): pass

class PluginLogger:
    def __init__(self, logger):
        self._logger = logger

    def section(self, title):
        self._logger.info(f"=== {title} ===")

    def subsection(self, title):
        self._logger.info(f"--- {title} ---")

    def event(self, message):
        self._logger.info(f">> {message} <<")

    def highlight(self, message):
        self._logger.info(f"*** {message} ***")

    def info(self, message):
        self._logger.info(f"{message}")

    def debug(self, message):
        self._logger.debug(f"{message}")

    def warning(self, message):
        self._logger.warning(f"{message}")

    def error(self, message):
        self._logger.error(f"{message}")

    def kv(self, key, value):
        self._logger.info(f"[{key}] {value}")

class ReconnectGuruPlugin(
    SettingsPlugin,
    EventHandlerPlugin,
    TemplatePlugin,
    StartupPlugin,
    ShutdownPlugin,
):
    def __init__(self):
        self._monitor = None
        self._monitor_thread = None
        self._stop_monitoring = False
        self.log = NullLogger()

    # -------------------------------------------------------------------------
    # Initialization / Logging
    # -------------------------------------------------------------------------

    def initialize(self):
        logging_path = os.path.join(
            self._settings.getBaseFolder("logs"),
            "plugin_reconnect_guru.log"
        )

        file_handler = RotatingFileHandler(
            logging_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3
        )

        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        self._logger.addHandler(file_handler)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        self.log = PluginLogger(self._logger)

        self.log.section("ReconnectGuru Plugin Initialized")
        self.log.kv("Log file", logging_path)
        self.print_settings()

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------

    def get_settings_version(self):
        return 1

    def get_settings_defaults(self):
        return dict(
            enabled=True,
            connect_delay_seconds=2,
            filter_vendor_id="",
            filter_product_id="",
            filter_serial="",
            filter_port="",
            message_on_connect=False,
        )

    def on_settings_save(self, data):
        SettingsPlugin.on_settings_save(self, data)

        self.log.section("Settings Saved")
        self.log.info(f"Raw data: {data}")
        self.print_settings()

    def print_settings(self):
        self.log.kv("Enabled", self._settings.get_boolean(["enabled"]))
        self.log.kv(
            "Connect delay",
            f"{self._settings.get_int(['connect_delay_seconds'])} seconds"
        )
        self.log.kv("Filter Vendor ID", self._settings.get(["filter_vendor_id"]) or "(any)")
        self.log.kv("Filter Product ID", self._settings.get(["filter_product_id"]) or "(any)")
        self.log.kv("Filter Serial", self._settings.get(["filter_serial"]) or "(any)")
        self.log.kv("Filter Port", self._settings.get(["filter_port"]) or "(any)")
        self.log.kv(
            "Message (M117) on connect",
            self._settings.get_boolean(["message_on_connect"])
        )

    # -------------------------------------------------------------------------
    # Startup / Shutdown
    # -------------------------------------------------------------------------

    def on_after_startup(self):
        if not self._settings.get_boolean(["enabled"]):
            self.log.info("Plugin disabled, not starting udev monitor")
            return

        self.log.section("Starting udev monitor")
        self._start_udev_monitor()

    def on_shutdown(self):
        self.log.section("Shutting down")
        self._stop_udev_monitor()

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    def on_event(self, event, payload):
        # Log significant events only
        significant_events = {
            Events.CONNECTED,
            Events.DISCONNECTED,
            Events.ERROR,
        }

        if event in significant_events:
            self.log.section(f"Event: {event}")

        if event == Events.CONNECTED:
            self.log.event("Printer connected")
        elif event == Events.DISCONNECTED:
            self.log.event("Printer disconnected")
        elif event == Events.ERROR:
            self.log.event("Printer error")

    # -------------------------------------------------------------------------
    # udev Monitoring
    # -------------------------------------------------------------------------

    def _start_udev_monitor(self):
        """Start the udev monitoring thread"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            self.log.warning("Monitor thread already running")
            return

        self._stop_monitoring = False
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self.log.highlight("udev monitor thread started")

    def _stop_udev_monitor(self):
        """Stop the udev monitoring thread"""
        if not self._monitor_thread:
            return

        self.log.info("Stopping udev monitor")
        self._stop_monitoring = True

        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

        self._monitor = None
        self.log.info("udev monitor stopped")

    def _monitor_loop(self):
        """Main monitoring loop running in separate thread"""
        try:
            context = pyudev.Context()
            self._monitor = pyudev.Monitor.from_netlink(context)
            self._monitor.filter_by(subsystem='tty')

            self.log.info("Listening for USB device add events...")

            for device in iter(self._monitor.poll, None):
                if self._stop_monitoring:
                    break

                if device.action == 'add':
                    self._handle_device_added(device)

        except Exception as e:
            self.log.error(f"Monitor loop error: {e}")

    def _handle_device_added(self, device):
        """Handle a new device being added"""

        if not self._settings.get_boolean(["enabled"]):
            self.log.info("Plugin disabled, skipping reconnection")
            return

        try:
            # Extract device information
            vendor = device.get('ID_VENDOR_ID', 'N/A')
            product = device.get('ID_MODEL_ID', 'N/A')
            serial_num = device.get('ID_SERIAL_SHORT', 'None/Empty')
            usb_path = device.get('ID_PATH', 'N/A')
            device_node = device.device_node

            # Extract port from USB path
            # USB paths follow format: platform-XXXX-usb-BUS:PORT:INTERFACE
            # We want the PORT part (e.g., "1.2" or "1.1.3")
            port = "Unknown"
            if ":" in usb_path:
                try:
                    # Split by colons, second element is the port
                    parts = usb_path.split(":")
                    if len(parts) >= 2:
                        port = parts[1]
                except (IndexError, ValueError):
                    port = "Unknown"

            self.log.section("USB Device Added")
            self.log.kv("Device Node", device_node)
            self.log.kv("Vendor ID", vendor)
            self.log.kv("Product ID", product)
            self.log.kv("Serial", serial_num)
            self.log.kv("USB Path", usb_path)
            self.log.kv("Pi Port", port)

            # Check if device matches filters
            if self._device_matches_filters(vendor, product, serial_num, port):
                self.log.highlight("Device matches filters!")
                self._schedule_connection(device_node)
            else:
                self.log.info("Device does not match filters, ignoring")

        except Exception as e:
            self.log.error(f"Error handling device: {e}")

    def _device_matches_filters(self, vendor, product, serial_num, port):
        """Check if device matches configured filters"""
        filter_vendor = self._settings.get(["filter_vendor_id"]).strip()
        filter_product = self._settings.get(["filter_product_id"]).strip()
        filter_serial = self._settings.get(["filter_serial"]).strip()
        filter_port = self._settings.get(["filter_port"]).strip()

        # If all filters are empty, match any device
        if not any([filter_vendor, filter_product, filter_serial, filter_port]):
            self.log.info("No filters configured, matching any device")
            return True

        # Check each configured filter
        if filter_vendor and vendor != filter_vendor:
            self.log.debug(f"Vendor mismatch: {vendor} != {filter_vendor}")
            return False

        if filter_product and product != filter_product:
            self.log.debug(f"Product mismatch: {product} != {filter_product}")
            return False

        if filter_serial and serial_num != filter_serial:
            self.log.debug(f"Serial mismatch: {serial_num} != {filter_serial}")
            return False

        if filter_port and port != filter_port:
            self.log.debug(f"Port mismatch: {port} != {filter_port}")
            return False

        return True

    def _schedule_connection(self, device_node):
        """Schedule a connection attempt after configured delay"""
        delay = self._settings.get_int(["connect_delay_seconds"])
        self.log.kv("Scheduling connection in", f"{delay} seconds")

        def delayed_connect():
            time.sleep(delay)
            if not self._stop_monitoring:
                self._attempt_connection(device_node)

        thread = threading.Thread(target=delayed_connect, daemon=True)
        thread.start()

    def _attempt_connection(self, device_node):
        """Attempt to connect OctoPrint to the device"""
        self.log.section("Attempting Connection")
        self.log.kv("Device", device_node)

        try:
            # Check if printer is already connected
            if not self._printer.is_closed_or_error():
                self.log.warning("Printer already connected, skipping")
                return

            # Verify port exists and is accessible
            try:
                baudrate = self._settings.global_get_int(["serial", "baudrate"])
                if baudrate:
                    test_serial = serial.Serial(device_node, baudrate, timeout=1)
                else:
                    test_serial = serial.Serial(device_node, timeout=1)

                if test_serial.is_open:
                    # naughtily send a little message on connect
                    if self._settings.get_boolean(["message_on_connect"]):
                        test_serial.write(b"G4 1000\n")
                        test_serial.write(b"M117 Connecting...\n")
                        test_serial.write(b"G4 1000\n")
                        test_serial.write(f"M117 {device_node}\n".encode('ascii'))
                        test_serial.write(b"G4 1000\n")
                    test_serial.close()
                    self.log.info("Port is accessible")
                else:
                    self.log.error("Port failed to open")
                    return
            except Exception as e:
                self.log.error(f"Failed to test port: {e}")
                return

            # Get printer profile
            printer_profile = self._printer_profile_manager.get_default()
            profile = printer_profile.get('id', '_default')

            self.log.kv("Profile", profile)
            self.log.highlight(f"Connecting to {device_node}")

            # Initiate connection
            self._printer.connect(port=device_node, profile=profile)

        except Exception as e:
            self.log.error(f"Connection attempt failed: {e}")

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def get_template_configs(self):
        return [dict(type="settings", autoescape=True, custom_bindings=False)]

    def is_template_autoescaped(self):
        return True

__plugin_name__ = "Reconnect Guru"
__plugin_author__ = "Ed Cragg"
__plugin_description__ = "Automatically reconnects to printers detected via udev events"
__plugin_version__ = "0.0.7"
__plugin_license__ = "ISC"
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_icon__ = "plug"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = ReconnectGuruPlugin()
