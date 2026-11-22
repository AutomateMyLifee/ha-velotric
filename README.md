# Velotric E-Bike BLE Home Assistant Integration [beta]

Custom Home Assistant integration for Velotric e-bikes (only my Velotric Tempo tested) via Bluetooth LE proxy (ie. ESPHome BLE proxy).

## Features

- **Battery Monitoring**:
  - Battery Level - Estimated from cell voltage
  - Battery Level - Reported by bike protocol (values currently not accurate, still testing)
  - Pack Voltage - Average Cell Voltage attribute
  - Cell Voltage Delta (highest - lowest cell)
  - Individual Cell Voltages (10 cells)
  - Charge Current (raw value, needs calibration)

- **Riding Data**:
  - Trip Distance [testing]

- **Firmware Versions**:
  - Display
  - Motor Controller
  - Battery (BMS)
  - Bluetooth
  - UI Display
  - Firmware Manager

- **Charge Status**:
  - Cable Connected
  - Charging Active
  - Actual Charge Current (raw) [testing]

- **Voltage Curve Calibration**:
  - Preset curve for Velotric Tempo
  - Custom JSON curve editor
  - Calibrate at current SOC button

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=AutomateMyLifee&repository=ha-velotric&category=integration)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add repository: `https://github.com/AutomateMyLifee/ha-velotric` (category: Integration)
3. Install "Velotric E-Bike"
4. Restart Home Assistant

### Manual
1. Copy `velotric` folder to `config/custom_components/`
2. Restart Home Assistant

## Configuration

### Via UI (Recommended)
1. Settings → Devices & Services → Add Integration
2. Search "Velotric"
3. Enter your bike's **QR code** (from bike display) or **MAC address**
4. The QR code format: `SERIAL##MAC##KEY` 

### Bluetooth Discovery
The integration will auto-discover your bike via Bluetooth if it's nearby and powered on.

## Sensors Created

| Sensor | Unit | Description |
|--------|------|-------------|
| Battery | % | Main battery level (uses selected data source) |
| Battery Level (Estimated) | % | Calculated from cell voltage (more accurate) |
| Battery Level (Reported) | % | Raw value from bike protocol |
| Pack Voltage | V | Total pack voltage |
| Average Cell Voltage | V | Mean of 10 cells |
| Cell Voltage Delta | mV | Highest - lowest cell voltage |
| Cell 1-10 Voltage | V | Individual cell voltages |
| Charge Current (Raw) | raw | Raw charge current value [testing] |
| Trip Distance | km | Trip meter [testing] |
| Firmware Display | - | Display firmware version |
| Firmware Motor Controller | - | Motor controller firmware |
| Firmware BMS | - | Battery management system firmware |
| Firmware Bluetooth | - | Bluetooth module firmware |
| Firmware UI Display | - | UI display firmware |
| Firmware Manager | - | Firmware manager version |

## Options

Settings → Devices & Services → Velotric → Configure

### Basic
- **Poll Interval**: How often to poll the bike (default: 120 seconds). Bike only connectable when on/charging.
- **Battery Data Source**: Select data source - "Tempo Voltage Curve" (estimated from voltage) or "Reported Battery Level" (bike's reported value)
- **Voltage Curve Preset**: Select voltage curve preset (Tempo Voltage Curve, etc.)

### Advanced Calibration
- **Custom Charging Curve**: JSON editor for charging voltage-SOC pairs
- **Custom Idle Curve**: JSON editor for idle voltage-SOC pairs

### Calibrate at Current SOC
1. Ensure bike is on and connected
2. Go to Options → Calibrate at Current SOC
3. Enter the SOC percentage shown on your bike display/app
4. Select if currently charging
5. Curves auto-adjust to match

## Voltage Curve Calibration

### Presets
| Preset | Description |
|--------|-------------|
| Tempo Voltage Curve | Default |

### Custom Curve Format (JSON)
```json
[
  [4.20, 100],
  [4.15, 95],
  [4.10, 90],
  [4.05, 85],
  [4.00, 74],
  [3.95, 66],
  [3.90, 58],
  [3.85, 48],
  [3.80, 40],
  [3.75, 32],
  [3.70, 22],
  [3.65, 14],
  [3.60, 7],
  [3.55, 3],
  [3.50, 2]
]
```
- Voltage: V per cell (descending order)
- SOC: percentage (descending order)
- Minimum 3 points required

## Services

- `velotric.force_update` - Force immediate data update
- `velotric.send_query` - Send specific query (battery, riding, charge, firmware)

## Known Limitations

- **Total Odometer**: Unable to reverse engineer at the time
- **Charge Time Remaining**: Doesn't seem to be transmitted by bike; calculate in HA: `(remaining_mAh / charge_current_mA) * 60`
- **SOC Accuracy**: Unable to reverse engineer true SOC at the time. Estimated SOC from cell voltage is default.

## Troubleshooting

### "Cannot connect"
- Ensure bike is **on** (press power button)
- Ensure bike is within **Bluetooth range**
- Check bike isn't paired to phone app simultaneously (only one at a time can connect)

### Sensors unavailable
- Bike must be **on/charging** to be connectable
- Increase poll interval if bike goes to sleep quickly

## Development
- Based on reverse-engineering of Velotric Tempo BLE protocol using android BLE packet capture and coding agent

## License
GPL v3
