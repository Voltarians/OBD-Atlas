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
