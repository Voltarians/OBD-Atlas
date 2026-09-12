#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include "../j2534_api.h"

namespace {

using namespace atlas_j2534;

struct Api {
  HMODULE module = nullptr;
  PassThruOpenFn open = nullptr;
  PassThruCloseFn close = nullptr;
  PassThruConnectFn connect = nullptr;
  PassThruDisconnectFn disconnect = nullptr;
  PassThruIoctlFn ioctl = nullptr;
};

struct IoctlResult {
  long open_result = -1;
  long connect_result = -1;
  long set_result = -1;
  long get_result = -1;
  long vbatt_result = -1;
  long invalid_result = -1;
  long disconnect_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  std::array<SCONFIG, 2> set_configs{};
  std::array<SCONFIG, 2> get_configs{};
  unsigned long battery_mv = 0;
  unsigned long invalid_input = 0;
  unsigned long invalid_output = 0;
};

Api LoadApi(const std::filesystem::path& path) {
  Api api;
  api.module = LoadLibraryW(path.c_str());
  if (api.module == nullptr) return api;
  api.open = reinterpret_cast<PassThruOpenFn>(
      GetProcAddress(api.module, "PassThruOpen"));
  api.close = reinterpret_cast<PassThruCloseFn>(
      GetProcAddress(api.module, "PassThruClose"));
  api.connect = reinterpret_cast<PassThruConnectFn>(
      GetProcAddress(api.module, "PassThruConnect"));
  api.disconnect = reinterpret_cast<PassThruDisconnectFn>(
      GetProcAddress(api.module, "PassThruDisconnect"));
  api.ioctl = reinterpret_cast<PassThruIoctlFn>(
      GetProcAddress(api.module, "PassThruIoctl"));
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.connect != nullptr && api.disconnect != nullptr &&
         api.ioctl != nullptr;
}

IoctlResult RunIoctl(const Api& api) {
  IoctlResult result;
  result.open_result = api.open(nullptr, &result.device_id);
  result.connect_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 500000, &result.channel_id);

  result.set_configs[0].Parameter = CONFIG_DATA_RATE;
  result.set_configs[0].Value = 500000;
  result.set_configs[1].Parameter = CONFIG_LOOPBACK;
  result.set_configs[1].Value = 1;
  SCONFIG_LIST set_list{
      static_cast<unsigned long>(result.set_configs.size()),
      result.set_configs.data()};
  result.set_result = api.ioctl(
      result.channel_id, IOCTL_SET_CONFIG, &set_list, nullptr);

  result.get_configs[0].Parameter = CONFIG_DATA_RATE;
  result.get_configs[0].Value = 0xAAAAAAAA;
  result.get_configs[1].Parameter = CONFIG_LOOPBACK;
  result.get_configs[1].Value = 0xBBBBBBBB;
  SCONFIG_LIST get_list{
      static_cast<unsigned long>(result.get_configs.size()),
      result.get_configs.data()};
  result.get_result = api.ioctl(
      result.channel_id, IOCTL_GET_CONFIG, &get_list, nullptr);

  result.battery_mv = 0xDEADBEEF;
  result.vbatt_result = api.ioctl(
      result.channel_id, IOCTL_READ_VBATT, nullptr, &result.battery_mv);

  result.invalid_input = 0x12345678;
  result.invalid_output = 0xCAFEBABE;
  result.invalid_result = api.ioctl(
      result.channel_id, 0xDEAD, &result.invalid_input, &result.invalid_output);

  result.disconnect_result = api.disconnect(result.channel_id);
  result.close_result = api.close(result.device_id);
  return result;
}

bool Equal(const IoctlResult& a, const IoctlResult& b) {
  return a.open_result == b.open_result &&
         a.connect_result == b.connect_result &&
         a.set_result == b.set_result && a.get_result == b.get_result &&
         a.vbatt_result == b.vbatt_result &&
         a.invalid_result == b.invalid_result &&
         a.disconnect_result == b.disconnect_result &&
         a.close_result == b.close_result && a.device_id == b.device_id &&
         a.channel_id == b.channel_id &&
         std::memcmp(a.set_configs.data(), b.set_configs.data(),
                     sizeof(a.set_configs)) == 0 &&
         std::memcmp(a.get_configs.data(), b.get_configs.data(),
                     sizeof(a.get_configs)) == 0 &&
         a.battery_mv == b.battery_mv &&
         a.invalid_input == b.invalid_input &&
         a.invalid_output == b.invalid_output;
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
    return Fail("usage: proxy_ioctl_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider IOCTL API");
  const IoctlResult baseline = RunIoctl(direct);
  FreeLibrary(direct.module);

  if (baseline.open_result != STATUS_NOERROR ||
      baseline.connect_result != STATUS_NOERROR ||
      baseline.set_result != STATUS_NOERROR ||
      baseline.get_result != STATUS_NOERROR ||
      baseline.vbatt_result != STATUS_NOERROR ||
      baseline.invalid_result != ERR_INVALID_IOCTL_ID ||
      baseline.disconnect_result != STATUS_NOERROR ||
      baseline.close_result != STATUS_NOERROR) {
    return Fail("fake provider returned unexpected IOCTL lifecycle status");
  }
  if (baseline.set_configs[0].Parameter != CONFIG_DATA_RATE ||
      baseline.set_configs[0].Value != 500000 ||
      baseline.set_configs[1].Parameter != CONFIG_LOOPBACK ||
      baseline.set_configs[1].Value != 1) {
    return Fail("SET_CONFIG input was unexpectedly modified");
  }
  if (baseline.get_configs[0].Parameter != CONFIG_DATA_RATE ||
      baseline.get_configs[0].Value != 500000 ||
      baseline.get_configs[1].Parameter != CONFIG_LOOPBACK ||
      baseline.get_configs[1].Value != 1) {
    return Fail("GET_CONFIG values are incorrect");
  }
  if (baseline.battery_mv != 12340) {
    return Fail("READ_VBATT value is incorrect");
  }
  if (baseline.invalid_input != 0x12345678 ||
      baseline.invalid_output != 0xCAFEBABE) {
    return Fail("invalid IOCTL modified opaque caller buffers");
  }

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_ioctl_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-ioctl");
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
  if (!Complete(proxy)) return Fail("could not load proxy IOCTL API");
  const IoctlResult proxied = RunIoctl(proxy);
  if (!Equal(baseline, proxied)) {
    return Fail("proxied IOCTL behavior differs from direct provider");
  }

  const std::string trace = ReadText(trace_path);
  if (!Contains(trace, "\"api\":\"PassThruIoctl\"")) {
    return Fail("trace missing PassThruIoctl");
  }
  if (!Contains(trace, "\"ioctlId\":2") ||
      !Contains(trace, "\"parameter\":1,\"value\":500000") ||
      !Contains(trace, "\"parameter\":3,\"value\":1")) {
    return Fail("trace missing SET_CONFIG contents");
  }
  if (!Contains(trace, "\"ioctlId\":1") ||
      !Contains(trace, "\"configInputAfter\"")) {
    return Fail("trace missing GET_CONFIG result snapshot");
  }
  if (!Contains(trace, "\"ioctlId\":3") ||
      !Contains(trace, "\"outputUnsignedLong\":12340")) {
    return Fail("trace missing READ_VBATT result");
  }
  if (!Contains(trace, "\"ioctlId\":57005") ||
      !Contains(trace, "\"returnCode\":15")) {
    return Fail("trace missing invalid IOCTL evidence");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 IOCTL transparency test passed\n";
  return 0;
}
