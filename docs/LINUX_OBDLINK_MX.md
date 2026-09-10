# OBDLink MX+ on Linux ARM64

OBD Atlas can use an OBDLink MX+ as a one-channel, receive-only CAN source on
Linux and Raspberry Pi ARM64. This does not replace the five-channel PCG-1
configuration: the MX+ monitors the single CAN protocol selected through its
ELM/OBDLink interface.

Atlas uses the STN `STM` command with raw ISO 11898 protocol 31 for 500-kbit/s
HS-CAN or protocol 61 for 33.3-kbit/s GM SWCAN, an explicit pass-all filter,
and `STCMM 0` silent monitoring. Spaces and the displayed DLC
are disabled to reduce Bluetooth bandwidth. Atlas reports `BUFFER FULL`,
`UART RX OVERFLOW`, `STOPPED`, and `NO DATA` as transport errors instead of
silently leaving a frozen frame counter. It does not send OBD requests,
acknowledge CAN frames, or transmit application CAN frames while this transport
is active.

## One-time Raspberry Pi setup

Install the BlueZ RFCOMM utility:

```bash
sudo apt update
sudo apt install -y bluez
sudo usermod -aG dialout "$USER"
```

Log out and back in after adding the `dialout` group. Pair the adapter using the
Raspberry Pi Bluetooth settings or `bluetoothctl`. Find the paired address with:

```bash
bluetoothctl devices Paired
```

Bind the MX+ serial service, replacing the example address:

```bash
sudo rfcomm bind 0 00:04:3E:12:34:56 1
ls -l /dev/rfcomm0
```

## Connect in Atlas

1. Open **Connect**.
2. Under **OBDLink MX+ • Bluetooth RFCOMM**, select **Scan serial ports**.
3. Select `/dev/rfcomm0` and the desired Atlas channel.
4. Select **HS-CAN** (DLC pins 6/14) or **SWCAN** (DLC pin 1).
5. Select **Monitor with MX+**.
6. Confirm that the selected channel reports frames before starting a capture.

Atlas uses protocol 31 (raw ISO 11898, 11-bit identifiers at 500 kbit/s) for
passive capture of the Gen-1 Chevrolet Volt primary diagnostic CAN bus. It uses
protocol 61 (raw ISO 11898, 11-bit identifiers at 33.3 kbit/s) for GM SWCAN on
DLC pin 1. The MX+ can monitor only one of these buses at a time.

Unfiltered HS-CAN may report `BUFFER FULL` when traffic exceeds Bluetooth
RFCOMM text-stream throughput. SWCAN's lower bus rate is expected to be more
sustainable, but must still pass the Atlas in-vehicle endurance test.

To remove the RFCOMM binding later:

```bash
sudo rfcomm release 0
```

## Scope and safety

- Receive-only monitoring; no diagnostic requests are issued.
- One selected CAN bus, not simultaneous five-network capture.
- Do not drive while operating the computer or reviewing capture results.
- Stop the Atlas connection before disconnecting the MX+ or turning off the car.
