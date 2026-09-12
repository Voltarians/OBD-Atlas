#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "../j2534_api.h"

namespace {

using namespace atlas_j2534;

struct Api {
  HMODULE module = nullptr;
  PassThruOpenFn open = nullptr;
  PassThruCloseFn close = nullptr;
  PassThruReadVersionFn read_version = nullptr;
  PassThruGetLastErrorFn get_last_error = nullptr;
};

struct LifecycleResult {
  long open_result = -1;
  long read_version_result = -1;
  long get_last_error_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  std::string firmware;
  std::string dll_version;
  std::string api_version;
  std::string error_text;
};

Api LoadApi(const std::filesystem::path& path) {
  Api api;
  api.module = LoadLibraryW(path.c_str());
  if (api.module == nullptr) return api;
  api.open = reinterpret_cast<PassThruOpenFn>(
      GetProcAddress(api.module, "PassThruOpen"));
  api.close = reinterpret_cast<PassThruCloseFn>(
      GetProcAddress(api.module, "PassThruClose"));
  api.read_version = reinterpret_cast<PassThruReadVersionFn>(
      GetProcAddress(api.module, "PassThruReadVersion"));
  api.get_last_error = reinterpret_cast<PassThruGetLastErrorFn>(
      GetProcAddress(api.module, "PassThruGetLastError"));
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.read_version != nullptr && api.get_last_error != nullptr;
}

LifecycleResult RunLifecycle(const Api& api) {
  LifecycleResult result;
  char firmware[80]{};
  char dll_version[80]{};
  char api_version[80]{};
  char error_text[80]{};

  result.open_result = api.open(nullptr, &result.device_id);
  result.read_version_result = api.read_version(
      result.device_id, firmware, dll_version, api_version);
  result.get_last_error_result = api.get_last_error(error_text);
  result.close_result = api.close(result.device_id);

  result.firmware = firmware;
  result.dll_version = dll_version;
  result.api_version = api_version;
  result.error_text = error_text;
  return result;
}

bool Equal(const LifecycleResult& a, const LifecycleResult& b) {
  return a.open_result == b.open_result &&
         a.read_version_result == b.read_version_result &&
         a.get_last_error_result == b.get_last_error_result &&
         a.close_result == b.close_result && a.device_id == b.device_id &&
         a.firmware == b.firmware && a.dll_version == b.dll_version &&
         a.api_version == b.api_version && a.error_text == b.error_text;
}

std::string ReadText(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  std::ostringstream output;
  output << input.rdbuf();
  return output.str();
}

size_t CountLines(const std::string& text) {
  size_t count = 0;
  for (const char ch : text) {
    if (ch == '\n') ++count;
  }
  return count;
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
    return Fail("usage: proxy_lifecycle_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider API");
  const LifecycleResult baseline = RunLifecycle(direct);
  FreeLibrary(direct.module);

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_proxy_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP_VERSION", L"1");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_NAME", L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_VENDOR", L"OBD Atlas CI");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH",
                          L"SOFTWARE\\PassThruSupport.04.04");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY",
                          L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT",
                          fingerprint.c_str());

  Api proxy = LoadApi(proxy_path);
  if (!Complete(proxy)) return Fail("could not load proxy API");
  const LifecycleResult proxied = RunLifecycle(proxy);

  if (!Equal(baseline, proxied)) {
    return Fail("proxied lifecycle does not match direct provider behavior");
  }
  if (proxied.open_result != STATUS_NOERROR ||
      proxied.read_version_result != STATUS_NOERROR ||
      proxied.get_last_error_result != STATUS_NOERROR ||
      proxied.close_result != STATUS_NOERROR) {
    return Fail("fake lifecycle returned a non-success J2534 status");
  }

  const std::string trace = ReadText(trace_path);
  if (trace.empty()) return Fail("proxy did not create a trace");
  if (CountLines(trace) != 9) {
    return Fail("expected session plus four begin/end call pairs");
  }
  if (!Contains(trace, "\"recordType\":\"session\"")) {
    return Fail("trace session record missing");
  }
  if (!Contains(trace, "\"providerFingerprintSha256\":\"" +
                           std::string(64, 'a') + "\"")) {
    return Fail("provider fingerprint missing from trace");
  }
  for (const char* api_name : {"PassThruOpen", "PassThruReadVersion",
                               "PassThruGetLastError", "PassThruClose"}) {
    if (!Contains(trace, std::string("\"api\":\"") + api_name + "\"")) {
      return Fail(std::string("trace missing ") + api_name);
    }
  }
  if (!Contains(trace, "\"firmwareVersion\":\"FAKE-FW-1.0\"")) {
    return Fail("forwarded ReadVersion output missing from trace");
  }
  if (!Contains(trace, "\"errorDescription\":\"FAKE_OK\"")) {
    return Fail("forwarded GetLastError output missing from trace");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 lifecycle proxy transparency test passed\n";
  return 0;
}
