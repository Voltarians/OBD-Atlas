# Promethean Core status service (PCG-1)

Voltarian Phase 1 can read a small, read-only HTTP status document from PCG-1.

The service:

- does **not** open CAN sockets;
- does **not** change SocketCAN configuration;
- does **not** transmit CAN frames;
- reads existing Linux interface state and receive/error counters;
- always reports the Phase 1 transmit lane as locked.

## Bench check

From the OBD-Atlas repository on PCG-1:

```bash
python3 tool/promethean_core_status_server.py --once
```

The output schema is:

```text
promethean.core.status.v1
```

Verify that each expected CAN interface is present and that `listenOnly` is `true`
before using the result as Phase 1 evidence.

## Start the endpoint

For the current PCG-1 Ethernet setup:

```bash
cd ~/OBD-Atlas-main
python3 tool/promethean_core_status_server.py --bind 0.0.0.0 --port 8765
```

Voltarian's default endpoint field is:

```text
http://192.168.137.2:8765/v1/status
```

If PCG-1 has a different address, edit that field in Voltarian before pressing Refresh.

From another machine on the same network, the endpoint can be checked with:

```bash
curl http://192.168.137.2:8765/v1/status
```

## What Voltarian expects

Each response contains:

- capture timestamp;
- PCG-1 hostname, gateway identity, and OBD-Atlas Git version;
- VIM3 and HMI availability flags;
- transmit-lock state;
- SocketCAN interface name;
- bitrate;
- RX frame count;
- frame rate field;
- RX errors and overflows;
- listen-only state.

The initial server intentionally reports `framesPerSecond: 0.0`. A later sampling
pass can calculate live FPS from successive RX counters without opening or reading
the CAN socket directly.

## Vehicle test gate

Do not proceed to any future transmit work from this endpoint. Phase 1 is accepted
only when Voltarian shows:

- `CORE CONNECTED`;
- `TRANSMIT LANE LOCKED`;
- every active vehicle bus as `LISTEN ONLY`;
- expected bitrates/interfaces;
- no unexpected error or overflow growth.

The endpoint is status/evidence plumbing only.
