"""Data update coordinator for Velotric E-Bike."""

import asyncio
import logging
from datetime import timedelta
from typing import Dict, Any, Optional, List

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN, DEFAULT_POLL_INTERVAL, DEFAULT_VOLTAGE_SCALING,
    DEFAULT_CHARGING_CURVE, DEFAULT_IDLE_CURVE, CURVE_PRESETS,
    CONF_POLL_INTERVAL, CONF_VOLTAGE_SCALING,
    CONF_CHARGING_CURVE, CONF_IDLE_CURVE, CONF_CURVE_PRESET,
    CONF_OFFLINE_TIMEOUT, DEFAULT_OFFLINE_TIMEOUT,
    AUTH_FRAMES_BASE, QUERY_FRAMES, build_auth_frame_time_set,
)
from .ble_client import (
    VelotricBLEClient, VelotricFrame,
    parse_battery_response, parse_firmware_response,
    estimate_soc_from_voltage,
)

_LOGGER = logging.getLogger(__name__)


class VelotricCoordinator(DataUpdateCoordinator):
    """Coordinator to manage Velotric E-Bike data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        mac: str,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.entry = entry
        self.mac = mac
        self.voltage_scaling = entry.options.get(CONF_VOLTAGE_SCALING, DEFAULT_VOLTAGE_SCALING)
        self.offline_timeout = entry.options.get(CONF_OFFLINE_TIMEOUT, DEFAULT_OFFLINE_TIMEOUT)
        self.ble_client: Optional[VelotricBLEClient] = None
        self._connected = False
        self._last_successful_update: Optional[float] = None
        self._last_battery_data: Dict[str, Any] = {}
        self._last_riding_data: Dict[str, Any] = {}
        self._last_charge_data: Dict[str, Any] = {}
        self._last_battery_detail_data: Dict[str, Any] = {}
        self._firmware_data: Dict[str, Any] = {}
        # Raw frame data for diagnostics
        self._raw_battery_frame: Optional[str] = None
        self._raw_riding_frame: Optional[str] = None
        self._raw_charge_frame: Optional[str] = None
        self._raw_battery_detail_frame: Optional[str] = None
        self._raw_firmware_frame: Optional[str] = None
        self._charging_curve: List[List[float]] = []
        self._idle_curve: List[List[float]] = {}
        self._update_curves()

    def _update_curves(self):
        """Update curves from config entry options."""
        # Get preset
        preset = self.entry.options.get(CONF_CURVE_PRESET, "velotric_discover2")
        
        # Check for custom curves
        custom_charging = self.entry.options.get(CONF_CHARGING_CURVE)
        custom_idle = self.entry.options.get(CONF_IDLE_CURVE)
        
        if custom_charging and isinstance(custom_charging, list):
            self._charging_curve = custom_charging
        elif preset in CURVE_PRESETS:
            self._charging_curve = CURVE_PRESETS[preset]["charging"]
        else:
            self._charging_curve = DEFAULT_CHARGING_CURVE
            
        if custom_idle and isinstance(custom_idle, list):
            self._idle_curve = custom_idle
        elif preset in CURVE_PRESETS:
            self._idle_curve = CURVE_PRESETS[preset]["idle"]
        else:
            self._idle_curve = DEFAULT_IDLE_CURVE

    @property
    def is_online(self) -> bool:
        """Return True if bike is considered online (recent successful update within timeout)."""
        if self._last_successful_update is None:
            return False
        import time
        return (time.time() - self._last_successful_update) < self.offline_timeout

    def _estimate_soc(self, avg_cell_v: float, is_charging: bool) -> int:
        """Estimate SOC from voltage using configured curves with linear interpolation."""
        curve = self._charging_curve if is_charging else self._idle_curve
        
        if not curve:
            return 1
        
        # If voltage is above highest point, return max SOC
        if avg_cell_v >= curve[0][0]:
            return curve[0][1]
        
        # If voltage is below lowest point, return min SOC
        if avg_cell_v <= curve[-1][0]:
            return curve[-1][1]
        
        # Find the two points that surround the voltage
        # Curve is sorted by voltage descending: [(V_high, SOC_high), (V_low, SOC_low), ...]
        for i in range(len(curve) - 1):
            v_high, soc_high = curve[i]
            v_low, soc_low = curve[i + 1]
            
            if v_low <= avg_cell_v <= v_high:
                # Linear interpolation: soc = soc_low + (soc_high - soc_low) * (v - v_low) / (v_high - v_low)
                if v_high != v_low:
                    soc = soc_low + (soc_high - soc_low) * (avg_cell_v - v_low) / (v_high - v_low)
                    return round(soc)
                return soc_high
        
        return 1

    async def async_update_options(self):
        """Update coordinator when options change."""
        old_interval = self.update_interval
        new_interval = timedelta(
            seconds=self.entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        if old_interval != new_interval:
            self.update_interval = new_interval
            
        self.voltage_scaling = self.entry.options.get(CONF_VOLTAGE_SCALING, DEFAULT_VOLTAGE_SCALING)
        self._update_curves()
        _LOGGER.debug("Updated curves: charging=%d points, idle=%d points", 
                     len(self._charging_curve), len(self._idle_curve))
    
    async def _async_setup(self) -> bool:
        """Set up the BLE connection and authentication."""
        try:
            # Clean up old client if exists
            if self.ble_client:
                try:
                    await self.ble_client.disconnect()
                except Exception:
                    pass
                self.ble_client = None

            self._connected = False

            # Get custom frames from options if provided
            custom_auth = self.entry.options.get("auth_frames")
            custom_query = self.entry.options.get("query_frames")

            if custom_auth:
                auth_frames = [bytes.fromhex(f) for f in custom_auth]
            else:
                # Build auth frames with current HA time for frame 2 (0x14 time set)
                from datetime import datetime
                now = datetime.now()
                auth_frames = [
                    AUTH_FRAMES_BASE[0],  # Frame 1: challenge
                    build_auth_frame_time_set(now.hour, now.minute),  # Frame 2: config with current time
                    AUTH_FRAMES_BASE[1],  # Frame 3: config
                    AUTH_FRAMES_BASE[2],  # Frame 4: config
                ]

            if custom_query:
                query_frames = {k: bytes.fromhex(v) for k, v in custom_query.items()}
            else:
                query_frames = QUERY_FRAMES

            self.ble_client = VelotricBLEClient(
                self.hass, self.mac,
                auth_frames=auth_frames,
                query_frames=query_frames,
            )

            if not await self.ble_client.connect():
                return False

            self._connected = True

            # Run auth sequence
            if not await self.ble_client.run_auth_sequence():
                return False

            # Initial data fetch
            await self._fetch_all_data()

            return True
        except Exception as e:
            _LOGGER.error("Setup failed: %s", e)
            if self.ble_client:
                try:
                    await self.ble_client.disconnect()
                except Exception:
                    pass
                self.ble_client = None
            self._connected = False
            return False
    
    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the bike. Returns stale data on failure to keep entities available."""
        if not self._connected:
            if not await self._async_setup():
                # Setup failed - return stale data, don't update last_successful_update
                _LOGGER.debug("Failed to connect to bike, returning stale data")
                return self._build_state()

        try:
            await self._fetch_battery()
            await self._fetch_charge_status()
            await self._fetch_riding()
            await self._fetch_firmware()

            # Successful update - record timestamp
            import time
            self._last_successful_update = time.time()

        except Exception as e:
            # Connection failed - mark as disconnected but return stale data
            # This keeps entities available with last known values
            if self._connected:
                _LOGGER.debug("Bike disconnected: %s", e)
            else:
                _LOGGER.debug("Bike not reachable: %s", e)
            self._connected = False
            # Clean up client on failure
            if self.ble_client:
                try:
                    await self.ble_client.disconnect()
                except Exception:
                    pass
                self.ble_client = None
            # Return stale state instead of raising - keeps last_update_success=True
            return self._build_state()

        return self._build_state()
    
    async def _fetch_all_data(self):
        """Fetch all data types."""
        await self._fetch_battery()
        await self._fetch_charge_status()
        await self._fetch_riding()
        await self._fetch_battery_detail()
        await self._fetch_firmware()
    
    async def _fetch_battery(self):
        """Fetch battery data."""
        try:
            frames = await self.ble_client.query("battery")
            if not frames:
                raise UpdateFailed("No response to battery query")
            found = False
            for frame in frames:
                if frame.cmd == 0x73:
                    parsed = parse_battery_response(frame)
                    self._last_battery_data = parsed
                    # Store raw frame data for diagnostics
                    self._raw_battery_frame = frame.payload.hex().upper()
                    _LOGGER.debug("Battery data: %s", parsed)
                    found = True
            if not found:
                raise UpdateFailed("No valid battery response frame (cmd 0x73)")
        except UpdateFailed:
            raise
        except Exception as e:
            _LOGGER.warning("Failed to fetch battery: %s", e)
            raise UpdateFailed(f"Battery fetch failed: {e}")
    
    async def _fetch_battery_detail(self):
        """Fetch battery detail data."""
        try:
            frames = await self.ble_client.query("battery_detail")
            if not frames:
                raise UpdateFailed("No response to battery detail query")
            found = False
            for frame in frames:
                if frame.cmd == 0x73:
                    parsed = parse_battery_response(frame)
                    self._last_battery_detail_data = parsed
                    # Store raw frame data for diagnostics
                    self._raw_battery_detail_frame = frame.payload.hex().upper()
                    found = True
            if not found:
                raise UpdateFailed("No valid battery detail response frame (cmd 0x73)")
        except UpdateFailed:
            raise
        except Exception as e:
            _LOGGER.warning("Failed to fetch battery detail: %s", e)
            raise UpdateFailed(f"Battery detail fetch failed: {e}")

    async def _fetch_charge_status(self):
        """Fetch charge status."""
        try:
            frames = await self.ble_client.query("charge")
            if not frames:
                raise UpdateFailed("No response to charge status query")
            found = False
            for frame in frames:
                if frame.cmd == 0x73:
                    parsed = parse_battery_response(frame)
                    self._last_charge_data = parsed
                    # Store raw frame data for diagnostics
                    self._raw_charge_frame = frame.payload.hex().upper()
                    found = True
            if not found:
                raise UpdateFailed("No valid charge status response frame (cmd 0x73)")
        except UpdateFailed:
            raise
        except Exception as e:
            _LOGGER.warning("Failed to fetch charge status: %s", e)
            raise UpdateFailed(f"Charge status fetch failed: {e}")
    
    async def _fetch_riding(self):
        """Fetch riding/trip data."""
        try:
            frames = await self.ble_client.query("riding")
            if not frames:
                raise UpdateFailed("No response to riding query")
            found = False
            for frame in frames:
                if frame.cmd == 0x73:
                    parsed = parse_battery_response(frame)
                    self._last_riding_data = parsed
                    # Store raw frame data for diagnostics
                    self._raw_riding_frame = frame.payload.hex().upper()
                    found = True
            if not found:
                raise UpdateFailed("No valid riding response frame (cmd 0x73)")
        except UpdateFailed:
            raise
        except Exception as e:
            _LOGGER.warning("Failed to fetch riding data: %s", e)
            raise UpdateFailed(f"Riding fetch failed: {e}")
    
    async def _fetch_firmware(self):
        """Fetch firmware versions."""
        try:
            frames = await self.ble_client.query("firmware")
            if not frames:
                raise UpdateFailed("No response to firmware query")
            found = False
            for frame in frames:
                if frame.cmd == 0x51:
                    parsed = parse_firmware_response(frame)
                    self._firmware_data = parsed
                    # Store raw frame data for diagnostics
                    self._raw_firmware_frame = frame.payload.hex().upper()
                    found = True
            if not found:
                raise UpdateFailed("No valid firmware response frame (cmd 0x51)")
        except UpdateFailed:
            raise
        except Exception as e:
            _LOGGER.warning("Failed to fetch firmware: %s", e)
            raise UpdateFailed(f"Firmware fetch failed: {e}")
    
    def _build_state(self) -> Dict[str, Any]:
        """Build the complete state dictionary."""
        battery = self._last_battery_data
        charge = self._last_charge_data
        riding = self._last_riding_data
        firmware = self._firmware_data
        
        cell_voltages = battery.get('cell_voltages', [])
        
        # Filter out 0 voltage readings - only use if we have valid cell voltages
        valid_cell_voltages = [v for v in cell_voltages if v > 0]
        if not valid_cell_voltages:
            # No valid cell voltages, keep previous values
            return self._build_state_from_last()
        
        # Voltage scaling
        scaled_pack_v = battery.get('pack_voltage', 0) * self.voltage_scaling
        scaled_cell_v = [round(v * self.voltage_scaling, 3) for v in valid_cell_voltages]
        
        # Delta voltage (only from valid cells)
        delta_v = max(valid_cell_voltages) - min(valid_cell_voltages)
        
        # Delta voltage scaled
        delta_v_scaled = delta_v * self.voltage_scaling
        
        # Charging status
        is_charging = charge.get('is_charging', False)
        cable_connected = charge.get('cable_connected', False)
        charge_current_raw = charge.get('charge_current_actual_raw', 0)
        
        # SOC estimation using configured curves - only when reading is valid
        avg_cell_v = battery.get('avg_cell_voltage', 0)
        soc_estimated = 0
        if battery.get('valid_battery_reading') and avg_cell_v > 0:
            avg_cell_v_scaled = round(avg_cell_v * self.voltage_scaling, 3)
            soc_estimated = self._estimate_soc(avg_cell_v, is_charging)
        else:
            avg_cell_v_scaled = round(avg_cell_v * self.voltage_scaling, 3) if avg_cell_v > 0 else 0
            # Fallback: use reported SOC if available
            soc_estimated = battery.get('soc_percent_reported', 0)
        
        # Firmware versions
        fw_strings = firmware.get('firmware_strings', [])
        firmware_versions = {}
        for f in fw_strings:
            for prefix, label in [('SWDP', 'display'), ('SWMC', 'motor'), ('SWBL', 'bms'),
                                  ('SWBE', 'bluetooth'), ('SWUI', 'ui'), ('SWFM', 'manager')]:
                if prefix in f:
                    version = f.split('V')[-1] if 'V' in f else 'unknown'
                    firmware_versions[label] = f"V{version}"
                    break
        
        return {
            "battery_reported": battery.get('soc_percent_reported', 0),
            "battery_estimated": soc_estimated,
            "pack_voltage": battery.get('pack_voltage', 0),
            "cell_voltages": cell_voltages,
            "avg_cell_voltage": battery.get('avg_cell_voltage', 0),
            "avg_cell_voltage_scaled": avg_cell_v_scaled,
            "delta_voltage": delta_v,
            "charge_current_raw": charge_current_raw,
            "cable_connected": cable_connected,
            "is_charging": is_charging,
            "trip_distance_km": riding.get('trip_distance_km', 0),
            "firmware": firmware_versions,
            "cell_voltages_scaled": scaled_cell_v,
            "pack_voltage_scaled": scaled_pack_v,
            "delta_voltage_scaled": delta_v_scaled,
            "online": self.is_online,
            # Raw frame data for diagnostics
            "raw_battery_frame": self._raw_battery_frame,
            "raw_riding_frame": self._raw_riding_frame,
            "raw_charge_frame": self._raw_charge_frame,
            "raw_battery_detail_frame": self._raw_battery_detail_frame,
            "raw_firmware_frame": self._raw_firmware_frame,
        }
    
    def _build_state_from_last(self) -> Dict[str, Any]:
        """Build state from last known good values when voltage is 0."""
        # Return empty dict to trigger re-fetch, or return minimal state
        return {
            "battery_reported": 0,
            "battery_estimated": 0,
            "pack_voltage": 0,
            "cell_voltages": [],
            "avg_cell_voltage": 0,
            "avg_cell_voltage_scaled": 0,
            "delta_voltage": 0,
            "charge_current_raw": 0,
            "cable_connected": False,
            "is_charging": False,
            "trip_distance_km": 0,
            "firmware": {},
            "cell_voltages_scaled": [],
            "pack_voltage_scaled": 0,
            "delta_voltage_scaled": 0,
            "online": self.is_online,
            "raw_battery_frame": self._raw_battery_frame,
            "raw_riding_frame": self._raw_riding_frame,
            "raw_charge_frame": self._raw_charge_frame,
            "raw_battery_detail_frame": self._raw_battery_detail_frame,
            "raw_firmware_frame": self._raw_firmware_frame,
        }
    
    async def async_shutdown(self):
        """Clean up on shutdown."""
        if self.ble_client:
            await self.ble_client.disconnect()
            self._connected = False