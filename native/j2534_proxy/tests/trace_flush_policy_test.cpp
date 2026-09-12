#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <filesystem>
#include <iostream>
#include <string>

#define ATLAS_TRACE_FLUSH_POLICY_IMPLEMENTATION
#include "../trace_flush_policy.h"

namespace {

int Fail(const char* message) {
  std::cerr << "FAIL: " << message << '\n';
  return 1;
}

bool WriteRecord(HANDLE handle, const std::string& line) {
  const std::string rendered = line + "\n";
  DWORD written = 0;
  if (!AtlasTraceWriteFile(handle, rendered.data(),
                           static_cast<DWORD>(rendered.size()), &written,
                           nullptr) ||
      written != rendered.size()) {
    return false;
  }
  return AtlasTraceFlushFileBuffers(handle) != FALSE;
}

}  // namespace

int wmain() {
  wchar_t temp_dir[MAX_PATH]{};
  if (GetTempPathW(MAX_PATH, temp_dir) == 0) return Fail("GetTempPathW failed");
  const std::filesystem::path path =
      std::filesystem::path(temp_dir) /
      (L"obd_atlas_trace_flush_policy_" +
       std::to_wstring(GetCurrentProcessId()) + L".jsonl");
  std::error_code ignored;
  std::filesystem::remove(path, ignored);

  const HANDLE handle = CreateFileW(
      path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW,
      FILE_ATTRIBUTE_NORMAL, nullptr);
  if (handle == INVALID_HANDLE_VALUE) return Fail("CreateFileW failed");

  AtlasTraceResetFlushPolicyForTesting();
  if (!WriteRecord(handle, "{\"recordType\":\"session\"}")) {
    CloseHandle(handle);
    return Fail("session write failed");
  }
  if (AtlasTracePhysicalFlushCountForTesting() != 1) {
    CloseHandle(handle);
    return Fail("session did not commit immediately");
  }

  for (int i = 0; i < 32; ++i) {
    if (!WriteRecord(handle, "{\"recordType\":\"callBegin\",\"api\":\"PassThruReadMsgs\"}")) {
      CloseHandle(handle);
      return Fail("ordinary batched write failed");
    }
  }
  if (AtlasTracePhysicalFlushCountForTesting() != 1) {
    CloseHandle(handle);
    return Fail("ordinary records flushed individually");
  }

  // 224 more records makes 256 ordinary records since the session commit.
  for (int i = 0; i < 224; ++i) {
    if (!WriteRecord(handle, "{\"recordType\":\"callEnd\",\"api\":\"PassThruReadMsgs\"}")) {
      CloseHandle(handle);
      return Fail("count-boundary write failed");
    }
  }
  if (AtlasTracePhysicalFlushCountForTesting() != 2) {
    CloseHandle(handle);
    return Fail("256-record commit boundary did not flush");
  }

  if (!WriteRecord(handle, "{\"recordType\":\"callBegin\",\"api\":\"PassThruGetLastError\"}")) {
    CloseHandle(handle);
    return Fail("age test write failed");
  }
  Sleep(120);
  if (!WriteRecord(handle, "{\"recordType\":\"callEnd\",\"api\":\"PassThruGetLastError\"}")) {
    CloseHandle(handle);
    return Fail("age test second write failed");
  }
  if (AtlasTracePhysicalFlushCountForTesting() != 3) {
    CloseHandle(handle);
    return Fail("100 ms commit-age boundary did not flush");
  }

  if (!WriteRecord(handle, "{\"recordType\":\"callBegin\",\"api\":\"PassThruClose\"}")) {
    CloseHandle(handle);
    return Fail("close begin write failed");
  }
  if (!WriteRecord(handle, "{\"recordType\":\"callEnd\",\"api\":\"PassThruClose\"}")) {
    CloseHandle(handle);
    return Fail("close end write failed");
  }
  if (AtlasTracePhysicalFlushCountForTesting() != 4) {
    CloseHandle(handle);
    return Fail("close boundary did not commit immediately");
  }

  CloseHandle(handle);
  std::filesystem::remove(path, ignored);
  std::cout << "J2534 trace group-commit policy test passed\n";
  return 0;
}
