"""Sensor entities for Velotric E-Bike."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

try:
    FIRMWARE_DEVICE_CLASS = SensorDeviceClass.FIRMWARE
except AttributeError:
    FIRMWARE_DEVICE_CLASS = None
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_TYPES, CONF_BATTERY_DATA_SOURCE
from .coordinator import VelotricCoordinator

_LOGGER = logging.getLogger(__name__)


def _safe_get(data: Optional[Dict], key: str, default: Any = None) -> Any:
    """Safely get value from data dict, returning default if data is None."""
    if data is None:
        return default
    return data.get(key, default)


def _round_1dp(value: Optional[float]) -> Optional[float]:
    """Round to 1 decimal place."""
    if value is None:
        return None
    return round(value, 1)


def _round_2dp(value: Optional[float]) -> Optional[float]:
    """Round to 2 decimal places."""
    if value is None:
        return None
    return round(value, 2)


def _round_3dp(value: Optional[float]) -> Optional[float]:
    """Round to 3 decimal places."""
    if value is None:
        return None
    return round(value, 3)


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up Velotric sensors."""
    coordinator: VelotricCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: List[SensorEntity] = []

    # Main battery sensor (uses selected data source)
    entities.append(VelotricBatterySensor(coordinator))

    # Main sensors
    for sensor_key in [
        "delta_voltage",
        "charge_time_to_full",
    ]:
        if sensor_key in SENSOR_TYPES:
            entities.append(VelotricSensor(coordinator, sensor_key))

    # Diagnostic sensors
    for sensor_key in [
        "pack_voltage",
        "avg_cell_voltage",
    ]:
        if sensor_key in SENSOR_TYPES:
            entities.append(VelotricSensor(coordinator, sensor_key))

    # Firmware version sensors (diagnostics)
    for fw_key in ["display", "motor", "bms", "bluetooth", "ui", "manager"]:
        entities.append(VelotricFirmwareSensor(coordinator, fw_key))

    # Binary sensors
    entities.append(VelotricChargingBinarySensor(coordinator))
    entities.append(VelotricOnlineBinarySensor(coordinator))

    async_add_entities(entities)


class VelotricBatterySensor(CoordinatorEntity, SensorEntity):
    """Main battery sensor - uses selected data source (curve or reported)."""

    def __init__(self, coordinator: "VelotricCoordinator"):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_battery"
        self._attr_name = "Battery"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        fw_display = _safe_get(data, "firmware", {}).get("display", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            name=self.coordinator.entry.title,
            manufacturer="Velotric",
            model="Tempo",
            sw_version=fw_display,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if data is None:
            return None

        # Get the selected battery data source from config entry
        battery_source = self.coordinator.entry.options.get("battery_data_source", "curve")

        if battery_source == "reported":
            # Use reported battery level from bike
            return _safe_get(self.coordinator.data, "battery_reported", 0)
        else:
            # Use estimated from voltage curve (default)
            return self.coordinator._estimate_soc(
                _safe_get(self.coordinator.data, "avg_cell_voltage", 0),
                _safe_get(self.coordinator.data, "is_charging", False)
            )

    @property
    def icon(self) -> str:
        """Return dynamic icon based on battery level and charging state."""
        data = self.coordinator.data
        if data is None:
            return "mdi:battery-unknown"
        
        is_charging = _safe_get(data, "is_charging", False)
        battery_level = self.native_value
        
        if battery_level is None:
            return "mdi:battery-unknown"
        
        if is_charging:
            return "mdi:battery-charging"
        
        # Battery level icons (10% increments)
        if battery_level <= 5:
            return "mdi:battery-outline"
        elif battery_level <= 15:
            return "mdi:battery-10"
        elif battery_level <= 25:
            return "mdi:battery-20"
        elif battery_level <= 35:
            return "mdi:battery-30"
        elif battery_level <= 45:
            return "mdi:battery-40"
        elif battery_level <= 55:
            return "mdi:battery-50"
        elif battery_level <= 65:
            return "mdi:battery-60"
        elif battery_level <= 75:
            return "mdi:battery-70"
        elif battery_level <= 85:
            return "mdi:battery-80"
        elif battery_level <= 95:
            return "mdi:battery-90"
        else:
            return "mdi:battery"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra attributes."""
        attrs = {}
        data = self.coordinator.data
        if data is None:
            return attrs

        battery_source = self.coordinator.entry.options.get("battery_data_source", "curve")
        attrs["data_source"] = "Reported" if battery_source == "reported" else "Voltage Curve"

        if battery_source == "reported":
            attrs["estimated_soc"] = self.coordinator._estimate_soc(
                _safe_get(data, "avg_cell_voltage", 0),
                _safe_get(data, "is_charging", False)
            )
        else:
            attrs["reported_soc"] = _safe_get(data, "battery_reported", 0)

        attrs["avg_cell_voltage"] = _round_3dp(_safe_get(data, "avg_cell_voltage", 0))
        cell_voltages = _safe_get(data, "cell_voltages_scaled", [])
        attrs["cell_voltages"] = [_round_3dp(v) for v in cell_voltages]
        for i, v in enumerate(cell_voltages):
            attrs[f"cell_{i+1}_voltage"] = _round_3dp(v)
        attrs["is_charging"] = _safe_get(data, "is_charging", False)
        attrs["cable_connected"] = _safe_get(data, "cable_connected", False)
        attrs["charge_current_raw"] = _safe_get(data, "charge_current_raw", 0)
        return attrs


class VelotricSensor(CoordinatorEntity, SensorEntity):
    """Base Velotric sensor."""

    def __init__(self, coordinator: "VelotricCoordinator", sensor_key: str):
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._attr_unique_id = f"{coordinator.mac}_{sensor_key}"
        self._attr_name = SENSOR_TYPES[sensor_key]["name"]
        self._attr_icon = SENSOR_TYPES[sensor_key].get("icon")
        self._attr_device_class = SENSOR_TYPES[sensor_key].get("device_class")
        self._attr_state_class = SensorStateClass.MEASUREMENT

        # Diagnostic sensors
        if sensor_key in ("delta_voltage", "charge_current_raw", "trip_distance", "battery_estimated", "battery_reported", "pack_voltage", "avg_cell_voltage"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Set units
        if "unit" in SENSOR_TYPES[sensor_key]:
            unit = SENSOR_TYPES[sensor_key]["unit"]
            if unit == "%":
                self._attr_native_unit_of_measurement = PERCENTAGE
            elif unit == "V":
                self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
            elif unit == "mV":
                try:
                    self._attr_native_unit_of_measurement = UnitOfElectricPotential.MILLIVOLT
                except AttributeError:
                    self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
            elif unit == "km":
                self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
            elif unit == "min":
                self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
            elif unit == "raw":
                self._attr_native_unit_of_measurement = None

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        fw_display = _safe_get(data, "firmware", {}).get("display", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            name=self.coordinator.entry.title,
            manufacturer="Velotric",
            model="Tempo",
            sw_version=fw_display,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> Any:
        return self._get_value()

    def _get_value(self) -> Any:
        data = self.coordinator.data
        if data is None:
            return None
        key = self._sensor_key

        if key == "battery_estimated":
            # Only estimate when reading is valid
            if self.coordinator.data.get("valid_battery_reading"):
                return self.coordinator._estimate_soc(
                    _safe_get(data, "avg_cell_voltage", 0),
                    _safe_get(data, "is_charging", False)
                )
            # Invalid reading: fall back to reported SOC
            return _safe_get(data, "battery_reported", 0)
        elif key == "battery_reported":
            return _safe_get(data, "battery_reported", 0)
        elif key == "pack_voltage":
            return _round_1dp(_safe_get(data, "pack_voltage_scaled", 0))
        elif key == "avg_cell_voltage":
            return _round_3dp(_safe_get(data, "avg_cell_voltage", 0))
        elif key == "delta_voltage":
            # Return in mV (value from coordinator is in V, convert to mV)
            val = _safe_get(data, "delta_voltage_scaled", 0)
            return _round_2dp(val * 1000) if val is not None else 0
        elif key == "charge_current_raw":
            return _safe_get(data, "charge_current_raw", 0)
        elif key == "trip_distance":
            return _round_1dp(_safe_get(data, "trip_distance_km", 0))
        elif key == "charge_time_to_full":
            return self._calculate_charge_time()
        return None

    def _calculate_charge_time(self) -> Optional[float]:
        """Calculate estimated time to 100% charge."""
        data = self.coordinator.data
        if data is None:
            return None

        current_soc = _safe_get(data, "battery_estimated", 0)
        if current_soc >= 100:
            return 0

        # Get configured charge current (in Amps)
        charge_current_a = self.coordinator.entry.options.get("charge_current_a", 2.0)
        charge_current_ma = charge_current_a * 1000

        # Battery capacity: 10.14Ah = 10140mAh
        battery_capacity_mah = 10140

        # Remaining capacity
        remaining_soc = 100 - current_soc
        remaining_mah = battery_capacity_mah * remaining_soc / 100

        # Time in hours = remaining_mAh / charge_current_mA
        time_hours = remaining_mah / charge_current_ma if charge_current_ma > 0 else 0
        time_minutes = time_hours * 60

        return round(time_minutes)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra attributes."""
        attrs = {}
        data = self.coordinator.data
        if data is None:
            return attrs

        if self._sensor_key == "battery_estimated":
            attrs["reported_soc"] = _safe_get(data, "battery_reported", 0)
            attrs["avg_cell_voltage"] = _round_3dp(_safe_get(data, "avg_cell_voltage", 0))
            cell_voltages = _safe_get(data, "cell_voltages_scaled", [])
            attrs["cell_voltages"] = [_round_3dp(v) for v in cell_voltages]
            # Individual cell voltages as separate attributes
            for i, v in enumerate(cell_voltages):
                attrs[f"cell_{i+1}_voltage"] = _round_3dp(v)
            attrs["is_charging"] = _safe_get(data, "is_charging", False)
            attrs["cable_connected"] = _safe_get(data, "cable_connected", False)
            attrs["charge_current_raw"] = _safe_get(data, "charge_current_raw", 0)

        elif self._sensor_key == "pack_voltage":
            cell_voltages = _safe_get(data, "cell_voltages_scaled", [])
            attrs["cell_voltages"] = [_round_3dp(v) for v in cell_voltages]
            # Individual cell voltages as separate attributes
            for i, v in enumerate(cell_voltages):
                attrs[f"cell_{i+1}_voltage"] = _round_3dp(v)
            attrs["avg_cell_voltage"] = _round_3dp(_safe_get(data, "avg_cell_voltage_scaled", 0))
            attrs["delta_voltage"] = _round_2dp(_safe_get(data, "delta_voltage_scaled", 0) * 1000)

        elif self._sensor_key == "battery_reported":
            attrs["estimated_soc"] = self.coordinator._estimate_soc(
                _safe_get(data, "avg_cell_voltage", 0),
                _safe_get(data, "is_charging", False)
            )
            attrs["avg_cell_voltage"] = _round_3dp(_safe_get(data, "avg_cell_voltage", 0))

        return attrs


class VelotricChargingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for charging state."""

    def __init__(self, coordinator: "VelotricCoordinator"):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_charging"
        self._attr_name = "Charging"
        self._attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
        self._attr_icon = "mdi:battery-charging"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            name=self.coordinator.entry.title,
            manufacturer="Velotric",
            model="Tempo",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        if data is None:
            return False
        # Only report charging when the bike is online (charge status only valid if online)
        return _safe_get(data, "is_charging", False) and self.coordinator.is_online

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "cable_connected": _safe_get(data, "cable_connected", False),
            "charge_current_raw": _safe_get(data, "charge_current_raw", 0),
        }


class VelotricOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for online/offline status."""

    def __init__(self, coordinator: "VelotricCoordinator"):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_online"
        self._attr_name = "Online"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:wifi"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            name=self.coordinator.entry.title,
            manufacturer="Velotric",
            model="Tempo",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_online


class VelotricFirmwareSensor(CoordinatorEntity, SensorEntity):
    """Firmware version sensor (diagnostic)."""

    def __init__(self, coordinator: "VelotricCoordinator", fw_key: str):
        super().__init__(coordinator)
        self._fw_key = fw_key
        self._attr_unique_id = f"{coordinator.mac}_fw_{fw_key}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if FIRMWARE_DEVICE_CLASS:
            self._attr_device_class = FIRMWARE_DEVICE_CLASS

        labels = {
            "display": "Display",
            "motor": "Motor Controller",
            "bms": "Battery",
            "bluetooth": "Bluetooth",
            "ui": "UI Display",
            "manager": "Other",
        }
        self._attr_name = f"Firmware Version {labels.get(fw_key, fw_key)}"
        self._attr_icon = "mdi:chip"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            name=self.coordinator.entry.title,
            manufacturer="Velotric",
            model="Tempo",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> Optional[str]:
        data = self.coordinator.data
        if data is None:
            return None
        firmware = _safe_get(data, "firmware", {})
        return firmware.get(self._fw_key)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        firmware = _safe_get(data, "firmware", {})
        return {"all_firmware": firmware}


