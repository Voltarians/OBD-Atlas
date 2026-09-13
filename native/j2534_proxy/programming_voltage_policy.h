#pragma once

#include <windows.h>

namespace atlas_j2534 {

using ProgrammingVoltageProviderFn = long(WINAPI*)(
    unsigned long DeviceID,
    unsigned long PinNumber,
    unsigned long Voltage);

// Programming voltage is intentionally fail-closed. The proxy may forward
// PassThruSetProgrammingVoltage only when the exact environment value is "1".
bool ProgrammingVoltageExplicitlyEnabled();

// Testable policy primitive used by the future exported proxy entry point.
// When disabled, the provider is not called and ERR_NOT_SUPPORTED is returned.
// When enabled, the exact caller-supplied values are forwarded unchanged.
long ForwardProgrammingVoltageWithPolicy(
    bool enabled,
    ProgrammingVoltageProviderFn provider,
    unsigned long device_id,
    unsigned long pin_number,
    unsigned long voltage,
    bool* provider_called = nullptr);

}  // namespace atlas_j2534
