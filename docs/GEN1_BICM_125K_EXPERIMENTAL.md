# Gen-1 Volt / Ampera internal BICM CAN — experimental

Status: **experimental, source-backed, not yet vehicle-verified by Atlas**

Scope: Chevrolet Volt / Opel Ampera **Gen-1 only**. Do not apply these definitions to Gen-2.

## Network

Community documentation identifies the internal BECM-to-BICM network on BECM connector X2 as **125 kbit/s CAN**. The existing Atlas research material is based primarily on `Tom-evnut/AmperaBattery`.

A second independent implementation, `yasko-pv/gw-ev`, communicates directly with Chevrolet Volt BICM modules and provides executable decoding logic for cell-voltage and temperature frames.

## Yasko voltage decode

The implementation treats voltage messages as IDs in the `0x4xx` family, with its slot arithmetic based at `0x460`. Atlas narrows the experimental decoder to `0x460..0x47F` until PCG-1 captures prove a broader range.

For each 2-byte pair:

```text
raw = ((byte0 & 0x0F) << 8) | byte1
volts = raw * 0.00125
```

CAN-ID ordering is interleaved:

```text
0x460..0x46F -> logical slots 0,2,4,...30
0x470..0x47F -> logical slots 1,3,5,...31
```

The source concatenates slot payloads and reverses the final sequence when populating its 96-cell array. Atlas preserves that behavior only as an experimental validation path.

## Yasko temperature decode

Yasko uses IDs `0x7E0..0x7EF`, but only decodes these indices:

- first 2-byte pair: `0x7E0`, `0x7E1`, `0x7E8`, `0x7EC`, `0x7ED`
- second 2-byte pair: `0x7E2`, `0x7E5`, `0x7E9`

Decode:

```text
raw = ((byteN & 0x0F) << 8) | byteN+1
temperature_C = 110.7 - raw * 0.0294
```

## Important discrepancy

The existing `Tom-evnut/AmperaBattery` DBC-derived Atlas research data contains a different temperature scale/offset. The two interpretations must **not** be silently merged.

Atlas therefore keeps the Yasko decoder tagged experimental until a known Gen-1 capture can be compared against:

1. plausible ambient/pack temperatures,
2. GDS2/BECM reported battery temperatures,
3. repeated 125-kbit/s captures across key-on and READY transitions.

## Passive-only policy

`lib/core/gen1_bicm_125k.dart` performs passive decoding only. It intentionally does **not** transmit the `0x200` query/control frame used by the external project. Active BICM commands remain out of scope until separately reviewed and validated.

## Validation target on PCG-1

Capture the internal battery network at 125 kbit/s and verify:

- recurring `0x460..0x47F` traffic,
- 12-bit values producing realistic ~3–4.2 V cell readings,
- exactly 96 reconstructed values for a full cycle,
- `0x7E0..0x7EF` traffic and which IDs actually carry temperatures,
- which temperature formula agrees with independent vehicle data.

Once confirmed, promote individual mappings from `experimental` to `verified` rather than promoting the whole family at once.

## Sources

- `yasko-pv/gw-ev`, `gw-ev.c` — direct BICM communication and executable decode logic.
- `Tom-evnut/AmperaBattery` — Gen-1 BECM/BICM wiring, 125-kbit/s internal-network documentation, DBC and captures.
