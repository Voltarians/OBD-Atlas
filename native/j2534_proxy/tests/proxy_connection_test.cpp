#define WIN32_LEAN_AND_MEAN
#include <windows.h>

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
};

struct ConnectionResult {
  long open_result = -1;
  long connect_result = -1;
  long disconnect_result = -1;
  long invalid_baud_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  unsigned long invalid_baud_channel_id = 0;
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
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.connect != nullptr && api.disconnect != nullptr;
}

ConnectionResult RunConnectionSequence(const Api& api) {
  ConnectionResult result;
  result.invalid_baud_channel_id = 0xDEADBEEF;
  result.open_result = api.open(nullptr, &result.device_id);
  result.connect_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 500000, &result.channel_id);
  result.disconnect_result = api.disconnect(result.channel_id);
  result.invalid_baud_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 250000,
      &result.invalid_baud_channel_id);
  result.close_result = api.close(result.device_id);
  return result;
}

bool Equal(const ConnectionResult& a, const ConnectionResult& b) {
  return a.open_result == b.open_result &&
         a.connect_result == b.connect_result &&
         a.disconnect_result == b.disconnect_result &&
         a.invalid_baud_result == b.invalid_baud_result &&
         a.close_result == b.close_result && a.device_id == b.device_id &&
         a.channel_id == b.channel_id &&
         a.invalid_baud_channel_id == b.invalid_baud_channel_id;
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

void ConfigureProxy(const std::filesystem::path& provider_path,
                    const std::filesystem::path& trace_path) {
  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-connect");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP_VERSION", L"1");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_NAME", L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_VENDOR", L"OBD Atlas CI");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH",
                          L"SOFTWARE\\PassThruSupport.04.04");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY",
                          L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT",
                          fingerprint.c_str());
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return Fail("usage: proxy_connection_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider connection API");
  const ConnectionResult baseline = RunConnectionSequence(direct);
  FreeLibrary(direct.module);

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_connection_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);
  ConfigureProxy(provider_path, trace_path);

  Api proxy = LoadApi(proxy_path);
  if (!Complete(proxy)) return Fail("could not load proxy connection API");
  const ConnectionResult proxied = RunConnectionSequence(proxy);

  if (!Equal(baseline, proxied)) {
    return Fail("proxied connection lifecycle differs from direct provider behavior");
  }
  if (proxied.open_result != STATUS_NOERROR ||
      proxied.connect_result != STATUS_NOERROR ||
      proxied.disconnect_result != STATUS_NOERROR ||
      proxied.invalid_baud_result != ERR_INVALID_BAUDRATE ||
      proxied.close_result != STATUS_NOERROR) {
    return Fail("connection lifecycle returned unexpected J2534 status");
  }
  if (proxied.invalid_baud_channel_id != 0xDEADBEEF) {
    return Fail("failed connect modified caller channel buffer");
  }

  const std::string trace = ReadText(trace_path);
  if (trace.empty()) return Fail("proxy did not create a connection trace");
  if (CountLines(trace) != 11) {
    return Fail("expected session plus five begin/end call pairs");
  }
  if (!Contains(trace, "\"api\":\"PassThruConnect\"")) {
    return Fail("trace missing PassThruConnect");
  }
  if (!Contains(trace, "\"api\":\"PassThruDisconnect\"")) {
    return Fail("trace missing PassThruDisconnect");
  }
  if (!Contains(trace, "\"protocolId\":6")) {
    return Fail("trace missing ISO15765 protocol ID");
  }
  if (!Contains(trace, "\"flags\":0")) {
    return Fail("trace missing connect flags");
  }
  if (!Contains(trace, "\"baudRate\":500000")) {
    return Fail("trace missing 500k baud rate");
  }
  if (!Contains(trace, "\"baudRate\":250000")) {
    return Fail("trace missing rejected baud rate");
  }
  if (!Contains(trace, "\"channelId\":9029")) {
    return Fail("trace missing provider channel ID");
  }
  if (!Contains(trace, "\"returnCode\":25")) {
    return Fail("trace missing invalid-baud return code");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 connection lifecycle transparency test passed\n";
  return 0;
}
