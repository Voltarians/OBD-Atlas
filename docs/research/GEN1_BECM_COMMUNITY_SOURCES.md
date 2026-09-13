# Gen-1 Volt/Ampera BECM community data sources

This file tracks community reverse-engineering inputs being incorporated into OBD Atlas for Gen-1 Chevrolet Volt / Opel Ampera battery research.

## Source: Tom-evnut/AmperaBattery

Repository: https://github.com/Tom-evnut/AmperaBattery
License: MIT
Original contributors listed by the project: Tom de Bree, Damian Maguire; further contributions by Liam O'Brien, swoozle, and jontscott.

### Confirmed architecture from the source

- Gen-1 scope: 2011-2015 Chevrolet Volt / Opel Ampera.
- BECM connector X1 exposes the car-facing 500 kbit/s CAN bus.
- BECM connector X2 exposes a separate 125 kbit/s internal BECM-to-slave/BICM CAN network.
- The source includes a DBC (`Volt_BMS.dbc`), raw master traffic (`Volt_BMS_Master.csv`), slave CAN captures, wiring/reference images, and two generations of decoder code.

### Data appropriate for Atlas

Use the source for:

- internal battery CAN IDs and byte layouts;
- 96 cell-group voltage mapping;
- thermistor mapping and scaling;
- BECM master/internal control traffic candidates;
- bus-rate and connector-layer distinction;
- validation targets for Atlas capture/import/DBC tooling.

Do **not** treat internal 125 kbit/s BICM IDs as car-facing 500 kbit/s HV Energy Management identifiers.

## Confidence policy

Imported/referenced signals should use one of these labels:

- `confirmed_source` — directly defined by source code/DBC and internally consistent.
- `community_derived` — documented by community reverse engineering but not yet independently validated by OBD Atlas.
- `candidate` — inferred or observed and awaiting a controlled capture.
- `atlas_verified` — independently reproduced on a known Gen-1 vehicle using OBD Atlas/PCG-1.

## Immediate contactor/precharge relevance

The community source is especially strong for cell/temperature/BICM data. It does not, by itself, establish verified car-facing IDs for positive contactor, negative contactor, or precharge state. Those remain controlled-capture targets on the 500 kbit/s HV Energy Management network.
