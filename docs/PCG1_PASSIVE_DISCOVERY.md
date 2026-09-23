# PCG-1 Passive Discovery Session

## Purpose

Turn PCG-1's verified multi-bus capture capability into a repeatable Atlas vehicle-discovery workflow. The first target vehicle is the 2013 Chevrolet Volt.

This phase is passive only. Atlas listens and inventories traffic; it does not transmit CAN frames.

## Discovery output

For every active interface and arbitration ID, Atlas shall retain:

- Atlas bus / logged interface
- configured bitrate and adapter/channel metadata when available
- arbitration ID and standard/extended format
- observed DLC
- frame count and calculated frame rate
- first and last timestamp
- mean period where meaningful
- byte transition/change statistics
- changing-byte count and activity score

The existing `sessions`, `buses`, `frames`, `id_metrics`, and `byte_metrics` tables are the canonical storage layer. Do not create a second incompatible discovery database.

## PCG-1 session workflow

1. Enumerate the configured PCG-1 receive interfaces.
2. Start all available buses as one logical Atlas session.
3. Capture without filters for the requested duration.
4. Import frames into the Atlas session database.
5. Compute ID and byte metrics.
6. Produce a concise bus/ID inventory sorted by bus then arbitration ID.
7. Preserve the session for later event correlation and DBC candidate generation.

An unavailable interface must be reported explicitly and must not silently invalidate captures from the remaining interfaces.

## First vehicle acceptance run

Vehicle: 2013 Chevrolet Volt.

Baseline: five minutes with the vehicle in a stable state and no deliberate control events.

Then run a separately marked event capture:

- wait 10 s
- left turn signal 10 s
- off 10 s
- right turn signal 10 s
- off 10 s
- hazard flashers 10 s
- off 10 s
- stop after 10 s

Brake and other controlled events can be added after the baseline/discovery gate passes.

## Acceptance criteria

The discovery gate passes when Atlas can:

1. create one session containing traffic from every available configured PCG-1 bus;
2. retain bus identity and timing for every imported frame;
3. produce per-ID and per-byte activity metrics without malformed-frame or sequence/storage errors;
4. save and reopen the session with the same bus and timing information;
5. expose the inventory as input to Atlas correlation and DBC workflows.

## Next phase

Compare the stable baseline with precisely timed event windows. Rank candidate arbitration IDs and bytes by correlation with each event, while retaining the originating bus. Candidate signals can then be promoted into the Atlas DBC workspace for human verification.
