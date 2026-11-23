# Velotric E-Bike BLE Home Assistant Integration [beta]

Custom Home Assistant integration for Velotric e-bikes via Bluetooth LE proxy (ESPHome BLE proxy).

**Beta status:** Fully reverse-engineered from BLE packet captures, but only tested on one Velotric Tempo unit. Heavy use of coding agent.

---

## Status Legend

| Tag | Meaning |
|-----|---------|
| 🟢 | Working reliably |
| 🟡 | Working, needs testing/calibration |
| 🔴 | Not working / not yet implemented |

---

## Features

**Battery**
- Pack voltage & average cell voltage (🟢)
- Individual cell voltages (🟢)
- Real battery level (🔴 — not yet reverse engineered)
- Battery level estimated from cell voltage curve (🟢)
- Cell voltage delta (🟢 battery health)

**Status**
- BLE connected (🟢)
- Cable connected (🟢)
- Charging active (🟢)
- Charge time remaining (🟡 estimated)
- Actual charge current (🔴 — not yet reverse engineered)

**Riding**
- Trip distance/odometer (🔴 — not yet reverse engineered)

**Firmware Versions**
- Display (🟢)
- Motor Controller (🟢)
- Battery (🟢)
- Bluetooth (🟢)
- UI Display (🟢)
- Firmware Manager (🟢)

**Voltage Curve Calibration**
- Preset curve for Velotric Tempo (🟢)
- Custom JSON curve editor (🟡 buggy behavior)
- Calibrate at current SOC button (🟡 buggy behavior)

---

## Installation

### HACS (Recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add repository: `https://github.com/AutomateMyLifee/ha-velotric` (category: Integration)
3. Install "Velotric E-Bike", restart Home Assistant

### Manual

1. Copy `custom_components/velotric` to `config/custom_components/`
2. Restart Home Assistant

---

## Configuration

### Via UI

1. Settings → Devices & Services → Add Integration → "Velotric"
2. Enter your bike's **QR code** (from bike display) or **MAC address**
3. QR code format: `SERIAL##MAC##KEY`

### Notes

- Bike must be **on/charging** to connect
- Only 1 BLE connection at a time (phone app blocks HA)
- Increase poll interval if bike goes to sleep quickly

## Configuration Options

Settings → Devices & Services → Velotric → Configure

**Basic**
- **Poll Interval**: Seconds between polls (default: 120)
- **Battery Data Source**: "Tempo Voltage Curve" (estimated) or "Reported Battery Level" (bike's raw value)
- **Voltage Curve Preset**: Tempo Voltage Curve (default)

**Advanced Calibration**
- **Custom Charging Curve**: JSON voltage-SOC pairs
- **Custom Idle Curve**: JSON voltage-SOC pairs

**Calibrate at Current SOC**
1. Bike on and connected
2. Options → Calibrate at Current SOC
3. Enter SOC from bike display/app, select charging state
4. Curves auto-adjust

## Services

- `velotric.force_update` — force immediate data update
- `velotric.send_query` — send a specific query (battery, riding, charge, firmware)

## License

GPL v3
