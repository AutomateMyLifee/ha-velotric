"""Constants for Velotric E-Bike integration."""

from datetime import timedelta
import json

DOMAIN = "velotric"

# Configuration
CONF_MAC = "mac"
CONF_QR_CODE = "qr_code"
CONF_POLL_INTERVAL = "poll_interval"
CONF_VOLTAGE_SCALING = "voltage_scaling"
CONF_CHARGING_CURVE = "charging_curve"
CONF_IDLE_CURVE = "idle_curve"
CONF_CURVE_PRESET = "curve_preset"
CONF_OFFLINE_TIMEOUT = "offline_timeout"
CONF_BATTERY_DATA_SOURCE = "battery_data_source"
CONF_CHARGE_CURRENT_A = "charge_current_a"

# Defaults
DEFAULT_POLL_INTERVAL = 120  # 2 minutes
DEFAULT_VOLTAGE_SCALING = 1.0
DEFAULT_CURVE_PRESET = "velotric_default"
DEFAULT_OFFLINE_TIMEOUT = 300  # 5 minutes
DEFAULT_BATTERY_DATA_SOURCE = "curve"
DEFAULT_CHARGE_CURRENT_A = 1.8
SERVICE_UUID = "000018e6-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "000039f5-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "000039f6-0000-1000-8000-00805f9b34fb"
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

# Frame protocol
FRAME_HEADER = bytes([0xCA, 0x85])
FRAME_TERMINATOR = 0x0C

# Commands
CMD_AUTH_CHALLENGE = 0x10
CMD_AUTH_ACK = 0x11
CMD_CONFIG_1 = 0x14
CMD_CONFIG_2 = 0x18
CMD_CONFIG_3 = 0x82
CMD_QUERY = 0x72
CMD_RESPONSE = 0x73
CMD_FIRMWARE = 0x50
CMD_FIRMWARE_RESP = 0x51
CMD_CHARGE_STATUS = 0x04
CMD_HEARTBEAT_1 = 0x7C
CMD_HEARTBEAT_2 = 0x7D

# Query sub-commands
QUERY_BATTERY = 0x02
QUERY_RIDING = 0x01
QUERY_BATTERY_DETAIL = 0x03
QUERY_CHARGE = 0x04

# Offline detection
CONF_OFFLINE_TIMEOUT = "offline_timeout"
DEFAULT_OFFLINE_TIMEOUT = 300  # 5 minutes

# Auth frames
# Frame 2 (0x14) contains bike time setting at bytes 4-5 (hour, minute).
# Built dynamically in coordinator with current HA time to avoid resetting bike clock.
AUTH_FRAMES_BASE = [
    bytes.fromhex("CA 85 10 09 05 D9 05 05 20 4E 05 00 9B 85 0C"),
    # Frame 2 (0x14) will be built dynamically with current time
    bytes.fromhex("CA 85 18 00 A8 0C"),
    bytes.fromhex("CA 85 82 00 32 0C"),
]

def build_auth_frame_time_set(hour: int, minute: int) -> bytes:
    """Build auth frame 2 (0x14) with specified hour/minute."""
    # Base: CA 85 14 07 F7 1A 0A 18 HH MM 32 5D 0C
    # Index: 0  1  2  3  4  5  6  7  8  9  10 11 12
    payload = bytearray([0xCA, 0x85, 0x14, 0x07, 0xF7, 0x1A, 0x0A, 0x18, hour, minute, 0x32, 0x5D, 0x0C])
    return bytes(payload)


# Complete auth frames with default time (12:00) for fallback use
AUTH_FRAMES = [
    AUTH_FRAMES_BASE[0],  # Frame 1: challenge
    build_auth_frame_time_set(12, 0),  # Frame 2: config with default time
    AUTH_FRAMES_BASE[1],  # Frame 3: config
    AUTH_FRAMES_BASE[2],  # Frame 4: config
]

QUERY_FRAMES = {
    "battery": bytes.fromhex("CA 85 72 01 02 C1 0C"),
    "riding": bytes.fromhex("CA 85 72 01 01 C2 0C"),
    "battery_detail": bytes.fromhex("CA 85 72 01 03 C0 0C"),
    "charge": bytes.fromhex("CA 85 72 01 04 C7 0C"),
    "firmware": bytes.fromhex("CA 85 50 01 00 E1 0C"),
}

# Battery chemistry: 10S Li-ion NMC (36V nominal, 10.14Ah, 374Wh)
# Per-cell voltage vs SOC reference (room temp, 25C):
#   100%: ~4.10V | 90%: 4.06V | 80%: 3.98V | 70%: 3.92V | 60%: 3.87V
#   50%: 3.82V | 40%: 3.79V | 30%: 3.77V | 20%: 3.74V | 10%: 3.68V | 5%: 3.60V
# Pack-level: 100%=42.0V | 75%=39.5V | 50%=38.2V | 25%=37.5V | 0%=30.0V
# Cold temperature effects: higher IR lowers voltage ~+5% at 0°C vs 25°C;
#   charging voltage is elevated ~+5-8mV per cell. Curves below are adjusted
#   for the user's ~cold-weather readings (evidenced in soc_capture files).
#   Note: temp coefficient is nonlinear; these curves are approximations.

# Charging curve - voltage elevated during charge, adjusted for cold temp
DEFAULT_CHARGING_CURVE = [
    [4.20, 100], [4.18, 98], [4.16, 95], [4.14, 93], [4.12, 90],
    [4.10, 88], [4.08, 85], [4.06, 82], [4.04, 79], [4.02, 76],
    [4.00, 73], [3.98, 70], [3.96, 66], [3.94, 62], [3.92, 58],
    [3.90, 54], [3.88, 50], [3.86, 47], [3.84, 44], [3.82, 41],
    [3.80, 38], [3.78, 35], [3.76, 32], [3.74, 28], [3.72, 25],
    [3.70, 22], [3.68, 19], [3.66, 16], [3.64, 13], [3.62, 10],
    [3.60, 7], [3.58, 5], [3.54, 3], [3.50, 2],
]

# Idle curve (lower voltage for same SOC) - adjusted for cold
DEFAULT_IDLE_CURVE = [
    [4.10, 100], [4.08, 97], [4.06, 93], [4.03, 89], [4.00, 85],
    [3.98, 81], [3.95, 76], [3.92, 72], [3.89, 67], [3.86, 62],
    [3.82, 57], [3.79, 52], [3.75, 47], [3.72, 42], [3.68, 37],
    [3.64, 32], [3.60, 27], [3.55, 22], [3.50, 17], [3.45, 12],
    [3.40, 8], [3.35, 5], [3.30, 3], [3.25, 1],
]

# Curve presets for different bike models
CURVE_PRESETS = {
    "velotric_default": {
        "name": "Tempo Voltage Curve",
        "charging": DEFAULT_CHARGING_CURVE,
        "idle": DEFAULT_IDLE_CURVE,
    },
}

# Battery data source options
BATTERY_DATA_SOURCES = {
    "curve": "Tempo Voltage Curve",
    "reported": "Reported Battery Level",
}

# Sensor names - SINGLE DEFINITION
SENSOR_TYPES = {
    "battery": {
        "name": "Battery",
        "unit": "%",
        "icon": "mdi:battery",
        "device_class": "battery",
    },
    "battery_estimated": {
        "name": "Battery Level (Estimated)",
        "unit": "%",
        "icon": "mdi:battery",
        "device_class": "battery",
    },
    "battery_reported": {
        "name": "Battery Level (Reported)",
        "unit": "%",
        "icon": "mdi:battery-outline",
        "device_class": "battery",
    },
    "pack_voltage": {
        "name": "Pack Voltage",
        "unit": "V",
        "icon": "mdi:flash",
        "device_class": "voltage",
    },
    "avg_cell_voltage": {
        "name": "Average Cell Voltage",
        "unit": "V",
        "icon": "mdi:flash",
        "device_class": "voltage",
    },
    "delta_voltage": {
        "name": "Cell Voltage Delta",
        "unit": "mV",
        "icon": "mdi:flash-triangle",
        "device_class": "voltage",
    },
    "charge_current_raw": {
        "name": "Charge Current (Raw)",
        "unit": "raw",
        "icon": "mdi:current-dc",
    },
    "trip_distance": {
        "name": "Trip Distance",
        "unit": "km",
        "icon": "mdi:road",
        "device_class": "distance",
    },
    "charge_time_to_full": {
        "name": "Time to Full Charge",
        "unit": "min",
        "icon": "mdi:timer-outline",
        "device_class": "duration",
    },
    "firmware_display": {
        "name": "Firmware Version Display",
        "icon": "mdi:monitor",
    },
    "firmware_motor": {
        "name": "Firmware Version Motor Controller",
        "icon": "mdi:engine",
    },
    "firmware_bms": {
        "name": "Firmware Version Battery",
        "icon": "mdi:battery-heart",
    },
    "firmware_bluetooth": {
        "name": "Firmware Version Bluetooth",
        "icon": "mdi:bluetooth",
    },
    "firmware_ui": {
        "name": "Firmware Version UI Display",
        "icon": "mdi:tablet-dashboard",
    },
    "firmware_manager": {
        "name": "Firmware Version Other",
        "icon": "mdi:cog",
    },
}

# Configuration keys for options flow
CONF_MAC = "mac"
CONF_QR_CODE = "qr_code"
CONF_POLL_INTERVAL = "poll_interval"
CONF_VOLTAGE_SCALING = "voltage_scaling"
CONF_CHARGING_CURVE = "charging_curve"
CONF_IDLE_CURVE = "idle_curve"
CONF_CURVE_PRESET = "curve_preset"
CONF_OFFLINE_TIMEOUT = "offline_timeout"
CONF_BATTERY_DATA_SOURCE = "battery_data_source"

# Defaults
DEFAULT_POLL_INTERVAL = 120  # 2 minutes
DEFAULT_VOLTAGE_SCALING = 1.0
DEFAULT_CURVE_PRESET = "velotric_default"
DEFAULT_OFFLINE_TIMEOUT = 300  # 5 minutes
DEFAULT_BATTERY_DATA_SOURCE = "curve"

# Configuration keys for options flow
CONFIG_KEYS = [
    CONF_POLL_INTERVAL,
    CONF_VOLTAGE_SCALING,
    CONF_CURVE_PRESET,
    CONF_CHARGING_CURVE,
    CONF_IDLE_CURVE,
]
