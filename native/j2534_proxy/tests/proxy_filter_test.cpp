#define WIN32_LEAN_AND_MEAN
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
  PassThruStartMsgFilterFn start_filter = nullptr;
  PassThruStopMsgFilterFn stop_filter = nullptr;
};

struct Result {
  long open_result = -1;
  long connect_result = -1;
  long start_result = -1;
  long rejected_start_result = -1;
  long stop_result = -1;
  long disconnect_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  unsigned long filter_id = 0;
  unsigned long rejected_filter_id = 0;
  bool filter_messages_unchanged = false;
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
  api.start_filter = reinterpret_cast<PassThruStartMsgFilterFn>(
      GetProcAddress(api.module, "PassThruStartMsgFilter"));
  api.stop_filter = reinterpret_cast<PassThruStopMsgFilterFn>(
      GetProcAddress(api.module, "PassThruStopMsgFilter"));
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.connect != nullptr && api.disconnect != nullptr &&
         api.start_filter != nullptr && api.stop_filter != nullptr;
}

PASSTHRU_MSG MakeMessage(const unsigned char (&payload)[4]) {
  PASSTHRU_MSG message{};
  message.ProtocolID = PROTOCOL_ISO15765;
  message.DataSize = 4;
  std::memcpy(message.Data, payload, 4);
  return message;
}

Result Run(const Api& api) {
  constexpr unsigned char kMaskData[4] = {0xFF, 0xFF, 0xFF, 0xFF};
  constexpr unsigned char kPatternData[4] = {0x00, 0x00, 0x07, 0xE8};
  constexpr unsigned char kFlowData[4] = {0x00, 0x00, 0x07, 0xE0};

  PASSTHRU_MSG mask = MakeMessage(kMaskData);
  PASSTHRU_MSG pattern = MakeMessage(kPatternData);
  PASSTHRU_MSG flow = MakeMessage(kFlowData);
  const PASSTHRU_MSG mask_before = mask;
  const PASSTHRU_MSG pattern_before = pattern;
  const PASSTHRU_MSG flow_before = flow;

  Result result;
  result.filter_id = 0xAAAAAAAA;
  result.rejected_filter_id = 0xDEADBEEF;
  result.open_result = api.open(nullptr, &result.device_id);
  result.connect_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 500000, &result.channel_id);
  result.start_result = api.start_filter(
      result.channel_id, FLOW_CONTROL_FILTER, &mask, &pattern, &flow,
      &result.filter_id);
  result.rejected_start_result = api.start_filter(
      result.channel_id, PASS_FILTER, &mask, &pattern, &flow,
      &result.rejected_filter_id);
  result.stop_result = api.stop_filter(result.channel_id, result.filter_id);
  result.disconnect_result = api.disconnect(result.channel_id);
  result.close_result = api.close(result.device_id);
  result.filter_messages_unchanged =
      std::memcmp(&mask, &mask_before, sizeof(mask)) == 0 &&
      std::memcmp(&pattern, &pattern_before, sizeof(pattern)) == 0 &&
      std::memcmp(&flow, &flow_before, sizeof(flow)) == 0;
  return result;
}

bool Equal(const Result& a, const Result& b) {
  return a.open_result == b.open_result &&
         a.connect_result == b.connect_result &&
         a.start_result == b.start_result &&
         a.rejected_start_result == b.rejected_start_result &&
         a.stop_result == b.stop_result &&
         a.disconnect_result == b.disconnect_result &&
         a.close_result == b.close_result && a.device_id == b.device_id &&
         a.channel_id == b.channel_id && a.filter_id == b.filter_id &&
         a.rejected_filter_id == b.rejected_filter_id &&
         a.filter_messages_unchanged == b.filter_messages_unchanged;
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
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-filter-ci");
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
    return Fail("usage: proxy_filter_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider filter API");
  const Result baseline = Run(direct);
  FreeLibrary(direct.module);

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) return Fail("GetTempPathW failed");
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_filter_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);
  ConfigureProxy(provider_path, trace_path);

  Api proxy = LoadApi(proxy_path);
  if (!Complete(proxy)) return Fail("could not load proxy filter API");
  const Result proxied = Run(proxy);

  if (!Equal(baseline, proxied)) {
    return Fail("proxied filter behavior does not match direct provider behavior");
  }
  if (proxied.open_result != STATUS_NOERROR ||
      proxied.connect_result != STATUS_NOERROR ||
      proxied.start_result != STATUS_NOERROR ||
      proxied.stop_result != STATUS_NOERROR ||
      proxied.disconnect_result != STATUS_NOERROR ||
      proxied.close_result != STATUS_NOERROR) {
    return Fail("valid filter lifecycle returned a non-success J2534 status");
  }
  if (proxied.rejected_start_result != ERR_NOT_SUPPORTED) {
    return Fail("rejected filter type did not preserve provider error status");
  }
  if (proxied.rejected_filter_id != 0xDEADBEEF) {
    return Fail("rejected filter call modified the caller filter-id buffer");
  }
  if (!proxied.filter_messages_unchanged) {
    return Fail("filter message structures were modified");
  }

  const std::string trace = ReadText(trace_path);
  if (trace.empty()) return Fail("proxy did not create a filter trace");
  if (CountLines(trace) != 15) {
    return Fail("expected session plus seven begin/end call pairs");
  }
  if (!Contains(trace, "\"api\":\"PassThruStartMsgFilter\"")) {
    return Fail("trace missing PassThruStartMsgFilter");
  }
  if (!Contains(trace, "\"api\":\"PassThruStopMsgFilter\"")) {
    return Fail("trace missing PassThruStopMsgFilter");
  }
  if (!Contains(trace, "\"filterType\":3")) {
    return Fail("trace missing flow-control filter type");
  }
  if (!Contains(trace, "\"payloadHex\":\"FFFFFFFF\"")) {
    return Fail("trace missing exact mask payload");
  }
  if (!Contains(trace, "\"payloadHex\":\"000007E8\"")) {
    return Fail("trace missing exact pattern payload");
  }
  if (!Contains(trace, "\"payloadHex\":\"000007E0\"")) {
    return Fail("trace missing exact flow-control payload");
  }
  if (!Contains(trace, "\"filterId\":13398")) {
    return Fail("trace missing provider-assigned filter ID");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 message filter transparency test passed\n";
  return 0;
}
