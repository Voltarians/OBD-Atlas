# MX+ Linux branch-cluster consolidation audit

Target: current-main-based `feature/pcg1-passive-discovery`

Audited source branches:

- `feature/linux-mxplus`
- `feature/mxplus-fast-monitor`
- `feature/mxplus-swcan`
- `fix/linux-mxplus-rfcomm-crash`
- `fix/mxplus-linux-autoconnect`
- `fix/mxplus-raw-stm-monitor`

## Result

The current target already contains the combined, newer MX+ implementation rather than any one stale branch version.

Current `lib/adapters/linux_obdlink_mx_adapter.dart` includes:

- Python-owned RFCOMM transport to avoid the ARM64 libserialport crash path.
- Discovery of both manually bound `/dev/rfcommN` ports and paired BlueZ MX+ devices.
- Direct `rfcomm://MAC:channel` socket connection, eliminating mandatory manual rfcomm binding.
- Fast raw `STM` monitoring.
- HS-CAN protocol 31 preset.
- GM SWCAN protocol 61 preset plus `STCSWM 3`.
- `STCMM 0` silent monitoring and pass-all filtering.
- compact `ATS0` / `ATD0` stream parsing.
- 11-bit and 29-bit monitor parsing.
- explicit BUFFER FULL, UART RX OVERFLOW, STOPPED, and NO DATA handling.
- first-valid-frame connection gate.
- connection/command logging that cannot terminate the transport.

Current tests cover bus presets, direct paired-device discovery, compact STM frames,
11/29-bit parsing, terminal errors, malformed lines, and channel validation.

The current documentation also describes direct paired-device operation, HS-CAN/SWCAN
selection, raw STM mode, buffer limitations, and the first-frame gate.

## Supersession map

- `feature/linux-mxplus`: foundation incorporated and extended.
- `feature/mxplus-fast-monitor`: incorporated and extended.
- `feature/mxplus-swcan`: incorporated.
- `fix/linux-mxplus-rfcomm-crash`: incorporated through Python-owned RFCOMM transport.
- `fix/mxplus-linux-autoconnect`: current adapter is byte-identical to this branch's adapter implementation and adds the associated current tests/docs.
- `fix/mxplus-raw-stm-monitor`: raw STM parsing/error handling incorporated and subsequently extended by SWCAN/autoconnect/first-frame handling.

Do not merge these stale branches wholesale. Their relevant functionality is already
present in current main-derived code.

## Remaining gate

Run current CI and hardware acceptance against the consolidated implementation. In
particular, preserve the known engineering distinction: SWCAN is suitable for sustained
MX+ monitoring, while unrestricted HS-CAN over Bluetooth RFCOMM can reach BUFFER FULL.
That behavior is a transport limit to report, not a reason to regress to an older branch.
