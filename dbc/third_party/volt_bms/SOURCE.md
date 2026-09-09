# Gen-1 Volt/Ampera battery DBC

This directory contains an unmodified third-party DBC for the internal
125-kbit/s CAN network between the Gen-1 Chevrolet Volt/Opel Ampera BECM and
its four battery monitoring modules.

- Upstream: https://github.com/damienmaguire/AmperaBattery
- Upstream file: `Volt_BMS.dbc`
- License: MIT, copyright 2018 Damien Maguire
- Downloaded: 2026-09-02
- SHA-256: `b5f3e6016e4c4ce18381f2ef466b07831aa81503acb67a195bc75ecbb06cb872`
- Atlas import result: 39 messages, 112 signals, 4 nodes

## Scope warning

This is not a complete Chevrolet Volt, Opel Ampera, or Cadillac ELR vehicle
DBC. It describes the battery module network exposed at the BECM X2 connector.
Do not apply it indiscriminately to the vehicle's high-speed, low-speed, or
single-wire CAN networks.

## Import

```bash
python3 atlas.py dbc-import dbc/third_party/volt_bms/Volt_BMS.dbc \\
  --database obd_atlas.sqlite3 --name gen1-volt-bms-internal
```
