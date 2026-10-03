# PCG-1 Promethean Core Gateway

This service exposes PCG-1 vehicle state to Promethean Core over newline-delimited JSON on TCP port 47001.

It is evidence-preserving: the service always sends heartbeat/link state, but it does not invent vehicle values. 12 V/APM fields appear only when a local decoder writes them to:

`/run/promethean/vehicle_state.json`

## Install on PCG-1

From the OBD-Atlas checkout:

```bash
sudo install -d /usr/local/lib/promethean
sudo install -m 0755 tool/pcg1_core_gateway.py /usr/local/lib/promethean/pcg1_core_gateway.py
sudo install -m 0644 systemd/promethean-pcg1-gateway.service /etc/systemd/system/promethean-pcg1-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now promethean-pcg1-gateway.service
```

Check it:

```bash
systemctl status promethean-pcg1-gateway.service --no-pager
ss -ltnp | grep 47001
journalctl -u promethean-pcg1-gateway.service -n 50 --no-pager
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


## Live 12-V voltage from vLinker MS

The current validated source for the 12-V card is SAE Mode 01 PID 0x42
(control-module voltage) read through the vLinker MS on the normal HS-CAN
DLC pins 6/14 path.

Multiple GM modules can answer PID 0x42 with slightly different local supply
measurements. PCG-1 publishes the median valid response as
`bus12_voltage_v`. This avoids selecting one ECU arbitrarily and preserves
the individual samples in the state file for evidence.

The vLinker MS used during this validation is:

- Bluetooth address: `08:04:B4:3F:41:BD`
- SPP/RFCOMM channel: `1`
- Linux device: `/dev/rfcomm0`
- serial rate: `115200`

Install the reader and optional RFCOMM reconnect service:

```bash
sudo install -m 0755 tool/pcg1_pid0142_reader.py /usr/local/lib/promethean/pcg1_pid0142_reader.py
sudo install -m 0644 systemd/promethean-pid0142.service /etc/systemd/system/promethean-pid0142.service
sudo install -m 0644 systemd/promethean-vlinker-ms-rfcomm.service /etc/systemd/system/promethean-vlinker-ms-rfcomm.service
sudo systemctl daemon-reload
sudo systemctl enable --now promethean-vlinker-ms-rfcomm.service
sudo systemctl enable --now promethean-pid0142.service
```

Check the live value:

```bash
journalctl -u promethean-pid0142.service -n 20 --no-pager
cat /run/promethean/vehicle_state.json
```

Expected state fields include:

```json
{
  "bus12_voltage_v": 13.533,
  "bus12_voltage_source": "sae_mode01_pid_0142_median",
  "bus12_pid0142_sample_count": 7,
  "bus12_pid0142_samples_v": [13.513,13.535,13.447,13.533,13.293,13.576,13.554]
}
```

Promethean Core already consumes `bus12_voltage_v`, so no HMI protocol change
is required for this value to appear in the **12 V BUS** card.

The PID 0x42 reader does not populate APM output voltage, current, power, or
state. Those remain unknown until separately validated from vehicle evidence.
