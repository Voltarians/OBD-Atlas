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
  PassThruWriteMsgsFn write_msgs = nullptr;
};

struct WriteResult {
  long open_result = -1;
  long connect_result = -1;
  long ordinary_result = -1;
  long security_result = -1;
  long transfer_result = -1;
  long timeout_result = -1;
  long disconnect_result = -1;
  long close_result = -1;
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  unsigned long ordinary_count = 0;
  unsigned long security_count = 0;
  unsigned long transfer_count = 0;
  unsigned long timeout_count = 0;
  std::array<PASSTHRU_MSG, 2> ordinary_messages{};
  std::array<PASSTHRU_MSG, 1> security_messages{};
  std::array<PASSTHRU_MSG, 1> transfer_messages{};
  std::array<PASSTHRU_MSG, 1> timeout_messages{};
};

void FillWriteMessage(PASSTHRU_MSG& message, const unsigned char* data,
                      size_t data_size) {
  std::memset(&message, 0, sizeof(message));
  message.ProtocolID = PROTOCOL_ISO15765;
  message.RxStatus = 0;
  message.TxFlags = 0;
  message.Timestamp = 0;
  message.DataSize = static_cast<unsigned long>(data_size);
  message.ExtraDataIndex = 0;
  std::memcpy(message.Data, data, data_size);
}

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
  api.write_msgs = reinterpret_cast<PassThruWriteMsgsFn>(
      GetProcAddress(api.module, "PassThruWriteMsgs"));
  return api;
}

bool Complete(const Api& api) {
  return api.module != nullptr && api.open != nullptr && api.close != nullptr &&
         api.connect != nullptr && api.disconnect != nullptr &&
         api.write_msgs != nullptr;
}

WriteResult RunWrite(const Api& api) {
  WriteResult result;
  constexpr unsigned char kDid0[] = {
      0x00, 0x00, 0x07, 0xE4, 0x03, 0x22, 0x43, 0x56};
  constexpr unsigned char kDid1[] = {
      0x00, 0x00, 0x07, 0xE4, 0x03, 0x22, 0x43, 0xAF};
  constexpr unsigned char kSecurity[] = {
      0x00, 0x00, 0x07, 0xE4, 0x04, 0x27, 0x01, 0xA5, 0x5A};
  constexpr unsigned char kTransfer[] = {
      0x00, 0x00, 0x07, 0xE4, 0x04, 0x36, 0x01, 0xC3, 0x3C};
  constexpr unsigned char kTimeout[] = {
      0x00, 0x00, 0x07, 0xE4, 0x03, 0x22, 0x43, 0x2D};

  FillWriteMessage(result.ordinary_messages[0], kDid0, sizeof(kDid0));
  FillWriteMessage(result.ordinary_messages[1], kDid1, sizeof(kDid1));
  FillWriteMessage(result.security_messages[0], kSecurity, sizeof(kSecurity));
  FillWriteMessage(result.transfer_messages[0], kTransfer, sizeof(kTransfer));
  FillWriteMessage(result.timeout_messages[0], kTimeout, sizeof(kTimeout));

  result.open_result = api.open(nullptr, &result.device_id);
  result.connect_result = api.connect(
      result.device_id, PROTOCOL_ISO15765, 0, 500000, &result.channel_id);

  result.ordinary_count = 2;
  result.ordinary_result = api.write_msgs(
      result.channel_id, result.ordinary_messages.data(), &result.ordinary_count,
      50);

  result.security_count = 1;
  result.security_result = api.write_msgs(
      result.channel_id, result.security_messages.data(), &result.security_count,
      60);

  result.transfer_count = 1;
  result.transfer_result = api.write_msgs(
      result.channel_id, result.transfer_messages.data(), &result.transfer_count,
      70);

  result.timeout_count = 1;
  result.timeout_result = api.write_msgs(
      result.channel_id, result.timeout_messages.data(), &result.timeout_count,
      0);

  result.disconnect_result = api.disconnect(result.channel_id);
  result.close_result = api.close(result.device_id);
  return result;
}

bool Equal(const WriteResult& a, const WriteResult& b) {
  return a.open_result == b.open_result &&
         a.connect_result == b.connect_result &&
         a.ordinary_result == b.ordinary_result &&
         a.security_result == b.security_result &&
         a.transfer_result == b.transfer_result &&
         a.timeout_result == b.timeout_result &&
         a.disconnect_result == b.disconnect_result &&
         a.close_result == b.close_result && a.device_id == b.device_id &&
         a.channel_id == b.channel_id &&
         a.ordinary_count == b.ordinary_count &&
         a.security_count == b.security_count &&
         a.transfer_count == b.transfer_count &&
         a.timeout_count == b.timeout_count &&
         std::memcmp(a.ordinary_messages.data(), b.ordinary_messages.data(),
                     sizeof(a.ordinary_messages)) == 0 &&
         std::memcmp(a.security_messages.data(), b.security_messages.data(),
                     sizeof(a.security_messages)) == 0 &&
         std::memcmp(a.transfer_messages.data(), b.transfer_messages.data(),
                     sizeof(a.transfer_messages)) == 0 &&
         std::memcmp(a.timeout_messages.data(), b.timeout_messages.data(),
                     sizeof(a.timeout_messages)) == 0;
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

size_t CountOccurrences(const std::string& text, const std::string& needle) {
  size_t count = 0;
  size_t offset = 0;
  while ((offset = text.find(needle, offset)) != std::string::npos) {
    ++count;
    offset += needle.size();
  }
  return count;
}

int Fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return Fail("usage: proxy_write_msgs_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct = LoadApi(provider_path);
  if (!Complete(direct)) return Fail("could not load fake provider write API");
  const WriteResult baseline = RunWrite(direct);
  FreeLibrary(direct.module);

  if (baseline.open_result != STATUS_NOERROR ||
      baseline.connect_result != STATUS_NOERROR ||
      baseline.ordinary_result != STATUS_NOERROR || baseline.ordinary_count != 2 ||
      baseline.security_result != STATUS_NOERROR || baseline.security_count != 1 ||
      baseline.transfer_result != STATUS_NOERROR || baseline.transfer_count != 1 ||
      baseline.timeout_result != ERR_TIMEOUT || baseline.timeout_count != 0 ||
      baseline.disconnect_result != STATUS_NOERROR ||
      baseline.close_result != STATUS_NOERROR) {
    return Fail("fake provider returned unexpected write lifecycle status");
  }

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_write_test_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'a');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-write");
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
  if (!Complete(proxy)) return Fail("could not load proxy write API");
  const WriteResult proxied = RunWrite(proxy);
  if (!Equal(baseline, proxied)) {
    return Fail("proxied WriteMsgs behavior differs from direct provider");
  }

  const std::string trace = ReadText(trace_path);
  if (!Contains(trace, "\"api\":\"PassThruWriteMsgs\"")) {
    return Fail("trace missing PassThruWriteMsgs");
  }
  if (!Contains(trace, "000007E403224356") ||
      !Contains(trace, "000007E4032243AF")) {
    return Fail("trace missing ordinary write payloads");
  }
  if (Contains(trace, "000007E4042701A55A") ||
      Contains(trace, "000007E4043601C33C")) {
    return Fail("trace leaked a sensitive write payload");
  }
  if (!Contains(trace, "\"sensitiveService\":\"SecurityAccess\"") ||
      !Contains(trace, "\"sensitiveService\":\"TransferData\"")) {
    return Fail("trace missing sensitive-service labels");
  }
  if (CountOccurrences(trace, "\"payloadRedacted\":true") < 2 ||
      CountOccurrences(trace, "\"payloadSha256\":\"") < 2 ||
      Contains(trace, "\"payloadSha256\":null")) {
    return Fail("trace missing SHA-256 redaction evidence");
  }
  if (!Contains(trace, "\"requestedMessageCount\":2,\"timeoutMs\":50") ||
      !Contains(trace, "\"returnedMessageCount\":2")) {
    return Fail("trace missing ordinary write count/timeout metadata");
  }
  if (!Contains(trace, "\"requestedMessageCount\":1,\"timeoutMs\":0") ||
      !Contains(trace, "\"returnCode\":9") ||
      !Contains(trace, "\"returnedMessageCount\":0")) {
    return Fail("trace missing timeout write behavior");
  }

  FreeLibrary(proxy.module);
  std::cout << "J2534 WriteMsgs transparency/redaction test passed\n";
  return 0;
}
