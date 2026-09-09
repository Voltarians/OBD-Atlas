# OBDLink MX+ on Linux ARM64

OBD Atlas can use an OBDLink MX+ as a one-channel, receive-only CAN source on
Linux and Raspberry Pi ARM64. This does not replace the five-channel PCG-1
configuration: the MX+ monitors the single CAN protocol selected through its
ELM/OBDLink interface.

Atlas sends adapter configuration commands and `ATMA` (monitor all). It does
not send OBD requests or application CAN frames while this transport is active.

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
4. Select **Monitor with MX+**.
5. Confirm that the selected channel reports frames before starting a capture.

Atlas uses protocol 6 (ISO 15765-4, 11-bit identifiers at 500 kbit/s) for the
Gen-1 Chevrolet Volt primary diagnostic CAN bus.

To remove the RFCOMM binding later:

```bash
sudo rfcomm release 0
```

## Scope and safety

- Receive-only monitoring; no diagnostic requests are issued.
- One selected CAN bus, not simultaneous five-network capture.
- Do not drive while operating the computer or reviewing capture results.
- Stop the Atlas connection before disconnecting the MX+ or turning off the car.
