"""Config flow for Velotric E-Bike integration."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_MAC,
    CONF_QR_CODE,
    CONF_POLL_INTERVAL,
    CONF_CHARGING_CURVE,
    CONF_IDLE_CURVE,
    CONF_CURVE_PRESET,
    CONF_OFFLINE_TIMEOUT,
    CONF_BATTERY_DATA_SOURCE,
    CONF_CHARGE_CURRENT_A,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_CURVE_PRESET,
    DEFAULT_OFFLINE_TIMEOUT,
    DEFAULT_CHARGING_CURVE,
    DEFAULT_IDLE_CURVE,
    DEFAULT_CHARGE_CURRENT_A,
    CURVE_PRESETS,
    BATTERY_DATA_SOURCES,
    DEFAULT_BATTERY_DATA_SOURCE,
)

_LOGGER = logging.getLogger(__name__)

# QR code regex - format: SERIAL##MAC##KEY
QR_PATTERN = re.compile(r"^[A-Z0-9]+##([0-9A-F:]{17})##[0-9A-Fa-f]{8}$", re.IGNORECASE)
# MAC address regex
MAC_PATTERN = re.compile(r"^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$", re.IGNORECASE)


class VelotricConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Velotric E-Bike."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            device_id = user_input.get("device_id", "").strip()

            qr_code = None
            mac = None

            # Determine if input is QR code or MAC
            if device_id:
                if QR_PATTERN.match(device_id):
                    match = QR_PATTERN.match(device_id)
                    if match:
                        mac = match.group(1).upper()
                        qr_code = device_id
                    else:
                        errors["device_id"] = "invalid_qr_format"
                elif MAC_PATTERN.match(device_id):
                    mac = device_id.upper()
                else:
                    errors["device_id"] = "invalid_format"

            if mac and not errors:
                try:
                    if await self._test_connection(mac):
                        await self.async_set_unique_id(mac.replace(":", ""))
                        self._abort_if_unique_id_configured()
                        # Get curves from preset
                        preset = CURVE_PRESETS.get(DEFAULT_CURVE_PRESET, {})
                        charging_curve = preset.get("charging", DEFAULT_CHARGING_CURVE)
                        idle_curve = preset.get("idle", DEFAULT_IDLE_CURVE)

                        return self.async_create_entry(
                            title=f"Velotric {mac[-5:].replace(':', '')}",
                            data={
                                CONF_MAC: mac,
                                CONF_QR_CODE: qr_code,
                            },
                            options={
                                CONF_OFFLINE_TIMEOUT: DEFAULT_OFFLINE_TIMEOUT,
                                CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
                                CONF_CURVE_PRESET: DEFAULT_CURVE_PRESET,
                                CONF_BATTERY_DATA_SOURCE: DEFAULT_BATTERY_DATA_SOURCE,
                                CONF_CHARGING_CURVE: charging_curve,
                                CONF_IDLE_CURVE: idle_curve,
                            },
                        )
                    else:
                        errors["base"] = "cannot_connect"
                except VelotricConnectionError:
                    errors["base"] = "cannot_connect"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception during connection test")
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("device_id"): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "device_help": self.hass.data.get("device_help", "")
            },
        )

    async def _test_connection(self, mac: str) -> bool:
        """Test if we can connect to the bike using HA Bluetooth."""
        try:
            device = bluetooth.async_ble_device_from_address(
                self.hass, mac.upper(), connectable=True
            )
            if device is None:
                _LOGGER.debug("Device %s not found in HA Bluetooth cache", mac)
                return False

            from bleak_retry_connector import (
                BleakClientWithServiceCache,
                establish_connection,
                close_stale_connections_by_address,
            )
            await close_stale_connections_by_address(mac)
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                mac,
                timeout=15.0,
                use_services_cache=True,
            )
            await client.disconnect()
            return True
        except Exception as exc:
            _LOGGER.debug("Connection test failed for %s: %s", mac, exc)
            raise VelotricConnectionError from exc

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow."""
        return VelotricOptionsFlow()


class VelotricOptionsFlow(OptionsFlow):
    """Handle options for Velotric."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._calibrate_data: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Check if user wants to calibrate
            if user_input.get("calibrate"):
                return await self.async_step_calibrate()

            # Parse JSON curves if provided
            options = dict(user_input)

            # Parse custom curves if provided
            for field in (CONF_CHARGING_CURVE, CONF_IDLE_CURVE):
                if user_input.get(field):
                    try:
                        json.loads(user_input[field])
                    except json.JSONDecodeError:
                        return self.async_show_form(
                            step_id="init",
                            data_schema=self._build_schema(),
                            errors={field: "invalid_json"},
                        )

            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(),
        )

    async def async_step_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle calibration step."""
        errors = {}

        # Get coordinator to read current voltage
        coordinator = self.hass.data[DOMAIN].get(self.config_entry.entry_id)

        if user_input is not None:
            _LOGGER.debug("Calibration input: %s", user_input)
            try:
                # Get current avg cell voltage from coordinator
                if coordinator and coordinator.data:
                    avg_cell_voltage = coordinator.data.get("avg_cell_voltage", 0)
                    is_charging = coordinator.data.get("is_charging", False)
                    _LOGGER.debug("Using coordinator data: voltage=%.3f, charging=%s", avg_cell_voltage, is_charging)
                else:
                    # Use user provided values if coordinator not available
                    avg_cell_voltage = user_input.get("avg_cell_voltage", 3.8)
                    is_charging = user_input.get("is_charging", False)
                    _LOGGER.debug("Using user input data: voltage=%.3f, charging=%s", avg_cell_voltage, is_charging)

                observed_soc = user_input.get("observed_soc", 70)
                _LOGGER.debug("Observed SOC: %d", observed_soc)

                # Determine which curve to adjust
                if is_charging:
                    curve_key = CONF_CHARGING_CURVE
                else:
                    curve_key = CONF_IDLE_CURVE

                # Get current curve
                current_curve = self.config_entry.options.get(curve_key, DEFAULT_CHARGING_CURVE if is_charging else DEFAULT_IDLE_CURVE)
                _LOGGER.debug("Current curve (%s): %d points", curve_key, len(current_curve))

                # Adjust curve to match observed SOC at current voltage
                adjusted_curve = self._adjust_curve_at_voltage(current_curve, avg_cell_voltage, observed_soc)
                _LOGGER.debug("Adjusted curve: %d points", len(adjusted_curve))

                # Update options with adjusted curve
                new_options = dict(self.config_entry.options)
                new_options[curve_key] = adjusted_curve
                _LOGGER.debug("Saving updated %s curve to options: %s", curve_key, adjusted_curve[:3])

                _LOGGER.info("Calibration successful: adjusted %s curve at %.3fV to %d%% SOC", curve_key, avg_cell_voltage, observed_soc)
                return self.async_create_entry(title="", data=new_options)

            except Exception as exc:
                _LOGGER.exception("Calibration failed: %s", exc)
                errors["base"] = "calibration_failed"

        # Get current voltage from coordinator for display
        current_voltage = 0
        is_charging = False
        if coordinator and coordinator.data:
            current_voltage = round(coordinator.data.get("avg_cell_voltage", 0), 3)
            is_charging = coordinator.data.get("is_charging", False)

        return self.async_show_form(
            step_id="calibrate",
            data_schema=vol.Schema(
                {
                    vol.Required("observed_soc", default=70): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                    vol.Optional("avg_cell_voltage", default=current_voltage): vol.All(vol.Coerce(float), vol.Range(min=2.5, max=4.5)),
                    vol.Optional("is_charging", default=is_charging): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "current_voltage": str(current_voltage),
                "charging_status": "Charging" if is_charging else "Idle",
            },
        )

    def _adjust_curve_at_voltage(self, curve: list[list[float]], voltage: float, target_soc: int) -> list[list[float]]:
        """Adjust curve so that given voltage maps to target SOC using linear interpolation."""
        if not curve:
            return curve

        # Filter valid 2-element points and sort by voltage descending
        valid_curve = [p for p in curve if isinstance(p, (list, tuple)) and len(p) == 2]
        if len(valid_curve) < 2:
            return curve
        sorted_curve = sorted(valid_curve, key=lambda x: x[0], reverse=True)

        # Find the two points that bracket the voltage
        lower_point = None
        upper_point = None

        for i, point in enumerate(sorted_curve):
            v, soc = point[0], point[1]
            if v <= voltage:
                lower_point = (v, soc)
                if i > 0:
                    upper_point = (sorted_curve[i - 1][0], sorted_curve[i - 1][1])
                break
        else:
            # Voltage is below all points
            lower_point = (sorted_curve[-1][0], sorted_curve[-1][1])
            upper_point = (sorted_curve[-2][0], sorted_curve[-2][1])

        if lower_point is None or upper_point is None:
            return curve

        # Interpolate to find what SOC the voltage currently maps to
        v_lower, soc_lower = lower_point
        v_upper, soc_upper = upper_point

        if v_upper == v_lower:
            return curve

        current_soc = soc_lower + (soc_upper - soc_lower) * (voltage - v_lower) / (v_upper - v_lower)

        # Calculate adjustment factor
        soc_diff = target_soc - current_soc

        # Shift all SOC values by the difference
        adjusted = []
        for point in curve:
            if isinstance(point, (list, tuple)) and len(point) == 2:
                v, soc = point[0], point[1]
                new_soc = max(0, min(100, soc + soc_diff))
                adjusted.append([v, round(new_soc)])
            else:
                adjusted.append(point)

        # Sort by voltage descending
        adjusted.sort(key=lambda x: x[0] if isinstance(x, (list, tuple)) and len(x) > 0 else 0, reverse=True)

        return adjusted

    def _build_schema(self) -> vol.Schema:
        """Build the options schema with current values pre-populated."""
        # Get current curve values, serialize to JSON if they exist
        charging_curve = self.config_entry.options.get(CONF_CHARGING_CURVE)
        idle_curve = self.config_entry.options.get(CONF_IDLE_CURVE)

        # Serialize curves to JSON for the text fields
        charging_json = json.dumps(charging_curve, indent=2) if charging_curve else ""
        idle_json = json.dumps(idle_curve, indent=2) if idle_curve else ""

        return vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_POLL_INTERVAL, 120
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Optional(
                    CONF_BATTERY_DATA_SOURCE,
                    default=self.config_entry.options.get(
                        CONF_BATTERY_DATA_SOURCE, "curve"
                    ),
                ): vol.In(BATTERY_DATA_SOURCES),
                vol.Optional(
                    CONF_CURVE_PRESET,
                    default=self.config_entry.options.get(
                        CONF_CURVE_PRESET, "velotric_default"
                    ),
                ): vol.In({k: v["name"] for k, v in CURVE_PRESETS.items()}),
                vol.Optional(
                    CONF_CHARGING_CURVE,
                    default=charging_json,
                ): str,
                vol.Optional(
                    CONF_IDLE_CURVE,
                    default=idle_json,
                ): str,
                vol.Optional(
                    CONF_OFFLINE_TIMEOUT,
                    default=self.config_entry.options.get(
                        CONF_OFFLINE_TIMEOUT, 300
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                vol.Optional(
                    CONF_CHARGE_CURRENT_A,
                    default=self.config_entry.options.get(
                        CONF_CHARGE_CURRENT_A, 2.0
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0)),
                # Calibration button
                vol.Optional("calibrate", default=False): bool,
            },
        )


class VelotricConnectionError(HomeAssistantError):
    """Error to indicate a connection error with the Velotric bike."""