# Gen-1 community CAN dataset

This directory contains normalized reverse-engineering data for the Gen-1 Chevrolet Volt / Opel Ampera battery system.

The first imported source is `Tom-evnut/AmperaBattery` (MIT). Data is normalized rather than copied blindly so Atlas can distinguish:

- 125 kbit/s internal BECM/BICM traffic;
- 500 kbit/s car-facing HV Energy Management traffic;
- directly decoded signals versus candidates awaiting Atlas validation.

## Network namespace rule

A CAN message is identified by the tuple `(network, bitrate_kbps, can_id_hex)`, never by CAN ID alone. Atlas data and tests must preserve the physical-network namespace before applying a decode.

This matters on Gen-1 Volt/Ampera data because the same numeric identifier can legitimately mean different things on different buses. For example, `0x460` is a cell-voltage message on the 125 kbit/s internal BECM/BICM bus, while `0x460` is also observed as a battery-coolant-temperature message on the 500 kbit/s HV Energy Management network.

See `docs/research/GEN1_BECM_COMMUNITY_SOURCES.md` for provenance and confidence rules.
