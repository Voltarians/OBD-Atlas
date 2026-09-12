#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <iostream>
#include <string>

#include "../j2534_api.h"
#include "../programming_voltage_policy.h"

namespace {

unsigned long g_device_id = 0;
unsigned long g_pin_number = 0;
unsigned long g_voltage = 0;
unsigned long g_call_count = 0;
constexpr long kProviderResult = 0x1234;

long WINAPI FakeProgrammingVoltageProvider(
    unsigned long DeviceID,
    unsigned long PinNumber,
    unsigned long Voltage) {
  ++g_call_count;
  g_device_id = DeviceID;
  g_pin_number = PinNumber;
  g_voltage = Voltage;
  return kProviderResult;
}

int Fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

}  // namespace

int wmain() {
  using namespace atlas_j2534;
  constexpr wchar_t kVariable[] =
      L"OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE";

  SetEnvironmentVariableW(kVariable, nullptr);
  if (ProgrammingVoltageExplicitlyEnabled()) {
    return Fail("unset environment unexpectedly enabled programming voltage");
  }

  for (const wchar_t* rejected : {L"0", L"true", L"yes", L"01", L"1 "}) {
    SetEnvironmentVariableW(kVariable, rejected);
    if (ProgrammingVoltageExplicitlyEnabled()) {
      return Fail("non-canonical enable value was accepted");
    }
  }

  bool provider_called = true;
  const long blocked = ForwardProgrammingVoltageWithPolicy(
      false, FakeProgrammingVoltageProvider, 0x1234, 13, 12000,
      &provider_called);
  if (blocked != ERR_NOT_SUPPORTED || provider_called || g_call_count != 0) {
    return Fail("blocked programming-voltage call reached provider");
  }

  SetEnvironmentVariableW(kVariable, L"1");
  if (!ProgrammingVoltageExplicitlyEnabled()) {
    return Fail("exact enable value did not enable programming voltage");
  }

  provider_called = false;
  const long forwarded = ForwardProgrammingVoltageWithPolicy(
      ProgrammingVoltageExplicitlyEnabled(), FakeProgrammingVoltageProvider,
      0x1234, 13, 12000, &provider_called);
  if (forwarded != kProviderResult || !provider_called || g_call_count != 1) {
    return Fail("enabled programming-voltage call was not forwarded once");
  }
  if (g_device_id != 0x1234 || g_pin_number != 13 || g_voltage != 12000) {
    return Fail("programming-voltage arguments changed during forwarding");
  }

  provider_called = true;
  const long missing_provider = ForwardProgrammingVoltageWithPolicy(
      true, nullptr, 0x1234, 13, 12000, &provider_called);
  if (missing_provider != ERR_NOT_SUPPORTED || provider_called) {
    return Fail("missing provider did not fail closed");
  }

  SetEnvironmentVariableW(kVariable, nullptr);
  std::cout << "J2534 programming-voltage policy test passed\n";
  return 0;
}
