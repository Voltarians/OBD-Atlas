# J2534 programming-voltage safety policy

`PassThruSetProgrammingVoltage` is a higher-risk J2534 API because it can command a provider to drive a voltage on a selected connector pin. OBD Atlas therefore treats it differently from ordinary transparent observation/forwarding.

## Current stage

The proxy now exports `PassThruSetProgrammingVoltage`, but forwarding is **blocked by default** behind a separately tested fail-closed policy.

The selected provider's programming-voltage function is resolved as optional. A provider that does not expose this API can still be used for ordinary diagnostic functions; programming-voltage calls simply fail closed.

## Fail-closed rule

Programming-voltage forwarding is disabled unless the process environment contains exactly:

`OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE=1`

No other value enables it. In particular, `true`, `yes`, `01`, `1 `, an empty value, and an unset variable remain disabled.

When disabled:

- the provider programming-voltage function is not called;
- the proxy returns J2534 `ERR_NOT_SUPPORTED`;
- no pin or voltage command reaches the provider;
- the trace still records the attempted request and the blocked policy decision.

When explicitly enabled:

- Atlas does not clamp, reinterpret, rescale, synthesize, or substitute the requested voltage;
- the exact caller-supplied `DeviceID`, `PinNumber`, and `Voltage` are forwarded to the selected provider;
- the provider return code is returned unchanged;
- the trace records that policy was enabled and whether the provider was actually invoked.

If the selected provider does not expose the programming-voltage API, the call fails closed with `ERR_NOT_SUPPORTED` even when the environment opt-in is present.

## Why Atlas does not invent voltage limits

Different J2534 devices and applications may use provider-defined or standards-defined values for enabling, disabling, and selecting programming voltages. Atlas should not silently change a legitimate GM-tool request based on an invented generic limit. Safety is instead enforced by requiring deliberate operator enablement before transparent forwarding is possible.

Atlas never generates a programming-voltage call on its own.

## Trace evidence

Each `PassThruSetProgrammingVoltage` call records:

- device ID through the normal J2534 call metadata;
- requested pin number;
- raw requested voltage value;
- whether programming-voltage policy was enabled;
- whether the selected provider exposes the API; and
- whether the provider was actually called.

This keeps blocked attempts visible without weakening the policy.

## Off-vehicle acceptance tests

`native/j2534_proxy/tests/programming_voltage_policy_test.cpp` proves the policy primitive:

1. programming voltage is disabled when the environment variable is absent;
2. non-canonical truthy values remain disabled;
3. a disabled call never invokes the provider callback;
4. an explicitly enabled call invokes the provider exactly once;
5. device ID, pin number, and voltage reach the provider unchanged;
6. the provider return code is preserved; and
7. a missing provider function fails closed.

`native/j2534_proxy/tests/proxy_programming_voltage_test.cpp` proves the exported proxy path:

1. the fake provider works directly with the expected device, pin, and voltage;
2. the default-blocked proxy call returns `ERR_NOT_SUPPORTED` and never reaches the provider;
3. exact opt-in enables forwarding;
4. provider-side argument validation proves the values arrive unchanged;
5. a provider error is returned unchanged; and
6. the trace records blocked/enabled policy state plus provider-called state.

Both tests are part of the Windows native CTest gate.

## Vehicle/programming boundary

Passing these off-vehicle tests does **not** authorize an in-vehicle programming session. Programming voltage must remain disabled during ordinary diagnostic observation.

Before Atlas is approved between SPS2/DPS/GDS2 and a real J2534 device for programming, we still require provider-specific bench testing, sustained-load/timing equivalence, periodic-message support where required, and fail-safe validation using the actual selected vendor DLL and interface.
