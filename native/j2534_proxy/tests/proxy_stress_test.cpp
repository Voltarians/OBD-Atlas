#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "../j2534_api.h"

namespace {

using namespace atlas_j2534;
using Clock = std::chrono::steady_clock;

constexpr size_t kOperationCount = 100000;
constexpr size_t kThreadCount = 4;
constexpr unsigned long kBaudRate = 500000;
constexpr unsigned long kExpectedBatteryMillivolts = 12340;
constexpr unsigned long kExpectedFilterId = 0x3456;
constexpr unsigned long kExpectedPeriodicMsgId = 0x4567;

struct Api {
  HMODULE module = nullptr;
  PassThruOpenFn open = nullptr;
  PassThruCloseFn close = nullptr;
  PassThruConnectFn connect = nullptr;
  PassThruDisconnectFn disconnect = nullptr;
  PassThruStartPeriodicMsgFn start_periodic = nullptr;
  PassThruStopPeriodicMsgFn stop_periodic = nullptr;
  PassThruStartMsgFilterFn start_filter = nullptr;
  PassThruStopMsgFilterFn stop_filter = nullptr;
  PassThruReadMsgsFn read_msgs = nullptr;
  PassThruWriteMsgsFn write_msgs = nullptr;
  PassThruIoctlFn ioctl = nullptr;
  PassThruGetLastErrorFn get_last_error = nullptr;
};

struct Session {
  unsigned long device_id = 0;
  unsigned long channel_id = 0;
  unsigned long filter_id = 0;
  unsigned long periodic_id = 0;
};

struct OpResult {
  long return_code = ERR_FAILED;
  unsigned long aux1 = 0;
  unsigned long aux2 = 0;
  uint64_t digest = 0;

  bool operator==(const OpResult& other) const {
    return return_code == other.return_code && aux1 == other.aux1 &&
           aux2 == other.aux2 && digest == other.digest;
  }
};

struct LatencyStats {
  uint64_t minimum = 0;
  uint64_t p50 = 0;
  uint64_t p95 = 0;
  uint64_t p99 = 0;
  uint64_t maximum = 0;
  uint64_t mean = 0;
};

struct TraceSummary {
  bool contiguous_sequences = true;
  bool call_pairs_valid = true;
  bool sensitive_payload_leak = false;
  uint64_t records = 0;
  uint64_t bytes = 0;
  uint64_t calls = 0;
};

int Fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

template <typename T>
T Resolve(HMODULE module, const char* name) {
  return reinterpret_cast<T>(GetProcAddress(module, name));
}

bool LoadApi(const std::filesystem::path& path, Api* api) {
  if (api == nullptr) return false;
  api->module = LoadLibraryW(path.c_str());
  if (api->module == nullptr) return false;
  api->open = Resolve<PassThruOpenFn>(api->module, "PassThruOpen");
  api->close = Resolve<PassThruCloseFn>(api->module, "PassThruClose");
  api->connect = Resolve<PassThruConnectFn>(api->module, "PassThruConnect");
  api->disconnect =
      Resolve<PassThruDisconnectFn>(api->module, "PassThruDisconnect");
  api->start_periodic = Resolve<PassThruStartPeriodicMsgFn>(
      api->module, "PassThruStartPeriodicMsg");
  api->stop_periodic = Resolve<PassThruStopPeriodicMsgFn>(
      api->module, "PassThruStopPeriodicMsg");
  api->start_filter = Resolve<PassThruStartMsgFilterFn>(
      api->module, "PassThruStartMsgFilter");
  api->stop_filter = Resolve<PassThruStopMsgFilterFn>(
      api->module, "PassThruStopMsgFilter");
  api->read_msgs =
      Resolve<PassThruReadMsgsFn>(api->module, "PassThruReadMsgs");
  api->write_msgs =
      Resolve<PassThruWriteMsgsFn>(api->module, "PassThruWriteMsgs");
  api->ioctl = Resolve<PassThruIoctlFn>(api->module, "PassThruIoctl");
  api->get_last_error = Resolve<PassThruGetLastErrorFn>(
      api->module, "PassThruGetLastError");
  return api->open != nullptr && api->close != nullptr &&
         api->connect != nullptr && api->disconnect != nullptr &&
         api->start_periodic != nullptr && api->stop_periodic != nullptr &&
         api->start_filter != nullptr && api->stop_filter != nullptr &&
         api->read_msgs != nullptr && api->write_msgs != nullptr &&
         api->ioctl != nullptr && api->get_last_error != nullptr;
}

uint64_t Fnv1a(const void* data, size_t size, uint64_t seed = 1469598103934665603ULL) {
  const auto* bytes = static_cast<const unsigned char*>(data);
  uint64_t hash = seed;
  for (size_t index = 0; index < size; ++index) {
    hash ^= bytes[index];
    hash *= 1099511628211ULL;
  }
  return hash;
}

template <typename T>
uint64_t HashValue(uint64_t hash, const T& value) {
  return Fnv1a(&value, sizeof(value), hash);
}

uint64_t HashMessage(const PASSTHRU_MSG& message, uint64_t seed = 1469598103934665603ULL) {
  uint64_t hash = seed;
  hash = HashValue(hash, message.ProtocolID);
  hash = HashValue(hash, message.RxStatus);
  hash = HashValue(hash, message.TxFlags);
  hash = HashValue(hash, message.Timestamp);
  hash = HashValue(hash, message.DataSize);
  hash = HashValue(hash, message.ExtraDataIndex);
  const size_t captured = std::min<size_t>(message.DataSize, sizeof(message.Data));
  return Fnv1a(message.Data, captured, hash);
}

PASSTHRU_MSG MakeMessage(const unsigned char* bytes, size_t size) {
  PASSTHRU_MSG message{};
  message.ProtocolID = PROTOCOL_ISO15765;
  message.DataSize = static_cast<unsigned long>(size);
  std::memcpy(message.Data, bytes, size);
  return message;
}

PASSTHRU_MSG MakeFilterMessage(const std::array<unsigned char, 4>& bytes) {
  return MakeMessage(bytes.data(), bytes.size());
}

bool SetupSession(const Api& api, Session* session) {
  if (session == nullptr) return false;
  if (api.open(nullptr, &session->device_id) != STATUS_NOERROR) return false;
  if (api.connect(session->device_id, PROTOCOL_ISO15765, 0, kBaudRate,
                  &session->channel_id) != STATUS_NOERROR) {
    return false;
  }

  auto mask = MakeFilterMessage({0xFF, 0xFF, 0xFF, 0xFF});
  auto pattern = MakeFilterMessage({0x00, 0x00, 0x07, 0xE8});
  auto flow = MakeFilterMessage({0x00, 0x00, 0x07, 0xE0});
  if (api.start_filter(session->channel_id, FLOW_CONTROL_FILTER, &mask,
                       &pattern, &flow, &session->filter_id) != STATUS_NOERROR ||
      session->filter_id != kExpectedFilterId) {
    return false;
  }

  constexpr unsigned char kPeriodic[] = {
      0x00, 0x00, 0x07, 0xE0, 0x02, 0x3E, 0x00};
  auto periodic = MakeMessage(kPeriodic, sizeof(kPeriodic));
  if (api.start_periodic(session->channel_id, &periodic,
                         &session->periodic_id, 1000) != STATUS_NOERROR ||
      session->periodic_id != kExpectedPeriodicMsgId) {
    return false;
  }
  return true;
}

bool TeardownSession(const Api& api, const Session& session) {
  bool ok = true;
  ok = api.stop_periodic(session.channel_id, session.periodic_id) ==
           STATUS_NOERROR && ok;
  ok = api.stop_filter(session.channel_id, session.filter_id) ==
           STATUS_NOERROR && ok;
  ok = api.disconnect(session.channel_id) == STATUS_NOERROR && ok;
  ok = api.close(session.device_id) == STATUS_NOERROR && ok;
  return ok;
}

template <typename Callable>
long TimedCall(Callable&& callable, uint64_t* elapsed_ns) {
  const auto start = Clock::now();
  const long result = callable();
  const auto end = Clock::now();
  if (elapsed_ns != nullptr) {
    *elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count());
  }
  return result;
}

OpResult ExecuteOperation(const Api& api, unsigned long channel_id,
                          size_t operation_index, uint64_t* elapsed_ns) {
  const size_t selector = operation_index % 8;
  OpResult output{};

  if (selector == 0) {
    std::array<PASSTHRU_MSG, 2> messages{};
    unsigned long count = static_cast<unsigned long>(messages.size());
    output.return_code = TimedCall(
        [&]() { return api.read_msgs(channel_id, messages.data(), &count, 25); },
        elapsed_ns);
    output.aux1 = count;
    uint64_t hash = 1469598103934665603ULL;
    for (unsigned long index = 0; index < count && index < messages.size(); ++index) {
      hash = HashMessage(messages[index], hash);
    }
    output.digest = hash;
    return output;
  }

  if (selector == 1) {
    constexpr unsigned char kDid0[] = {
        0x00, 0x00, 0x07, 0xE4, 0x03, 0x22, 0x43, 0x56};
    constexpr unsigned char kDid1[] = {
        0x00, 0x00, 0x07, 0xE4, 0x03, 0x22, 0x43, 0xAF};
    std::array<PASSTHRU_MSG, 2> messages = {
        MakeMessage(kDid0, sizeof(kDid0)), MakeMessage(kDid1, sizeof(kDid1))};
    unsigned long count = static_cast<unsigned long>(messages.size());
    output.return_code = TimedCall(
        [&]() { return api.write_msgs(channel_id, messages.data(), &count, 50); },
        elapsed_ns);
    output.aux1 = count;
    uint64_t hash = 1469598103934665603ULL;
    for (const auto& message : messages) hash = HashMessage(message, hash);
    output.digest = hash;
    return output;
  }

  if (selector == 2) {
    PASSTHRU_MSG message{};
    std::memset(&message, 0xA5, sizeof(message));
    unsigned long count = 1;
    output.return_code = TimedCall(
        [&]() { return api.read_msgs(channel_id, &message, &count, 0); },
        elapsed_ns);
    output.aux1 = count;
    output.digest = Fnv1a(&message, sizeof(message));
    return output;
  }

  if (selector == 3) {
    constexpr unsigned char kDid[] = {
        0x00, 0x00, 0x07, 0xE4, 0x03, 0x22, 0x43, 0x56};
    auto message = MakeMessage(kDid, sizeof(kDid));
    unsigned long count = 1;
    output.return_code = TimedCall(
        [&]() { return api.write_msgs(channel_id, &message, &count, 0); },
        elapsed_ns);
    output.aux1 = count;
    output.digest = HashMessage(message);
    return output;
  }

  if (selector == 4) {
    char description[80]{};
    output.return_code = TimedCall(
        [&]() { return api.get_last_error(description); }, elapsed_ns);
    output.aux1 = static_cast<unsigned long>(strnlen_s(description, sizeof(description)));
    output.digest = Fnv1a(description, output.aux1);
    return output;
  }

  if (selector == 5) {
    unsigned long battery = 0xDEADBEEF;
    output.return_code = TimedCall(
        [&]() { return api.ioctl(channel_id, IOCTL_READ_VBATT, nullptr, &battery); },
        elapsed_ns);
    output.aux1 = battery;
    output.digest = HashValue(1469598103934665603ULL, battery);
    return output;
  }

  if (selector == 6) {
    constexpr unsigned char kSecurity[] = {
        0x00, 0x00, 0x07, 0xE4, 0x04, 0x27, 0x01, 0xA5, 0x5A};
    auto message = MakeMessage(kSecurity, sizeof(kSecurity));
    unsigned long count = 1;
    output.return_code = TimedCall(
        [&]() { return api.write_msgs(channel_id, &message, &count, 60); },
        elapsed_ns);
    output.aux1 = count;
    output.digest = HashMessage(message);
    return output;
  }

  constexpr unsigned char kTransfer[] = {
      0x00, 0x00, 0x07, 0xE4, 0x04, 0x36, 0x01, 0xC3, 0x3C};
  auto message = MakeMessage(kTransfer, sizeof(kTransfer));
  unsigned long count = 1;
  output.return_code = TimedCall(
      [&]() { return api.write_msgs(channel_id, &message, &count, 70); },
      elapsed_ns);
  output.aux1 = count;
  output.digest = HashMessage(message);
  return output;
}

bool ExpectedResult(size_t operation_index, const OpResult& result) {
  switch (operation_index % 8) {
    case 0:
      return result.return_code == STATUS_NOERROR && result.aux1 == 2;
    case 1:
      return result.return_code == STATUS_NOERROR && result.aux1 == 2;
    case 2:
      return result.return_code == ERR_TIMEOUT && result.aux1 == 0;
    case 3:
      return result.return_code == ERR_TIMEOUT && result.aux1 == 0;
    case 4:
      return result.return_code == STATUS_NOERROR && result.aux1 == 7;
    case 5:
      return result.return_code == STATUS_NOERROR &&
             result.aux1 == kExpectedBatteryMillivolts;
    case 6:
    case 7:
      return result.return_code == STATUS_NOERROR && result.aux1 == 1;
    default:
      return false;
  }
}

bool RunStress(const Api& api, unsigned long channel_id,
               std::vector<OpResult>* results,
               std::vector<uint64_t>* latencies,
               uint64_t* wall_ns) {
  if (results == nullptr || latencies == nullptr || wall_ns == nullptr) return false;
  results->assign(kOperationCount, OpResult{});
  latencies->assign(kOperationCount, 0);
  std::atomic<unsigned long> invalid_results{0};
  const auto wall_start = Clock::now();

  std::vector<std::thread> threads;
  threads.reserve(kThreadCount);
  for (size_t thread_index = 0; thread_index < kThreadCount; ++thread_index) {
    threads.emplace_back([&, thread_index]() {
      for (size_t operation_index = thread_index;
           operation_index < kOperationCount;
           operation_index += kThreadCount) {
        auto result = ExecuteOperation(api, channel_id, operation_index,
                                       &(*latencies)[operation_index]);
        if (!ExpectedResult(operation_index, result)) {
          invalid_results.fetch_add(1, std::memory_order_relaxed);
        }
        (*results)[operation_index] = result;
      }
    });
  }
  for (auto& thread : threads) thread.join();

  const auto wall_end = Clock::now();
  *wall_ns = static_cast<uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(wall_end - wall_start)
          .count());
  return invalid_results.load(std::memory_order_relaxed) == 0;
}

LatencyStats CalculateStats(const std::vector<uint64_t>& samples) {
  LatencyStats stats{};
  if (samples.empty()) return stats;
  std::vector<uint64_t> sorted = samples;
  std::sort(sorted.begin(), sorted.end());
  auto percentile = [&](double fraction) {
    const size_t index = static_cast<size_t>(
        fraction * static_cast<double>(sorted.size() - 1));
    return sorted[index];
  };
  stats.minimum = sorted.front();
  stats.p50 = percentile(0.50);
  stats.p95 = percentile(0.95);
  stats.p99 = percentile(0.99);
  stats.maximum = sorted.back();
  const long double total = std::accumulate(
      sorted.begin(), sorted.end(), static_cast<long double>(0));
  stats.mean = static_cast<uint64_t>(total / sorted.size());
  return stats;
}

std::string ExtractJsonString(const std::string& line, const std::string& key) {
  const std::string needle = "\"" + key + "\":\"";
  const size_t start = line.find(needle);
  if (start == std::string::npos) return {};
  const size_t value_start = start + needle.size();
  const size_t end = line.find('"', value_start);
  if (end == std::string::npos) return {};
  return line.substr(value_start, end - value_start);
}

bool ExtractSequence(const std::string& line, uint64_t* sequence) {
  if (sequence == nullptr) return false;
  constexpr char kNeedle[] = "\"sequence\":";
  const size_t start = line.find(kNeedle);
  if (start == std::string::npos) return false;
  size_t cursor = start + sizeof(kNeedle) - 1;
  size_t end = cursor;
  while (end < line.size() && line[end] >= '0' && line[end] <= '9') ++end;
  if (end == cursor) return false;
  *sequence = std::stoull(line.substr(cursor, end - cursor));
  return true;
}

TraceSummary ValidateTrace(const std::filesystem::path& path) {
  TraceSummary summary{};
  std::error_code error;
  summary.bytes = std::filesystem::file_size(path, error);
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    summary.contiguous_sequences = false;
    summary.call_pairs_valid = false;
    return summary;
  }

  std::unordered_map<std::string, int> call_states;
  call_states.reserve(kOperationCount + 16);
  uint64_t expected_sequence = 0;
  std::string line;
  while (std::getline(input, line)) {
    ++summary.records;
    uint64_t sequence = 0;
    if (!ExtractSequence(line, &sequence) || sequence != expected_sequence) {
      summary.contiguous_sequences = false;
    }
    ++expected_sequence;

    if (line.find("000007E4042701A55A") != std::string::npos ||
        line.find("000007E4043601C33C") != std::string::npos) {
      summary.sensitive_payload_leak = true;
    }

    const std::string type = ExtractJsonString(line, "recordType");
    if (type == "session") continue;
    const std::string call_id = ExtractJsonString(line, "callId");
    if (call_id.empty()) {
      summary.call_pairs_valid = false;
      continue;
    }
    int& state = call_states[call_id];
    if (type == "callBegin") {
      if (state != 0) summary.call_pairs_valid = false;
      state = 1;
    } else if (type == "callEnd") {
      if (state != 1) summary.call_pairs_valid = false;
      state = 2;
    } else {
      summary.call_pairs_valid = false;
    }
  }

  summary.calls = call_states.size();
  for (const auto& item : call_states) {
    if (item.second != 2) summary.call_pairs_valid = false;
  }
  return summary;
}

void PrintStats(const char* name, const LatencyStats& stats, uint64_t wall_ns) {
  std::cout << name << ".wall_ms=" << (wall_ns / 1000000.0) << '\n'
            << name << ".latency_ns.min=" << stats.minimum << '\n'
            << name << ".latency_ns.p50=" << stats.p50 << '\n'
            << name << ".latency_ns.p95=" << stats.p95 << '\n'
            << name << ".latency_ns.p99=" << stats.p99 << '\n'
            << name << ".latency_ns.max=" << stats.maximum << '\n'
            << name << ".latency_ns.mean=" << stats.mean << '\n';
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return Fail("usage: proxy_stress_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  Api direct_api{};
  if (!LoadApi(provider_path, &direct_api)) {
    return Fail("could not load complete fake-provider API");
  }
  Session direct_session{};
  if (!SetupSession(direct_api, &direct_session)) {
    return Fail("direct-provider setup failed");
  }

  std::vector<OpResult> direct_results;
  std::vector<uint64_t> direct_latencies;
  uint64_t direct_wall_ns = 0;
  if (!RunStress(direct_api, direct_session.channel_id, &direct_results,
                 &direct_latencies, &direct_wall_ns)) {
    return Fail("direct-provider workload returned an unexpected result");
  }
  if (!TeardownSession(direct_api, direct_session)) {
    return Fail("direct-provider teardown failed");
  }
  FreeLibrary(direct_api.module);

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) {
    return Fail("GetTempPathW failed");
  }
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_stress_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring provider_string = provider_path.wstring();
  const std::wstring trace_string = trace_path.wstring();
  const std::wstring fingerprint(64, L'c');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL", provider_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH", trace_string.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-stress");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP_VERSION", L"1");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_NAME", L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_VENDOR", L"OBD Atlas CI");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH",
                          L"SOFTWARE\\PassThruSupport.04.04");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY",
                          L"Fake J2534");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT",
                          fingerprint.c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE", nullptr);

  Api proxy_api{};
  if (!LoadApi(proxy_path, &proxy_api)) {
    return Fail("could not load complete proxy API");
  }
  Session proxy_session{};
  if (!SetupSession(proxy_api, &proxy_session)) {
    return Fail("proxy setup failed");
  }

  std::vector<OpResult> proxy_results;
  std::vector<uint64_t> proxy_latencies;
  uint64_t proxy_wall_ns = 0;
  if (!RunStress(proxy_api, proxy_session.channel_id, &proxy_results,
                 &proxy_latencies, &proxy_wall_ns)) {
    return Fail("proxy workload returned an unexpected result");
  }
  if (!TeardownSession(proxy_api, proxy_session)) {
    return Fail("proxy teardown failed");
  }

  size_t mismatches = 0;
  size_t first_mismatch = kOperationCount;
  for (size_t index = 0; index < kOperationCount; ++index) {
    if (!(direct_results[index] == proxy_results[index])) {
      if (mismatches == 0) first_mismatch = index;
      ++mismatches;
    }
  }
  if (mismatches != 0) {
    std::ostringstream message;
    message << mismatches << " direct/proxy operation mismatches; first at "
            << first_mismatch;
    return Fail(message.str());
  }

  const TraceSummary trace = ValidateTrace(trace_path);
  constexpr uint64_t kLifecycleCalls = 8;
  const uint64_t expected_calls = kOperationCount + kLifecycleCalls;
  const uint64_t expected_records = 1 + expected_calls * 2;
  if (!trace.contiguous_sequences || !trace.call_pairs_valid ||
      trace.sensitive_payload_leak || trace.calls != expected_calls ||
      trace.records != expected_records) {
    std::ostringstream message;
    message << "trace validation failed: records=" << trace.records
            << " expected=" << expected_records
            << " calls=" << trace.calls << " expectedCalls=" << expected_calls
            << " contiguous=" << trace.contiguous_sequences
            << " pairs=" << trace.call_pairs_valid
            << " sensitiveLeak=" << trace.sensitive_payload_leak;
    return Fail(message.str());
  }

  const auto direct_stats = CalculateStats(direct_latencies);
  const auto proxy_stats = CalculateStats(proxy_latencies);
  PrintStats("direct", direct_stats, direct_wall_ns);
  PrintStats("proxy", proxy_stats, proxy_wall_ns);
  std::cout << "stress.operations=" << kOperationCount << '\n'
            << "stress.threads=" << kThreadCount << '\n'
            << "stress.mismatches=" << mismatches << '\n'
            << "trace.records=" << trace.records << '\n'
            << "trace.calls=" << trace.calls << '\n'
            << "trace.bytes=" << trace.bytes << '\n'
            << "trace.sequence_gaps=0\n"
            << "trace.call_pair_errors=0\n"
            << "trace.sensitive_payload_leaks=0\n";

  const int64_t added_p50 = static_cast<int64_t>(proxy_stats.p50) -
                            static_cast<int64_t>(direct_stats.p50);
  const int64_t added_p95 = static_cast<int64_t>(proxy_stats.p95) -
                            static_cast<int64_t>(direct_stats.p95);
  const int64_t added_p99 = static_cast<int64_t>(proxy_stats.p99) -
                            static_cast<int64_t>(direct_stats.p99);
  std::cout << "proxy.added_latency_ns.p50=" << added_p50 << '\n'
            << "proxy.added_latency_ns.p95=" << added_p95 << '\n'
            << "proxy.added_latency_ns.p99=" << added_p99 << '\n';

  FreeLibrary(proxy_api.module);
  std::filesystem::remove(trace_path, ignored);
  std::cout << "J2534 100k-operation stress transparency test passed\n";
  return 0;
}
