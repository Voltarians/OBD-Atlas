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
  PassThruReadMsgsFn read_msgs = nullptr;
};

struct ReadResult {
  long open_result = -1;
  long connect_result = -1;
  long read_result = -1;
  long timeout_result = -1;
  long disconnect_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  unsigned long read_count = 0;
  unsigned long timeout_count = 0;
  std::array<PASSTHRU_MSG, 4> read_messages{};
  std::array<PASSTHRU_MSG, 2> timeout_messages{};
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
  api.read_msgs = reinterpret_cast<PassThruReadMsgsFn>(
      GetProcAddress(api.module, "PassThruReadMsgs"));
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.connect != nullptr && api.disconnect != nullptr &&
         api.read_msgs != nullptr;
}

ReadResult RunRead(const Api& api) {
  ReadResult result;
  std::memset(result.read_messages.data(), 0xA5,
              sizeof(result.read_messages));
  std::memset(result.timeout_messages.data(), 0x5A,
              sizeof(result.timeout_messages));

  result.open_result = api.open(nullptr, &result.device_id);
  result.connect_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 500000, &result.channel_id);

  result.read_count = static_cast<unsigned long>(result.read_messages.size());
  result.read_result = api.read_msgs(
      result.channel_id, result.read_messages.data(), &result.read_count, 100);

  result.timeout_count =
      static_cast<unsigned long>(result.timeout_messages.size());
  result.timeout_result = api.read_msgs(
      result.channel_id, result.timeout_messages.data(), &result.timeout_count,
      0);

  result.disconnect_result = api.disconnect(result.channel_id);
  result.close_result = api.close(result.device_id);
  return result;
}

bool Equal(const ReadResult& a, const ReadResult& b) {
  return a.open_result == b.open_result &&
         a.connect_result == b.connect_result &&
         a.read_result == b.read_result &&
         a.timeout_result == b.timeout_result &&
         a.disconnect_result == b.disconnect_result &&
         a.close_result == b.close_result && a.device_id == b.device_id &&
         a.channel_id == b.channel_id && a.read_count == b.read_count &&
         a.timeout_count == b.timeout_count &&
         std::memcmp(a.read_messages.data(), b.read_messages.data(),
                     sizeof(a.read_messages)) == 0 &&
         std::memcmp(a.timeout_messages.data(), b.timeout_messages.data(),
                     sizeof(a.timeout_messages)) == 0;
}

bool MessageMatches(const PASSTHRU_MSG& message, unsigned long rx_status,
                    unsigned long timestamp, const unsigned char* data,
                    size_t data_size) {
  return message.ProtocolID == PROTOCOL_ISO15765 &&
         message.RxStatus == rx_status && message.TxFlags == 0 &&
         message.Timestamp == timestamp && message.DataSize == data_size &&
         message.ExtraDataIndex == data_size &&
         std::memcmp(message.Data, data, data_size) == 0;
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
    return Fail("usage: proxy_read_msgs_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider read API");
  const ReadResult baseline = RunRead(direct);
  FreeLibrary(direct.module);

  constexpr unsigned char kMessage0[] = {
      0x00, 0x00, 0x07, 0xE8, 0x03, 0x62, 0x43, 0x56};
  constexpr unsigned char kMessage1[] = {
      0x00, 0x00, 0x07, 0xE8, 0x04, 0x62, 0x43, 0xAF, 0x80};
  if (baseline.open_result != STATUS_NOERROR ||
      baseline.connect_result != STATUS_NOERROR ||
      baseline.read_result != STATUS_NOERROR || baseline.read_count != 2 ||
      baseline.timeout_result != ERR_TIMEOUT || baseline.timeout_count != 0 ||
      baseline.disconnect_result != STATUS_NOERROR ||
      baseline.close_result != STATUS_NOERROR) {
    return Fail("fake provider returned unexpected read lifecycle status");
  }
  if (!MessageMatches(baseline.read_messages[0], 0x00000001, 1000,
                      kMessage0, sizeof(kMessage0)) ||
      !MessageMatches(baseline.read_messages[1], 0x00000002, 1010,
                      kMessage1, sizeof(kMessage1))) {
    return Fail("fake provider returned unexpected message contents");
  }

  std::array<PASSTHRU_MSG, 2> timeout_sentinel{};
  std::memset(timeout_sentinel.data(), 0x5A, sizeof(timeout_sentinel));
  if (std::memcmp(baseline.timeout_messages.data(), timeout_sentinel.data(),
                  sizeof(timeout_sentinel)) != 0) {
    return Fail("timeout read unexpectedly modified the message buffer");
  }

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_read_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-read");
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
  if (!Complete(proxy)) return Fail("could not load proxy read API");
  const ReadResult proxied = RunRead(proxy);
  if (!Equal(baseline, proxied)) {
    return Fail("proxied ReadMsgs behavior differs from direct provider");
  }

  const std::string trace = ReadText(trace_path);
  if (!Contains(trace, "\"api\":\"PassThruReadMsgs\"")) {
    return Fail("trace missing PassThruReadMsgs");
  }
  if (!Contains(trace,
                "\"requestedMessageCount\":4,\"timeoutMs\":100")) {
    return Fail("trace missing successful read request metadata");
  }
  if (!Contains(trace,
                "\"returnedMessageCount\":2,\"capturedMessageCount\":2")) {
    return Fail("trace missing successful read result counts");
  }
  if (!Contains(trace, "000007E803624356") ||
      !Contains(trace, "000007E8046243AF80")) {
    return Fail("trace missing returned read payloads");
  }
  if (!Contains(trace,
                "\"requestedMessageCount\":2,\"timeoutMs\":0")) {
    return Fail("trace missing timeout read request metadata");
  }
  if (!Contains(trace, "\"returnCode\":9") ||
      !Contains(trace,
                "\"returnedMessageCount\":0,\"capturedMessageCount\":0")) {
    return Fail("trace missing timeout result metadata");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 ReadMsgs transparency test passed\n";
  return 0;
}
