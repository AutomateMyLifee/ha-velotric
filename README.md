# Velotric E-Bike BLE Home Assistant Integration [beta]

Custom Home Assistant integration for Velotric e-bikes via Bluetooth LE proxy (ESPHome BLE proxy).

**Beta status:** Fully reverse-engineered from BLE packet captures, but only tested on one Velotric Tempo unit.

---

## Status Legend

| Tag | Meaning |
|-----|---------|
| 🟢 | Working reliably |
| 🟡 | Working, needs testing/calibration |
| 🔴 | Not working / not yet implemented |

---

## Working Features

**Battery**
- Pack voltage & average cell voltage
- 10 individual cell voltages
- Battery level estimated from cell voltage curve (🟢)
- Battery level reported by bike protocol (🟡 — values not accurate, still testing)
- Charge current (raw, needs calibration)
- Cell voltage delta (highest − lowest cell)

**Riding**
- Trip distance (trip meter, resets per ride) (🟡 — not yet reverse engineered)

**Firmware (all ✅ working)**
- Display
- Motor Controller
- Battery (BMS)
- Bluetooth
- UI Display
- Firmware Manager

**Charge Status**
- Cable connected (🟢)
- Charging active (🟢)
- Actual charge current (raw, needs calibration)

**Voltage Curve Calibration**
- Preset curve for Velotric Tempo (🟢)
- Custom JSON curve editor
- Calibrate at current SOC button

---

## Known Limitations

- **Total odometer**: Not implemented — unable to reverse engineer at time of writing
- **Charge time remaining**: Not transmitted by bike; calculate in HA: `(remaining_mAh / charge_current_mA) * 60`
- **Battery level reported by bike**: Current values not accurate — use voltage-estimated SOC instead
- **Trip distance**: Trip meter not yet reverse engineered
- **Cell voltage values**: Verify cell voltage readings with `/DEBUG` before relying on them

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
