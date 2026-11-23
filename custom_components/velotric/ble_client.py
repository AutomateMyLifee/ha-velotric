"""BLE client for Velotric E-Bike communication."""

import asyncio
import logging
from typing import Optional, Callable, Awaitable, List, Dict, Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    close_stale_connections_by_address,
)
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    SERVICE_UUID, WRITE_UUID, NOTIFY_UUID, CCCD_UUID,
    FRAME_HEADER, FRAME_TERMINATOR,
    CMD_AUTH_CHALLENGE, CMD_AUTH_ACK, CMD_RESPONSE,
    CMD_QUERY, QUERY_BATTERY, QUERY_RIDING, QUERY_BATTERY_DETAIL, QUERY_CHARGE,
    CMD_FIRMWARE, CMD_FIRMWARE_RESP,
    AUTH_FRAMES_BASE, QUERY_FRAMES,
)

_LOGGER = logging.getLogger(__name__)


class VelotricFrame:
    """Velotric BLE frame parser/builder."""

    HEADER = FRAME_HEADER
    TERMINATOR = 0x0C

    def __init__(self, cmd: int, seq: int, payload: bytes, checksum: int):
        self.cmd = cmd
        self.seq = seq
        self.payload = payload
        self.checksum = checksum

    @classmethod
    def parse(cls, data: bytes) -> List['VelotricFrame']:
        """Parse one or more frames from notification data."""
        frames = []
        i = 0
        while i < len(data):
            if i + 1 >= len(data):
                break
            if data[i] == 0xCA and data[i + 1] == 0x85:
                j = i + 2
                while j < len(data) and data[j] != 0x0C:
                    j += 1
                if j < len(data) and data[j] == 0x0C:
                    frame_data = data[i:j+1]
                    if len(frame_data) >= 5:
                        cmd = frame_data[2]
                        seq = frame_data[3]
                        checksum = frame_data[-2]
                        payload = frame_data[4:-2]
                        frames.append(cls(cmd, seq, payload, checksum))
                    i = j + 1
                else:
                    break
            else:
                i += 1
        return frames

    def to_bytes(self) -> bytes:
        return self.HEADER + bytes([self.cmd, self.seq]) + self.payload + bytes([self.checksum, self.TERMINATOR])

    def __repr__(self):
        return f"Frame(cmd=0x{self.cmd:02X}, seq=0x{self.seq:02X}, payload={self.payload.hex()}, chk=0x{self.checksum:02X})"


class VelotricBLEClient:
    """BLE client for Velotric E-Bike using HA Bluetooth integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac: str,
        auth_frames: list[bytes] | None = None,
        query_frames: dict[str, bytes] | None = None,
    ):
        self.hass = hass
        self.mac = mac.upper()
        self.client: Optional[BleakClientWithServiceCache] = None
        self.write_char: Optional[BleakGATTCharacteristic] = None
        self.notify_char: Optional[BleakGATTCharacteristic] = None
        self.cccd_char: Optional[BleakGATTCharacteristic] = None
        self._notification_callback: Optional[Callable[[VelotricFrame], Awaitable[None]]] = None
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._seq = 1
        self._connected = False
        self._auth_frames = auth_frames if auth_frames is not None else AUTH_FRAMES
        self._query_frames = query_frames if query_frames is not None else QUERY_FRAMES

    def set_notification_callback(self, callback: Callable[[VelotricFrame], Awaitable[None]]):
        self._notification_callback = callback

    async def connect(self) -> bool:
        """Connect to the bike using HA's Bluetooth integration."""
        try:
            # Close any stale connections first
            await close_stale_connections_by_address(self.mac)

            # Resolve device through HA Bluetooth (works with ESPHome proxies)
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac, connectable=True
            )
            if device is None:
                _LOGGER.warning("Device %s not found in HA Bluetooth cache, will retry connection", self.mac)
                return False

            # Establish connection with retry logic
            self.client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self.mac,
                timeout=30.0,
                use_services_cache=True,
            )

            # Find our characteristics
            for service in self.client.services:
                for char in service.characteristics:
                    uuid_lower = char.uuid.lower()
                    if uuid_lower == WRITE_UUID.lower():
                        self.write_char = char
                    elif uuid_lower == NOTIFY_UUID.lower():
                        self.notify_char = char
                    elif uuid_lower == CCCD_UUID.lower():
                        self.cccd_char = char

            if not self.write_char or not self.notify_char:
                _LOGGER.error("Required characteristics not found")
                await self.disconnect()
                return False

            # Enable notifications via CCCD
            if self.cccd_char:
                await self.client.write_gatt_char(self.cccd_char, b'\x01\x00', response=True)

            await self.client.start_notify(self.notify_char, self._handle_notification)
            self._connected = True
            _LOGGER.debug("Connected to Velotric bike %s", self.mac)
            return True

        except Exception as e:
            _LOGGER.warning("Connection failed: %s", e)
            await self.disconnect()
            return False

    def _handle_notification(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Handle incoming notifications."""
        frames = VelotricFrame.parse(bytes(data))
        for frame in frames:
            if self._notification_callback:
                asyncio.create_task(self._notification_callback(frame))
            if frame.cmd in (CMD_AUTH_ACK, CMD_RESPONSE, 0x19, 0x83, 0x73, 0x51, 0x81, 0x15, 0x7C, 0x7D):
                try:
                    self._response_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    pass

    async def send_frame(self, frame_bytes: bytes, wait_for_response: float = 2.0) -> List[VelotricFrame]:
        """Send a frame and collect responses."""
        if not self._connected or not self.client or not self.client.is_connected:
            _LOGGER.warning("Not connected, skipping frame send")
            return []

        _LOGGER.debug("WRITE: %s", frame_bytes.hex())
        try:
            await self.client.write_gatt_char(self.write_char, frame_bytes, response=True)
        except Exception as e:
            _LOGGER.error("Write failed: %s", e)
            self._connected = False
            return []

        responses = []
        deadline = asyncio.get_event_loop().time() + wait_for_response
        while asyncio.get_event_loop().time() < deadline:
            try:
                timeout = deadline - asyncio.get_event_loop().time()
                frame = await asyncio.wait_for(self._response_queue.get(), timeout=timeout)
                responses.append(frame)
            except asyncio.TimeoutError:
                break
        return responses

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    async def run_auth_sequence(self) -> bool:
        """Run the authentication sequence."""
        for i, frame in enumerate(self._auth_frames):
            responses = await self.send_frame(frame, wait_for_response=2.0)
            ack = any(f.cmd == CMD_AUTH_ACK for f in responses)
            if not ack and i == 0:
                _LOGGER.error("Auth challenge ACK not received, authentication failed")
                return False
            if not ack and i > 0:
                _LOGGER.warning("Auth frame %d ACK not received, continuing", i)
            await asyncio.sleep(0.3)
        return True

    async def query(self, query_name: str) -> List[VelotricFrame]:
        """Send a query and return responses."""
        frame = self._query_frames.get(query_name)
        if not frame:
            return []
        return await self.send_frame(frame, wait_for_response=3.0)

    async def disconnect(self):
        if self.client and self.client.is_connected:
            try:
                if self.notify_char:
                    await self.client.stop_notify(self.notify_char)
            except Exception:
                pass
            await self.client.disconnect()
            self._connected = False


# Voltage curves (fallback defaults, overridden by coordinator options)
CHARGING_CURVE = [
    (4.20, 100), (4.18, 98), (4.15, 95), (4.12, 93), (4.10, 90),
    (4.08, 87), (4.05, 83), (4.02, 78), (4.00, 74), (3.98, 70),
    (3.95, 66), (3.92, 62), (3.90, 58), (3.88, 54), (3.85, 48),
    (3.82, 44), (3.80, 40), (3.78, 36), (3.75, 32), (3.72, 27),
    (3.70, 22), (3.68, 18), (3.65, 14), (3.62, 10), (3.60, 7),
    (3.58, 5), (3.55, 3), (3.50, 2),
]

RESTING_CURVE = [
    (4.15, 100), (4.12, 97), (4.10, 93), (4.07, 89), (4.04, 85),
    (4.00, 78), (3.97, 74), (3.94, 70), (3.91, 66), (3.88, 61),
    (3.85, 56), (3.82, 50), (3.80, 45), (3.78, 41), (3.75, 35),
    (3.72, 30), (3.70, 25), (3.68, 21), (3.65, 17), (3.62, 13),
    (3.60, 10), (3.58, 7), (3.55, 5), (3.50, 3), (3.45, 1),
]


def estimate_soc_from_voltage(avg_cell_v: float, is_charging: bool) -> int:
    """Estimate SOC from average cell voltage using calibrated curves."""
    curve = CHARGING_CURVE if is_charging else RESTING_CURVE
    for voltage, soc in curve:
        if avg_cell_v >= voltage:
            return soc
    return 1


def parse_battery_response(frame: VelotricFrame) -> Dict[str, Any]:
    """Parse battery telemetry from CMD 0x73 response."""
    if frame.cmd != 0x73:
        return {"raw": frame.payload.hex()}

    sub_cmd = frame.payload[0]
    data = frame.payload[1:]
    result = {"sub_cmd": sub_cmd}

    if sub_cmd == 0x01:  # Riding data
        result['type'] = 'riding_data'
        if len(data) >= 8:
            trip_m = (data[6] << 8) | data[7]
            result['trip_distance_m'] = trip_m
            result['trip_distance_km'] = trip_m / 1000.0
        result['raw'] = data.hex()

    elif sub_cmd == 0x02:  # Battery main info
        result['type'] = 'battery_main'
        if len(data) >= 14:
            result['soc_percent_reported'] = data[10]
            result['soc_percent_reported_alt'] = data[9]

            if len(data) >= 33:
                cell_mv = []
                for i in range(10):
                    offset = 13 + i * 2
                    if offset + 1 < len(data):
                        # BIG-endian: high byte first; data is big-endian (confirmed from capture)
                        mv = (data[offset] << 8) | data[offset + 1]
                        cell_mv.append(mv)
                result['cell_voltages_mv'] = cell_mv
                result['cell_voltages'] = [mv / 1000.0 for mv in cell_mv]
                result['pack_voltage'] = sum(cell_mv) / 1000.0
                avg_cell_v = sum(cell_mv) / 10 / 1000.0
                result['avg_cell_voltage'] = avg_cell_v

                # Validate readings: skip 0V, high/low outliers, and implausible avg/pack
                # Cell voltage must be > 2V and < 5V; pack must be > 20V and < 50V
                valid_cells = [v for v in cell_mv if 2000.0 <= v <= 5000.0]
                if len(valid_cells) >= 10:
                    valid_avg_mv = sum(valid_cells) / 10.0
                    valid_pack_mv = sum(valid_cells)
                    if 2000.0 < valid_avg_mv < 5000.0 and 20000.0 < valid_pack_mv < 50000.0:
                        result['valid_battery_reading'] = True
                    else:
                        result['valid_battery_reading'] = False
                else:
                    result['valid_battery_reading'] = False

                # Only estimate SOC when the reading is valid
                if result.get('valid_battery_reading'):
                    result['soc_percent_estimated_resting'] = estimate_soc_from_voltage(avg_cell_v, False)
                    result['soc_percent_estimated_charging'] = estimate_soc_from_voltage(avg_cell_v, True)

            if len(data) >= 14:
                result['cell_voltages_str'] = data[11:14].decode('ascii', errors='ignore')
        result['raw'] = data.hex()

    elif sub_cmd == 0x03:  # Battery detail
        result['type'] = 'battery_detail'
        if len(data) >= 6:
            result['pack_voltage_str'] = data[2:6].decode('ascii', errors='ignore')
        result['raw'] = data.hex()

    elif sub_cmd == 0x04:  # Charge status
        max_current_ma = 2170
        for i in range(len(data) - 1):
            if data[i] == 0x08 and data[i + 1] == 0x7a:
                max_current_ma = (data[i] << 8) | data[i + 1]
                break

        cable_connected = False
        charge_active = False
        if len(data) >= 3:
            cable_connected = data[1] == 0x01
            charge_active = data[2] == 0x04

        actual_current_raw = None
        if len(data) >= 15:
            actual_current_raw = data[14]
        elif len(data) >= 16:
            actual_current_raw = data[15]

        result['type'] = 'charge_status'
        result['cable_connected'] = cable_connected
        result['is_charging'] = charge_active
        result['charge_current_max_ma'] = max_current_ma
        result['charge_current_actual_raw'] = actual_current_raw
        result['charge_state_raw'] = data[2] if len(data) > 2 else 0
        result['raw'] = data.hex()

    return result


def parse_firmware_response(frame: VelotricFrame) -> Dict[str, Any]:
    """Parse firmware version response (CMD 0x51)."""
    if frame.cmd != 0x51:
        return {}
    try:
        text = frame.payload.decode('ascii', errors='ignore')
        import re
        parts = re.split(r'[\x01-\x08]', text)
        versions = [p for p in parts if p and any(c.isdigit() for c in p)]
        return {'firmware_strings': versions, 'raw': frame.payload.hex()}
    except:
        return {'raw': frame.payload.hex()}