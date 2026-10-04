# PCG-1 verified five-channel vehicle configuration

Status: **verified in-vehicle on 2026-09-07**

This is the authoritative installed wiring and OBD Atlas logical-channel record for the Raspberry Pi 5 PCG-1 capture system. It supersedes the earlier CA2/CANalyst-II and primary-DLC pins 2/10 working notes.

## Installed hardware

- Raspberry Pi 5, Linux ARM64
- UC2 / LYS USBCAN device 0: two high-speed CAN channels
- UC2 / LYS USBCAN device 1: two high-speed CAN channels
- RH02 candleLight/gs_usb: one SWCAN channel
- Vehicle-powered through the XY5008L
- CA2/CANalyst-II removed and replaced by the second UC2

## Verified logical and physical mapping

| Atlas channel | Capture name | Adapter | Vehicle connector | Pins and installed wire colors | Bitrate |
|---|---|---|---|---|---:|
| CH1 | `can0` | UC2 device 0 CAN0 | Auxiliary X84B | pin 3 CAN-H, purple; pin 11 CAN-L, yellow | 500,000 |
| CH2 | `can1` | UC2 device 0 CAN1 | Auxiliary X84B | pin 12 CAN-H, pink; pin 13 CAN-L, gray | 500,000 |
| CH3 | `can2` | UC2 device 1 CAN0 | Primary X84 | pin 12 CAN-H, pink; pin 13 CAN-L, gray | 500,000 |
| CH4 | `can3` | UC2 device 1 CAN1 | Primary X84 | pin 6 CAN-H, green; pin 14 CAN-L, green/white | 500,000 |
| CH5 | `can4` | RH02 SocketCAN `can0` | Primary X84 | pin 1 SWCAN, brown; pin 4 reference ground, orange | 33,333 |

Primary X84 pins 2/10 are not used for this five-channel CAN configuration. The earlier brown/white pin 2 and white pin 10 connection produced zero frames and was replaced by primary X84 pins 12/13.

## OBD Atlas launch

```bash
cd "$HOME/OBD-Atlas"
export OBD_ATLAS_USBCAN_LIB="$HOME/promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so"
./build/linux/arm64/release/bundle/obd_atlas
```

In the Linux interface:

1. Scan UC2 devices.
2. Connect **4 UC2 CAN → CH1–CH4**.
3. Connect RH02/SocketCAN as **CH5**.
4. Confirm all five counters increase before starting a capture.

## Verified capture

File: `atlas_capture_20260907_075515.log`

- Duration: 41.99 seconds
- Total frames: 229,976
- Malformed records: 0

| Capture channel | Frames |
|---|---:|
| `can0` | 31,807 |
| `can1` | 46,406 |
| `can2` | 24,779 |
| `can3` | 119,362 |
| `can4` | 7,622 |

All four UC2 channels and the RH02 SWCAN channel received frames simultaneously.

## Operational notes

- Close OBD Atlas before running `tool/diagnose-uc2-linux.py`.
- The native UC2 library can occasionally initialize a channel without useful receive traffic. Restarting OBD Atlas restored all five channels during validation.
- UC2 device numbers are assigned by the vendor library and are not yet locked to USB serial number or physical topology. Confirm counters after every restart.
- Shut down the Pi with `sudo shutdown -h now`, wait about 30 seconds, and only then remove vehicle power.


## Promethean Core five-bus service verification

Verified again in-vehicle on 2026-10-04 using the Promethean Core direct state publisher.

The service opened the UC2 pair successfully and simultaneously received traffic on all five physical vehicle buses:

- Atlas logical `can0`: live 500 kbit/s UC2 channel
- Atlas logical `can1`: live 500 kbit/s UC2 channel
- Atlas logical `can2`: live 500 kbit/s UC2 channel
- Atlas logical `can3`: live 500 kbit/s UC2 channel
- Atlas logical `can4`: live 33,333 bit/s RH02/candleLight SWCAN channel

The Core health contract reported:

```text
direct_can_interfaces_online = 5
physical_vehicle_buses_expected = 5
physical_vehicle_buses_with_traffic = 5
physical_vehicle_bus_health = all_expected_buses_live
```

This is the acceptance gate for the physical PCG-1 acquisition layer. Higher-level signal decoding remains independently evidence-gated.


## Degraded 2011 battery validation

The 2026-10-04 five-bus Core validation was performed on a badly degraded 2011 Chevrolet Volt. The low battery measurement-slot values observed during that session are vehicle evidence, not decoder artifacts.

The live Core state included:

- confirmed pack voltage approximately 362.375 V
- all 96 passive battery measurement slots populated
- minimum measurement slot 1.3625 V
- maximum measurement slot 3.88 V
- spread 2517.5 mV
- additional severely depressed slots including approximately 2.23 V and 2.67 V
- all nine passive battery temperature slots populated

Promethean Core and Voltarian must preserve and report these low measurements exactly as decoded. Do not clip, suppress, replace, or reject a measurement solely because it is outside the expected healthy-cell range. Missing/invalid transport evidence must be handled separately from a genuinely low measured voltage.


## Five physical plus one hidden bus model

Promethean Core must keep two counts distinct:

- **5 directly acquired physical vehicle buses**: four 500 kbit/s classic CAN buses plus one 33,333 bit/s SWCAN bus.
- **1 additional known hidden/internal vehicle bus**: the 125 kbit/s BICM/BECM internal CAN.

Therefore the current vehicle-network model is **5 directly acquired + 1 hidden/internal = 6 known vehicle buses**.

The hidden BICM/BECM bus is not counted in `physical_vehicle_buses_with_traffic` until PCG-1 has a validated direct acquisition route for it. It is also not the same thing as the reserved PCG-1 `can5` hardware channel. Those are separate architectural concepts.

Core telemetry exposes this explicitly as:

```text
physical_vehicle_buses_expected = 5
known_hidden_internal_buses = 1
total_known_vehicle_buses = 6
hidden_internal_bus_name = bicm_internal_125k
hidden_internal_bus_bitrate = 125000
hidden_internal_bus_status = known_internal_not_directly_acquired
```


## Validated signal-source buses

Live in-vehicle source-evidence captured on 2026-10-04 established these decoder source buses:

- APM / 12 V command and status: `can3`
  - `0x1D4` observed on `can3`
  - `0x1D6` observed on `can3`
- HV battery: `can2`
  - `0x210` observed on `can2`
  - `0x302` observed on `can2`
  - `0x200`, `0x202`, `0x204`, and `0x206` observed on `can2`

The `0x200/202/204/206` ID family also appears on other physical buses, proving that CAN ID alone is insufficient to select a decoder. Signal decoding must remain qualified by the validated physical source bus.
