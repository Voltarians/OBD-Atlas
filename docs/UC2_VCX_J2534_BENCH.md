# UC2 / VCX J2534 isolated bench validation

OBD Atlas includes a narrow PCG-1 bench test for validating the physical and API path between a Windows J2534 VCX device and one UC2 channel on Linux ARM64.

## Purpose

The test proves both directions of this isolated path:

```
Windows J2534 application
        |
VXDIAG / VCX J2534 provider
        |
VCX hardware
        |
DLC passthrough pins 6 / 14
        |
UC2 device 0 CAN1
        |
PCG-1 / OBD Atlas
```

The current PCG-1 bench defaults are:

- UC2 device: `0`
- physical UC2 channel: `CAN1`
- CAN bitrate: `500000` bit/s
- DLC pair: pin 6 CAN-H / pin 14 CAN-L
- isolated-bench termination currently validated around 99 ohms across pins 6/14

The vehicle must remain disconnected while this active bench test is running.

## Built-in test

Run from the OBD Atlas checkout:

```bash
export OBD_ATLAS_USBCAN_LIB="$HOME/promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so"
python3 tool/uc2_vcx_bench.py --confirm-isolated-bench
```

The explicit confirmation flag is required because the tool places the selected UC2 controller in normal/active CAN mode so it can provide CAN acknowledgement. Without the flag, Atlas refuses to open the active test.

The test is deliberately not a general-purpose transmit utility. It waits for one exact standard-CAN request and sends one exact standard-CAN response.

## VCX request

The Windows VCX side sends one raw 500-kbit/s CAN message:

- CAN ID: `0x7E4`
- payload: `02 3E 00`

For a J2534 raw-CAN `PASSTHRU_MSG`, the message bytes are:

```
00 00 07 E4 02 3E 00
```

The first four bytes are the J2534 CAN identifier representation. The wire payload is `02 3E 00`.

## Atlas response

When Atlas receives the exact request, it sends one reply:

- CAN ID: `0x7EC`
- payload: `02 7E 00`

This is the positive TesterPresent response for the bench probe.

## Pass criteria

Atlas reports PASS only when all of the following are true:

1. `VCI_OpenDevice` succeeds.
2. UC2 device 0 CAN1 initializes at 500 kbit/s in active mode.
3. The exact standard frame `7E4#023E00` is received from the VCX.
4. `VCI_Transmit` accepts exactly one response frame.
5. Atlas transmits `7EC#027E00`.

The final Atlas message is:

```
PASS — VCX -> UC2 receive/ACK and UC2 -> VCX response path verified.
```

A timeout without the exact probe is a failure. Frames with the wrong ID, payload, extended-frame flag, or remote-frame flag are ignored and cannot satisfy the test.

## Safety boundary

This test exists only for an isolated two-node or controlled bench network. Do not connect it to the live vehicle while `--confirm-isolated-bench` is in use.

Normal Atlas UC2 vehicle capture remains passive/listen-only. The bench tool does not change the normal receive-only adapter configuration.

## Automated regression tests

`tests/test_uc2_vcx_bench.py` verifies:

- native ControlCAN structure layout
- 500-kbit/s timing values
- active-mode initialization for this bench tool
- exact request matching
- exact `0x7EC / 02 7E 00` response construction
- current PCG-1 defaults (device 0, CAN1, 500 kbit/s)
- pass status requires both request reception and successful response submission

These tests are part of the repository's standard Python CI suite.
