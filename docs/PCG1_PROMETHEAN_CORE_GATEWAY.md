# PCG-1 Promethean Core Gateway

This service exposes PCG-1 vehicle state to Promethean Core over newline-delimited JSON on TCP port 47001.

It is evidence-preserving: the service always sends heartbeat/link state, but it does not invent vehicle values. 12 V/APM fields appear only when a local decoder writes them to:

`/run/promethean/vehicle_state.json`

## Install on PCG-1

From the OBD-Atlas checkout:

```bash
sudo install -d /usr/local/lib/promethean
sudo install -m 0755 tool/pcg1_direct_state_publisher.py /usr/local/lib/promethean/pcg1_direct_state_publisher.py
sudo install -m 0755 tool/pcg1_core_gateway.py /usr/local/lib/promethean/pcg1_core_gateway.py
sudo install -m 0644 systemd/promethean-pcg1-direct-state.service /etc/systemd/system/promethean-pcg1-direct-state.service
sudo install -m 0644 systemd/promethean-pcg1-gateway.service /etc/systemd/system/promethean-pcg1-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now promethean-pcg1-direct-state.service
sudo systemctl enable --now promethean-pcg1-gateway.service
```

Check it:

```bash
systemctl status promethean-pcg1-direct-state.service --no-pager
systemctl status promethean-pcg1-gateway.service --no-pager
ss -ltnp | grep 47001
journalctl -u promethean-pcg1-direct-state.service -n 50 --no-pager
journalctl -u promethean-pcg1-gateway.service -n 50 --no-pager
cat /run/promethean/vehicle_state.json
```

## State-file schema

A validated decoder can atomically write a JSON object such as:

```json
{
  "bus12_voltage_v": 12.64,
  "apm_output_voltage_v": 14.42,
  "apm_current_a": 18.7,
  "apm_power_w": 270.0,
  "apm_state": "ACTIVE"
}
```

Nested APM form is also accepted:

```json
{
  "data": {
    "bus12_voltage_v": 12.64,
    "apm": {
      "output_voltage_v": 14.42,
      "output_current_a": 18.7,
      "output_power_w": 270.0,
      "state": "ACTIVE"
    }
  }
}
```

Unknown fields are ignored. A malformed write does not replace the last valid state.

## Transport

The current development connection uses Wi-Fi:

- PCG-1: `192.168.10.242`
- Promethean Core VIM3: `192.168.10.239`

The protocol itself is ordinary TCP/IP so the later move to Ethernet does not require an application-protocol change.


## Persist the temporary Wi-Fi peer mapping

Install the NetworkManager dispatcher hook so PCG-1 restores the VIM3 neighbor entry after boot or DHCP renewal:

```bash
sudo install -m 0755 systemd/90-promethean-core-neighbor /etc/NetworkManager/dispatcher.d/90-promethean-core-neighbor
sudo /etc/NetworkManager/dispatcher.d/90-promethean-core-neighbor wlan0 up
ip neigh show dev wlan0
```

Promethean Core pins the reciprocal PCG-1 neighbor in its AAOS device configuration. Keep the PCG-1 Wi-Fi address reserved as `192.168.10.242` while this development workaround is in use.

## Vehicle-data source

PCG-1 itself is the permanent vehicle interface. Promethean Core does not require a vLinker, ELM/STN adapter, or Bluetooth/RFCOMM path.

The direct state publisher uses the verified mixed PCG-1 receive path rather than pretending every logical Atlas bus is a Linux SocketCAN interface. Atlas logical `can0` through `can3` are the four channels from the two LYS/UC2 USBCAN2 adapters through the ARM64 `libusbcan.so` API. Atlas logical `can4` is the RH02/candleLight SWCAN adapter exposed by Linux as SocketCAN `can0`. The sixth CAN-capable route remains reserved/assignable in the PCG-1 architecture and is not a sixth independent Volt DLC bus. Network-specific decoders remain scoped to the established Atlas logical networks: `can1` is Primary Powertrain and `can2` is HV Energy Management.

The production data path is:

```text
Volt CAN / SWCAN / LIN
        ↓
PCG-1 direct bus interfaces
        ↓
OBD Atlas / PCG-1 decoding
        ↓
/run/promethean/vehicle_state.json
        ↓
TCP 47001 newline-delimited JSON
        ↓
Promethean Core VIM3 HMI
```

Only values backed by PCG-1 vehicle evidence are written to the state file and forwarded to the HMI. Unknown values stay absent.

The gateway currently accepts these top-level fields for the Core dashboard:

```text
bus12_voltage_v
apm_output_voltage_v
apm_current_a
apm_power_w
apm_temperature_c
apm_state
dc_dc_state

hv_pack_voltage_v
hv_pack_current_a
hv_pack_power_kw
hv_soc_pct
hv_cell_min_v
hv_cell_max_v
hv_cell_delta_mv
hv_temp_min_c
hv_temp_max_c
isolation_kohm
hvil_state
contactor_state

drive_power_kw
regen_power_kw
charger_power_kw
charging_state

battery_coolant_temp_c
power_electronics_coolant_temp_c
engine_coolant_temp_c

motor_a_rpm
motor_b_rpm
drive_torque_nm
inverter_temperature_c
vehicle_speed_mph
drive_state

dtc_count
active_dtcs
network_modules_online
network_modules_expected
offline_modules
```

These fields are the PCG-1-to-HMI presentation contract. They do not imply that every decoder is already validated. Each field should appear only after Atlas/PCG-1 has a validated source for it.

## Core dashboard mapping

The intended Core cards consume the gateway fields directly:

- **Vehicle Health** — HV battery spread, 12-V status, isolation, DTC count, network/module status.
- **HV Battery** — pack voltage/current/power, SOC, cell min/max/delta, battery temperature, contactor/HVIL state.
- **12 V / APM** — 12-V bus, APM output voltage/current/power/temperature/state.
- **Energy Flow** — pack, drive, regen, charger and APM power.
- **Thermal** — battery, power-electronics and engine coolant temperatures.
- **DTC Health** — DTC count/list, isolation, HVIL and network status.
- **Drive Unit** — motor speeds, torque, inverter temperature and vehicle speed.

Wi-Fi is the current development transport. The planned Gigabit Ethernet link uses the same TCP/47001 protocol, so no HMI application-protocol change is required.


## Initial live direct-CAN card sources

The first evidence-backed values published without any diagnostic dongle are:

- **12 V / APM:** 0x1D4 command state/requested voltage and 0x1D6 APM sensed low-voltage, output current, calculated output power, temperatures, HV input current and counter. `bus12_voltage_v` comes directly from the validated 0x1D6 low-voltage sensed field.
- **HV Battery:** confirmed 0x210 pack voltage.
- **HV Battery cell health:** the 0x200/0x202/0x204/0x206 multiplex structure is accumulated across all 96 passive measurement slots; Core receives min, max, delta and the 96-slot vector only when all 96 slots have been observed.
- **Battery thermal:** 0x302 is accumulated into the nine passive temperature slots and Core receives min/max plus the nine-slot vector when both mux groups have been observed.
- **Network health:** the four UC2 channels plus the RH02 SWCAN channel are counted and timestamped under the established Atlas logical names `can0` through `can4`. The sixth CAN-capable route is reported as reserved rather than falsely opened as Linux `can5`.
- **BICM network:** the known 125 kbit/s BICM bus is located on the secondary DLC. It is tracked as a logical vehicle network while its exact concurrent acquisition route is kept separate until that routing is validated.

Candidate pack current and unvalidated APM/HV semantics remain excluded until their evidence gates are met.


## Future LIN expansion

Promethean Core reserves three future LIN channels as first-class PCG-1 inputs:

```text
lin0
lin1
lin2
```

They are not claimed as installed or active on the present PCG-1 hardware. The current gateway publishes:

```text
future_lin_interfaces_configured = 3
future_lin_interfaces_online = 0
future_lin_status = reserved_not_installed
```

When LIN transceivers and capture support are added, the same PCG-1 state pipeline will carry validated LIN-derived values into the HMI. LIN ownership remains on PCG-1; the VIM3 will not talk directly to LIN devices.

The eventual vehicle-network architecture is therefore:

```text
PCG-1 CAN-capable routing: 6 channels total
Current Volt acquisition: 4 UC2 CAN channels + 1 SWCAN channel
Known embedded/logical network: 125 kbit/s BICM on secondary DLC
Future expansion: 3 LIN channels
        ↓
PCG-1 acquisition / Atlas decoding
        ↓
normalized vehicle state
        ↓
TCP 47001
        ↓
Promethean Core HMI
```

Each LIN-derived value must preserve its source channel and remain absent until the corresponding signal has been validated.
