#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <filesystem>
#include <iostream>
#include <string>

#include "../j2534_api.h"

namespace {

int Fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return Fail("usage: proxy_invalid_config_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_proxy_invalid_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL",
                          provider_path.wstring().c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH",
                          trace_path.wstring().c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT", L"bad");

  HMODULE proxy = LoadLibraryW(proxy_path.c_str());
  if (proxy == nullptr) return Fail("could not load proxy DLL");
  const auto open = reinterpret_cast<atlas_j2534::PassThruOpenFn>(
      GetProcAddress(proxy, "PassThruOpen"));
  if (open == nullptr) return Fail("PassThruOpen export missing");

  unsigned long device_id = 0;
  const long result = open(nullptr, &device_id);
  if (result != atlas_j2534::ERR_FAILED) {
    return Fail("proxy did not fail closed on invalid provider fingerprint");
  }
  if (std::filesystem::exists(trace_path)) {
    return Fail("invalid configuration unexpectedly created a trace");
  }

  FreeLibrary(proxy);
  std::cout << "J2534 invalid provider identity test passed\n";
  return 0;
}
