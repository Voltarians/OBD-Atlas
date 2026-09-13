#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <atomic>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include "../j2534_api.h"

namespace {

int Fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

bool ExtractSequence(const std::string& line, unsigned long long* value) {
  const std::string marker = "\"sequence\":";
  const size_t start = line.find(marker);
  if (start == std::string::npos) return false;
  size_t pos = start + marker.size();
  size_t end = pos;
  while (end < line.size() && line[end] >= '0' && line[end] <= '9') ++end;
  if (end == pos) return false;
  try {
    *value = std::stoull(line.substr(pos, end - pos));
    return true;
  } catch (...) {
    return false;
  }
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return Fail("usage: proxy_concurrency_test <proxy.dll> <fake-provider.dll>");
  }

  const std::filesystem::path proxy_path = argv[1];
  const std::filesystem::path provider_path = argv[2];

  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) return Fail("GetTempPathW failed");
  const std::filesystem::path trace_path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_j2534_proxy_concurrency_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(trace_path, ignored);

  const std::wstring fingerprint(64, L'b');
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_REAL_DLL",
                          provider_path.wstring().c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_TRACE_PATH",
                          trace_path.wstring().c_str());
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_SOURCE_APP", L"atlas-ci-concurrency");
  SetEnvironmentVariableW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT",
                          fingerprint.c_str());

  HMODULE proxy = LoadLibraryW(proxy_path.c_str());
  if (proxy == nullptr) return Fail("could not load proxy DLL");
  const auto open = reinterpret_cast<atlas_j2534::PassThruOpenFn>(
      GetProcAddress(proxy, "PassThruOpen"));
  const auto close = reinterpret_cast<atlas_j2534::PassThruCloseFn>(
      GetProcAddress(proxy, "PassThruClose"));
  const auto get_last_error = reinterpret_cast<atlas_j2534::PassThruGetLastErrorFn>(
      GetProcAddress(proxy, "PassThruGetLastError"));
  if (open == nullptr || close == nullptr || get_last_error == nullptr) {
    return Fail("required lifecycle export missing");
  }

  unsigned long device_id = 0;
  if (open(nullptr, &device_id) != atlas_j2534::STATUS_NOERROR) {
    return Fail("PassThruOpen failed");
  }

  constexpr int kThreads = 8;
  constexpr int kCallsPerThread = 25;
  std::atomic<int> failures{0};
  std::vector<std::thread> workers;
  workers.reserve(kThreads);
  for (int thread_index = 0; thread_index < kThreads; ++thread_index) {
    workers.emplace_back([&] {
      for (int i = 0; i < kCallsPerThread; ++i) {
        char error_text[80]{};
        const long result = get_last_error(error_text);
        if (result != atlas_j2534::STATUS_NOERROR ||
            std::string(error_text) != "FAKE_OK") {
          failures.fetch_add(1);
        }
      }
    });
  }
  for (auto& worker : workers) worker.join();
  if (failures.load() != 0) return Fail("concurrent forwarded calls changed behavior");

  if (close(device_id) != atlas_j2534::STATUS_NOERROR) {
    return Fail("PassThruClose failed");
  }

  std::ifstream input(trace_path, std::ios::binary);
  if (!input) return Fail("trace file missing");
  unsigned long long expected_sequence = 0;
  std::string line;
  size_t line_count = 0;
  while (std::getline(input, line)) {
    unsigned long long sequence = 0;
    if (!ExtractSequence(line, &sequence)) return Fail("trace sequence field missing");
    if (sequence != expected_sequence) {
      return Fail("trace sequence order is not contiguous under concurrency");
    }
    ++expected_sequence;
    ++line_count;
  }

  const size_t expected_lines =
      1 + 2 + (kThreads * kCallsPerThread * 2) + 2;
  if (line_count != expected_lines) {
    return Fail("unexpected trace line count in concurrency test");
  }

  FreeLibrary(proxy);
  std::cout << "J2534 concurrency trace-order test passed\n";
  return 0;
}
