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
