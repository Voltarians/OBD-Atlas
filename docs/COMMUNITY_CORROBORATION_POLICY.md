# Community corroboration policy

Atlas distinguishes CAN knowledge that has been directly validated on a test vehicle from definitions that are strongly corroborated by independent community sources.

## Confidence tiers

- `confirmed`: directly validated by an Atlas-controlled capture or equivalent direct test, with the observed behavior matching the decode.
- `communityCorroborated`: not yet directly validated by Atlas, but at least three distinct source families agree on the signal definition.
- `candidate`: plausible or correlated, but not enough evidence exists for either higher tier.

A `communityCorroborated` definition is part of the usable Atlas knowledge database. It must remain visibly distinguishable from `confirmed` until a direct Atlas test promotes it.

## Three-source gate

A signal may be promoted to `communityCorroborated` only when at least three distinct source/project families agree on the material definition. Copies, mirrors, forks, vendored snapshots, generated copies of the same upstream DBC, and multiple files from one project count as one source family.

For a fully decoded signal, agreement should cover every field that materially affects the result:

- standard versus extended CAN identifier;
- CAN identifier;
- start bit / byte position;
- bit length;
- byte order;
- signedness;
- scale/factor;
- offset;
- engineering unit; and
- enum/value meaning when applicable.

If sources disagree on a material field, Atlas does not choose a majority definition automatically. The signal stays `candidate` or reference-only until the conflict is resolved.

Source lineage must be recorded with the signal. When apparent independent sources disclose that they copied or vendored another project, Atlas should collapse them into a single provenance family for the three-source count.

## Promotion

A later controlled Atlas capture can promote a `communityCorroborated` signal to `confirmed`. The community provenance should be retained after promotion.

## First application: Gen-1 Volt charger

The first application of this policy covers the Gen-1 Chevrolet Volt / Opel Ampera charger. Exact decode agreement was found across the OpenDBC GM high-voltage database, Damien Maguire's AmperaCharger implementation, and additional working community implementations/documentation. The imported set covers `0x212` charger DC telemetry, `0x304` requested current/voltage, and `0x30E` charger mode.

`0x30A` AC-input telemetry is deliberately not promoted under this policy because the available definitions are not sufficiently consistent.
