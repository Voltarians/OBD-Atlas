# J2534 programming-voltage safety policy

`PassThruSetProgrammingVoltage` is a higher-risk J2534 API because it can command a provider to drive a voltage on a selected connector pin. OBD Atlas therefore treats it differently from ordinary transparent observation/forwarding.

## Current stage

The safety policy and off-vehicle acceptance harness are implemented, but the proxy **does not yet export `PassThruSetProgrammingVoltage`**.

The policy code is compiled into the native Windows proxy so the eventual entry point can use the same tested primitive once this gate is green.

## Fail-closed rule

Programming-voltage forwarding is disabled unless the process environment contains exactly:

`OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE=1`

No other value enables it. In particular, `true`, `yes`, `01`, `1 `, an empty value, and an unset variable remain disabled.

When disabled:

- the provider programming-voltage function must not be called;
- the policy returns J2534 `ERR_NOT_SUPPORTED`;
- no pin or voltage command reaches the provider.

When explicitly enabled:

- Atlas does not clamp, reinterpret, rescale, synthesize, or substitute the requested voltage;
- the exact caller-supplied `DeviceID`, `PinNumber`, and `Voltage` are forwarded to the selected provider;
- the provider return code is returned unchanged.

If the selected provider does not expose the programming-voltage API, the policy fails closed with `ERR_NOT_SUPPORTED`.

## Why Atlas does not invent voltage limits

Different J2534 devices and applications may use provider-defined or standards-defined values for enabling, disabling, and selecting programming voltages. Atlas should not silently change a legitimate GM-tool request based on an invented generic limit. Safety is instead enforced by requiring deliberate operator enablement before transparent forwarding is possible.

The future trace record should preserve the requested pin and raw voltage value plus whether forwarding was allowed by policy. Atlas must not generate a programming-voltage call on its own.

## Off-vehicle acceptance test

`native/j2534_proxy/tests/programming_voltage_policy_test.cpp` proves:

1. programming voltage is disabled when the environment variable is absent;
2. non-canonical truthy values remain disabled;
3. a disabled call never invokes the provider callback;
4. an explicitly enabled call invokes the provider exactly once;
5. device ID, pin number, and voltage reach the provider unchanged;
6. the provider return code is preserved; and
7. a missing provider function fails closed.

This test is part of the Windows native CTest gate.

## Vehicle/programming boundary

Passing this policy test does **not** authorize an in-vehicle programming session. The next stage is to export `PassThruSetProgrammingVoltage`, resolve the real provider function, trace policy decisions, and compare direct-provider vs proxy behavior with a fake provider while keeping the fail-closed default.

After that, provider-specific bench testing and sustained-load timing equivalence are still required before Atlas is approved between SPS2/DPS/GDS2 and a real J2534 device.
