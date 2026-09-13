#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

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
  PassThruStartPeriodicMsgFn start = nullptr;
  PassThruStopPeriodicMsgFn stop = nullptr;
};

struct Result {
  long open_result = -1;
  long connect_result = -1;
  long start_result = -1;
  long bad_interval_result = -1;
  long stop_result = -1;
  long bad_stop_result = -1;
  long disconnect_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  unsigned long periodic_id = 0;
  unsigned long bad_interval_id = 0;
  PASSTHRU_MSG message{};
  PASSTHRU_MSG message_after{};
};

Api LoadApi(const std::filesystem::path& path) {
  Api api;
  api.module = LoadLibraryW(path.c_str());
  if (api.module == nullptr) return api;
  api.open = reinterpret_cast<PassThruOpenFn>(GetProcAddress(api.module, "PassThruOpen"));
  api.close = reinterpret_cast<PassThruCloseFn>(GetProcAddress(api.module, "PassThruClose"));
  api.connect = reinterpret_cast<PassThruConnectFn>(GetProcAddress(api.module, "PassThruConnect"));
  api.disconnect = reinterpret_cast<PassThruDisconnectFn>(GetProcAddress(api.module, "PassThruDisconnect"));
  api.start = reinterpret_cast<PassThruStartPeriodicMsgFn>(
      GetProcAddress(api.module, "PassThruStartPeriodicMsg"));
  api.stop = reinterpret_cast<PassThruStopPeriodicMsgFn>(
      GetProcAddress(api.module, "PassThruStopPeriodicMsg"));
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.connect != nullptr && api.disconnect != nullptr &&
         api.start != nullptr && api.stop != nullptr;
}

PASSTHRU_MSG MakePeriodicMessage() {
  PASSTHRU_MSG message{};
  message.ProtocolID = PROTOCOL_ISO15765;
  message.RxStatus = 0;
  message.TxFlags = 0;
  message.Timestamp = 0;
  constexpr unsigned char payload[] = {
      0x00, 0x00, 0x07, 0xE0, 0x02, 0x3E, 0x00};
  message.DataSize = static_cast<unsigned long>(sizeof(payload));
  message.ExtraDataIndex = 0;
  std::memcpy(message.Data, payload, sizeof(payload));
  return message;
}

Result Run(const Api& api) {
  Result result;
  result.message = MakePeriodicMessage();
  result.message_after = result.message;
  result.open_result = api.open(nullptr, &result.device_id);
  result.connect_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 500000, &result.channel_id);

  result.periodic_id = 0xAAAAAAAA;
  result.start_result = api.start(
      result.channel_id, &result.message_after, &result.periodic_id, 1000);

  result.bad_interval_id = 0xCAFEBABE;
  result.bad_interval_result = api.start(
      result.channel_id, &result.message_after, &result.bad_interval_id, 0);

  result.stop_result = api.stop(result.channel_id, result.periodic_id);
  result.bad_stop_result = api.stop(result.channel_id, 0xDEADBEEF);
  result.disconnect_result = api.disconnect(result.channel_id);
  result.close_result = api.close(result.device_id);
  return result;
}

bool Equal(const Result& a, const Result& b) {
  return a.open_result == b.open_result &&
         a.connect_result == b.connect_result &&
         a.start_result == b.start_result &&
         a.bad_interval_result == b.bad_interval_result &&
         a.stop_result == b.stop_result &&
         a.bad_stop_result == b.bad_stop_result &&
         a.disconnect_result == b.disconnect_result &&
         a.close_result == b.close_result &&
         a.device_id == b.device_id && a.channel_id == b.channel_id &&
         a.periodic_id == b.periodic_id &&
         a.bad_interval_id == b.bad_interval_id &&
         std::memcmp(&a.message_after, &b.message_after, sizeof(PASSTHRU_MSG)) == 0;
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
    return Fail("usage: proxy_periodic_msg_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider periodic API");
  const Result baseline = Run(direct);
  FreeLibrary(direct.module);

  if (baseline.open_result != STATUS_NOERROR ||
      baseline.connect_result != STATUS_NOERROR ||
      baseline.start_result != STATUS_NOERROR ||
      baseline.bad_interval_result != ERR_INVALID_TIME_INTERVAL ||
      baseline.stop_result != STATUS_NOERROR ||
      baseline.bad_stop_result != ERR_INVALID_MSG_ID ||
      baseline.disconnect_result != STATUS_NOERROR ||
      baseline.close_result != STATUS_NOERROR) {
    return Fail("fake provider returned unexpected periodic lifecycle status");
  }
  if (baseline.periodic_id != 0x4567) {
    return Fail("fake provider returned unexpected periodic message ID");
  }
  if (baseline.bad_interval_id != 0xCAFEBABE) {
    return Fail("rejected periodic start changed caller output ID");
  }
  if (std::memcmp(&baseline.message, &baseline.message_after,
                  sizeof(PASSTHRU_MSG)) != 0) {
    return Fail("fake provider modified periodic message input");
  }

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) return Fail("GetTempPathW failed");
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_periodic_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-periodic");
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
  if (!Complete(proxy)) return Fail("could not load proxy periodic API");
  const Result proxied = Run(proxy);
  if (!Equal(baseline, proxied)) {
    return Fail("proxied periodic behavior differs from direct provider");
  }
  if (std::memcmp(&proxied.message, &proxied.message_after,
                  sizeof(PASSTHRU_MSG)) != 0) {
    return Fail("proxy modified periodic message input");
  }

  const std::string trace = ReadText(trace_path);
  if (!Contains(trace, "\"api\":\"PassThruStartPeriodicMsg\"") ||
      !Contains(trace, "\"api\":\"PassThruStopPeriodicMsg\"")) {
    return Fail("trace missing periodic API calls");
  }
  if (!Contains(trace, "\"timeIntervalMs\":1000") ||
      !Contains(trace, "\"payloadHex\":\"000007E0023E00\"") ||
      !Contains(trace, "\"messageId\":17767")) {
    return Fail("trace missing periodic start evidence");
  }
  if (!Contains(trace, "\"timeIntervalMs\":0") ||
      !Contains(trace, "\"returnCode\":11")) {
    return Fail("trace missing invalid interval evidence");
  }
  if (!Contains(trace, "\"messageId\":3735928559") ||
      !Contains(trace, "\"returnCode\":13")) {
    return Fail("trace missing invalid periodic stop evidence");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 periodic message transparency test passed\n";
  return 0;
}
