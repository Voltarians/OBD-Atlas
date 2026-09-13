# Gen-1 community CAN dataset

This directory contains normalized reverse-engineering data for the Gen-1 Chevrolet Volt / Opel Ampera battery system.

The first imported source is `Tom-evnut/AmperaBattery` (MIT). Data is normalized rather than copied blindly so Atlas can distinguish:

- 125 kbit/s internal BECM/BICM traffic;
- 500 kbit/s car-facing HV Energy Management traffic;
- directly decoded signals versus candidates awaiting Atlas validation.

See `docs/research/GEN1_BECM_COMMUNITY_SOURCES.md` for provenance and confidence rules.
