#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "j2534_api.h"
#include "programming_voltage_policy.h"

namespace atlas_j2534 {

namespace {
constexpr wchar_t kEnableVariable[] =
    L"OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE";
}

bool ProgrammingVoltageExplicitlyEnabled() {
  wchar_t buffer[8]{};
  const DWORD written = GetEnvironmentVariableW(
      kEnableVariable, buffer,
      static_cast<DWORD>(sizeof(buffer) / sizeof(buffer[0])));
  return written == 1 && buffer[0] == L'1' && buffer[1] == L'\0';
}

long ForwardProgrammingVoltageWithPolicy(
    bool enabled,
    ProgrammingVoltageProviderFn provider,
    unsigned long device_id,
    unsigned long pin_number,
    unsigned long voltage,
    bool* provider_called) {
  if (provider_called != nullptr) *provider_called = false;
  if (!enabled) return ERR_NOT_SUPPORTED;
  if (provider == nullptr) return ERR_NOT_SUPPORTED;

  if (provider_called != nullptr) *provider_called = true;
  return provider(device_id, pin_number, voltage);
}

}  // namespace atlas_j2534
