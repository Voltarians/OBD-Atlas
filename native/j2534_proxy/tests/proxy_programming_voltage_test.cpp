#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include "../j2534_api.h"

namespace {

using namespace atlas_j2534;
constexpr wchar_t kAllowVariable[] =
    L"OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE";
constexpr wchar_t kCalledVariable[] =
    L"OBD_ATLAS_FAKE_PROGRAMMING_VOLTAGE_CALLED";
constexpr unsigned long kDeviceId = 0x1234;
constexpr unsigned long kPin = 13;
constexpr unsigned long kVoltage = 12000;

PassThruSetProgrammingVoltageFn LoadVoltageApi(
    const std::filesystem::path& path, HMODULE* module) {
  *module = LoadLibraryW(path.c_str());
  if (*module == nullptr) return nullptr;
  return reinterpret_cast<PassThruSetProgrammingVoltageFn>(
      GetProcAddress(*module, "PassThruSetProgrammingVoltage"));
}

bool MarkerPresent() {
  wchar_t buffer[8]{};
  return GetEnvironmentVariableW(
             kCalledVariable, buffer, static_cast<DWORD>(std::size(buffer))) > 0;
}

std::string ReadText(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  std::ostringstream output;
  output << input.rdbuf();
  return output.str();
}

bool Contains(const std::string& text, const std::string& needle) {
  return text.find(needle) != std::string::npos;
}

int Fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return Fail(
        "usage: proxy_programming_voltage_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  SetEnvironmentVariableW(kCalledVariable, nullptr);
  HMODULE direct_module = nullptr;
  const auto direct_voltage = LoadVoltageApi(provider_path, &direct_module);
  if (direct_voltage == nullptr) {
    return Fail("could not load fake provider programming-voltage API");
  }
  const long direct_result = direct_voltage(kDeviceId, kPin, kVoltage);
  if (direct_result != STATUS_NOERROR || !MarkerPresent()) {
    return Fail("fake provider programming-voltage baseline failed");
  }
  FreeLibrary(direct_module);
  SetEnvironmentVariableW(kCalledVariable, nullptr);

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_programming_voltage_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-prog-voltage");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP_VERSION", L"1");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_NAME", L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_VENDOR", L"OBD Atlas CI");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH",
                          L"SOFTWARE\\PassThruSupport.04.04");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY",
                          L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT",
                          fingerprint.c_str());
  SetEnvironmentVariableW(kAllowVariable, nullptr);

  HMODULE proxy_module = nullptr;
  const auto proxy_voltage = LoadVoltageApi(proxy_path, &proxy_module);
  if (proxy_voltage == nullptr) {
    return Fail("could not load proxy programming-voltage API");
  }

  const long blocked = proxy_voltage(kDeviceId, kPin, kVoltage);
  if (blocked != ERR_NOT_SUPPORTED) {
    return Fail("default-blocked programming-voltage call returned wrong status");
  }
  if (MarkerPresent()) {
    return Fail("default-blocked programming-voltage call reached provider");
  }

  SetEnvironmentVariableW(kAllowVariable, L"1");
  const long enabled = proxy_voltage(kDeviceId, kPin, kVoltage);
  if (enabled != STATUS_NOERROR || !MarkerPresent()) {
    return Fail("explicitly enabled programming-voltage call was not forwarded");
  }

  SetEnvironmentVariableW(kCalledVariable, nullptr);
  const long provider_error = proxy_voltage(kDeviceId, kPin, kVoltage + 1);
  if (provider_error != ERR_INVALID_IOCTL_VALUE || !MarkerPresent()) {
    return Fail("provider programming-voltage error was not preserved");
  }

  const std::string trace = ReadText(trace_path);
  if (!Contains(trace, "\"api\":\"PassThruSetProgrammingVoltage\"")) {
    return Fail("trace missing PassThruSetProgrammingVoltage");
  }
  if (!Contains(trace,
                "\"pinNumber\":13,\"voltage\":12000,\"policyEnabled\":false")) {
    return Fail("trace missing default-blocked policy decision");
  }
  if (!Contains(trace,
                "\"pinNumber\":13,\"voltage\":12000,\"policyEnabled\":true")) {
    return Fail("trace missing enabled programming-voltage decision");
  }
  if (!Contains(trace, "\"providerCalled\":false") ||
      !Contains(trace, "\"providerCalled\":true")) {
    return Fail("trace missing provider-call policy evidence");
  }
  if (!Contains(trace, "\"voltage\":12001") ||
      !Contains(trace, "\"returnCode\":5")) {
    return Fail("trace missing preserved provider error case");
  }

  SetEnvironmentVariableW(kAllowVariable, nullptr);
  SetEnvironmentVariableW(kCalledVariable, nullptr);
  FreeLibrary(proxy_module);
  std::cout << "J2534 programming-voltage proxy test passed\n";
  return 0;
}
