#define ATLAS_TRACE_FLUSH_POLICY_IMPLEMENTATION
#include "trace_flush_policy.h"

#include <mutex>
#include <string_view>

namespace {

constexpr unsigned long kMaxRecordsPerCommit = 256;
constexpr ULONGLONG kMaxCommitAgeMs = 100;

std::mutex g_policy_mutex;
HANDLE g_trace_handle = INVALID_HANDLE_VALUE;
unsigned long g_records_since_flush = 0;
ULONGLONG g_last_flush_tick = 0;
bool g_force_flush = false;
unsigned long long g_physical_flush_count = 0;

bool Contains(std::string_view text, std::string_view needle) {
  return text.find(needle) != std::string_view::npos;
}

bool IsImmediateCommitBoundary(std::string_view line) {
  if (Contains(line, "\"recordType\":\"session\"")) return true;
  if (!Contains(line, "\"recordType\":\"callEnd\"")) return false;

  return Contains(line, "\"api\":\"PassThruClose\"") ||
         Contains(line, "\"api\":\"PassThruDisconnect\"") ||
         Contains(line, "\"api\":\"PassThruStopPeriodicMsg\"") ||
         Contains(line, "\"api\":\"PassThruSetProgrammingVoltage\"");
}

void SelectHandleLocked(HANDLE handle) {
  if (g_trace_handle == handle) return;
  g_trace_handle = handle;
  g_records_since_flush = 0;
  g_last_flush_tick = GetTickCount64();
  g_force_flush = false;
}

}  // namespace

BOOL WINAPI AtlasTraceWriteFile(
    HANDLE hFile,
    LPCVOID lpBuffer,
    DWORD nNumberOfBytesToWrite,
    LPDWORD lpNumberOfBytesWritten,
    LPOVERLAPPED lpOverlapped) {
  const BOOL result = ::WriteFile(
      hFile, lpBuffer, nNumberOfBytesToWrite, lpNumberOfBytesWritten,
      lpOverlapped);
  if (result == FALSE) return result;

  const DWORD written = lpNumberOfBytesWritten != nullptr
                            ? *lpNumberOfBytesWritten
                            : nNumberOfBytesToWrite;
  if (written != nNumberOfBytesToWrite || lpBuffer == nullptr) return result;

  std::lock_guard<std::mutex> lock(g_policy_mutex);
  SelectHandleLocked(hFile);
  ++g_records_since_flush;
  const auto* bytes = static_cast<const char*>(lpBuffer);
  const std::string_view line(bytes, static_cast<size_t>(written));
  if (IsImmediateCommitBoundary(line)) g_force_flush = true;
  return result;
}

BOOL WINAPI AtlasTraceFlushFileBuffers(HANDLE hFile) {
  std::lock_guard<std::mutex> lock(g_policy_mutex);
  SelectHandleLocked(hFile);
  if (g_records_since_flush == 0) return TRUE;

  const ULONGLONG now = GetTickCount64();
  const bool age_due = now - g_last_flush_tick >= kMaxCommitAgeMs;
  const bool count_due = g_records_since_flush >= kMaxRecordsPerCommit;
  if (!g_force_flush && !age_due && !count_due) return TRUE;

  const BOOL result = ::FlushFileBuffers(hFile);
  if (result != FALSE) {
    g_records_since_flush = 0;
    g_last_flush_tick = now;
    g_force_flush = false;
    ++g_physical_flush_count;
  }
  return result;
}

unsigned long long AtlasTracePhysicalFlushCountForTesting() {
  std::lock_guard<std::mutex> lock(g_policy_mutex);
  return g_physical_flush_count;
}

void AtlasTraceResetFlushPolicyForTesting() {
  std::lock_guard<std::mutex> lock(g_policy_mutex);
  g_trace_handle = INVALID_HANDLE_VALUE;
  g_records_since_flush = 0;
  g_last_flush_tick = 0;
  g_force_flush = false;
  g_physical_flush_count = 0;
}
