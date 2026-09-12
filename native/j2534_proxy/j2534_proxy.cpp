#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <iterator>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>

#include "j2534_api.h"

namespace {

using namespace atlas_j2534;

HMODULE g_self_module = nullptr;
HMODULE g_provider_module = nullptr;
PassThruOpenFn g_open = nullptr;
PassThruCloseFn g_close = nullptr;
PassThruReadVersionFn g_read_version = nullptr;
PassThruGetLastErrorFn g_get_last_error = nullptr;
std::once_flag g_init_once;
bool g_initialized = false;
std::atomic<unsigned long long> g_call_sequence{0};
std::atomic<unsigned long long> g_record_sequence{0};

std::wstring GetEnvW(const wchar_t* name) {
  const DWORD needed = GetEnvironmentVariableW(name, nullptr, 0);
  if (needed == 0) return L"";
  std::wstring value(needed, L'\0');
  const DWORD written = GetEnvironmentVariableW(name, value.data(), needed);
  if (written == 0) return L"";
  value.resize(written);
  return value;
}

std::string WideToUtf8(const std::wstring& value) {
  if (value.empty()) return {};
  const int needed = WideCharToMultiByte(
      CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()), nullptr, 0,
      nullptr, nullptr);
  if (needed <= 0) return {};
  std::string result(static_cast<size_t>(needed), '\0');
  WideCharToMultiByte(CP_UTF8, 0, value.c_str(),
                      static_cast<int>(value.size()), result.data(), needed,
                      nullptr, nullptr);
  return result;
}

std::string JsonEscape(const std::string& value) {
  std::ostringstream out;
  for (const unsigned char ch : value) {
    switch (ch) {
      case '\\': out << "\\\\"; break;
      case '"': out << "\\\""; break;
      case '\b': out << "\\b"; break;
      case '\f': out << "\\f"; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (ch < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
              << static_cast<int>(ch) << std::dec;
        } else {
          out << static_cast<char>(ch);
        }
    }
  }
  return out.str();
}

std::string JsonString(const std::string& value) {
  return "\"" + JsonEscape(value) + "\"";
}

std::string JsonString(const std::wstring& value) {
  return JsonString(WideToUtf8(value));
}

uint64_t MonotonicNs() {
  LARGE_INTEGER counter{};
  LARGE_INTEGER frequency{};
  QueryPerformanceCounter(&counter);
  QueryPerformanceFrequency(&frequency);
  if (frequency.QuadPart <= 0) return 0;
  const long double seconds =
      static_cast<long double>(counter.QuadPart) /
      static_cast<long double>(frequency.QuadPart);
  return static_cast<uint64_t>(seconds * 1000000000.0L);
}

std::string UtcNowIso() {
  FILETIME file_time{};
  GetSystemTimePreciseAsFileTime(&file_time);
  SYSTEMTIME system_time{};
  FileTimeToSystemTime(&file_time, &system_time);
  char buffer[40]{};
  std::snprintf(buffer, sizeof(buffer),
                "%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",
                system_time.wYear, system_time.wMonth, system_time.wDay,
                system_time.wHour, system_time.wMinute, system_time.wSecond,
                system_time.wMilliseconds);
  return buffer;
}

std::wstring CanonicalPath(const std::wstring& path) {
  if (path.empty()) return {};
  const DWORD needed = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
  if (needed == 0) return path;
  std::wstring full(needed, L'\0');
  const DWORD written =
      GetFullPathNameW(path.c_str(), needed, full.data(), nullptr);
  if (written == 0) return path;
  full.resize(written);
  return full;
}

std::wstring SelfModulePath() {
  wchar_t buffer[32768]{};
  const DWORD written =
      GetModuleFileNameW(g_self_module, buffer, static_cast<DWORD>(std::size(buffer)));
  if (written == 0 || written >= std::size(buffer)) return {};
  return CanonicalPath(std::wstring(buffer, written));
}

std::string BoundedCString(const char* value, size_t max_length = 255) {
  if (value == nullptr) return {};
  const size_t length = strnlen_s(value, max_length);
  return std::string(value, length);
}

class TraceWriter {
 public:
  bool Open(const std::wstring& path) {
    std::lock_guard<std::mutex> lock(mutex_);
    handle_ = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                          CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    return handle_ != INVALID_HANDLE_VALUE;
  }

  bool IsOpen() const { return handle_ != INVALID_HANDLE_VALUE; }

  bool WriteLine(const std::string& line) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (handle_ == INVALID_HANDLE_VALUE) return false;
    const std::string rendered = line + "\n";
    DWORD written = 0;
    const BOOL ok = WriteFile(handle_, rendered.data(),
                              static_cast<DWORD>(rendered.size()), &written,
                              nullptr);
    if (!ok || written != rendered.size()) return false;
    FlushFileBuffers(handle_);
    return true;
  }

 private:
  HANDLE handle_ = INVALID_HANDLE_VALUE;
  std::mutex mutex_;
};

TraceWriter g_trace;

struct CallContext {
  std::string call_id;
  uint64_t started_ns = 0;
};

std::string BaseRecord(const char* record_type, unsigned long long sequence,
                       uint64_t monotonic_ns) {
  std::ostringstream out;
  out << "{\"schema\":\"obd-atlas.j2534-trace.v1\""
      << ",\"recordType\":" << JsonString(record_type)
      << ",\"sequence\":" << sequence
      << ",\"utc\":" << JsonString(UtcNowIso())
      << ",\"monotonicNs\":" << monotonic_ns;
  return out.str();
}

bool WriteSession(const std::wstring& real_dll) {
  const auto sequence = g_record_sequence.fetch_add(1);
  const uint64_t now_ns = MonotonicNs();
  const std::wstring source_app = GetEnvW(L"OBD_ATLAS_J2534_SOURCE_APP");
  const std::wstring source_version =
      GetEnvW(L"OBD_ATLAS_J2534_SOURCE_APP_VERSION");
  const std::wstring provider_name =
      GetEnvW(L"OBD_ATLAS_J2534_PROVIDER_NAME");
  const std::wstring provider_vendor =
      GetEnvW(L"OBD_ATLAS_J2534_PROVIDER_VENDOR");
  const std::wstring provider_registry_path =
      GetEnvW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH");
  const std::wstring provider_registry_subkey =
      GetEnvW(L"OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY");
  const std::wstring provider_fingerprint =
      GetEnvW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT");

  std::ostringstream out;
  out << BaseRecord("session", sequence, now_ns)
      << ",\"observerMode\":\"transparent-forwarder\""
      << ",\"proxyMayTransmitIndependently\":false"
      << ",\"sourceApplication\":"
      << JsonString(source_app.empty() ? L"unknown" : source_app)
      << ",\"sourceApplicationVersion\":";
  if (source_version.empty()) {
    out << "null";
  } else {
    out << JsonString(source_version);
  }
  out << ",\"processId\":" << GetCurrentProcessId()
      << ",\"provider\":{"
      << "\"registryPath\":";
  if (provider_registry_path.empty()) out << "null";
  else out << JsonString(provider_registry_path);
  out << ",\"registrySubkey\":";
  if (provider_registry_subkey.empty()) out << "null";
  else out << JsonString(provider_registry_subkey);
  out << ",\"name\":";
  if (provider_name.empty()) out << "null";
  else out << JsonString(provider_name);
  out << ",\"vendor\":";
  if (provider_vendor.empty()) out << "null";
  else out << JsonString(provider_vendor);
  out << ",\"functionLibrary\":{\"path\":" << JsonString(real_dll)
      << "}}"
      << ",\"providerFingerprintSha256\":";
  if (provider_fingerprint.empty()) out << "null";
  else out << JsonString(provider_fingerprint);
  out << ",\"sensitivePayloadPolicy\":\"redact-security-access-and-transfer-data\"}";
  return g_trace.WriteLine(out.str());
}

CallContext BeginCall(const char* api, std::optional<unsigned long> device_id,
                      const std::string& arguments_json) {
  const unsigned long long call_number = g_call_sequence.fetch_add(1) + 1;
  char call_buffer[32]{};
  std::snprintf(call_buffer, sizeof(call_buffer), "call-%08llu", call_number);
  CallContext context{call_buffer, MonotonicNs()};
  const auto sequence = g_record_sequence.fetch_add(1);
  std::ostringstream out;
  out << BaseRecord("callBegin", sequence, context.started_ns)
      << ",\"callId\":" << JsonString(context.call_id)
      << ",\"api\":" << JsonString(api)
      << ",\"threadId\":" << GetCurrentThreadId()
      << ",\"deviceId\":";
  if (device_id.has_value()) out << device_id.value();
  else out << "null";
  out << ",\"channelId\":null"
      << ",\"arguments\":" << arguments_json << "}";
  g_trace.WriteLine(out.str());
  return context;
}

void EndCall(const CallContext& context, const char* api, long return_code,
             const std::string& outputs_json) {
  const uint64_t ended_ns = MonotonicNs();
  const auto sequence = g_record_sequence.fetch_add(1);
  std::ostringstream out;
  out << BaseRecord("callEnd", sequence, ended_ns)
      << ",\"callId\":" << JsonString(context.call_id)
      << ",\"api\":" << JsonString(api)
      << ",\"returnCode\":" << return_code
      << ",\"durationNs\":"
      << (ended_ns >= context.started_ns ? ended_ns - context.started_ns : 0)
      << ",\"outputs\":" << outputs_json << "}";
  g_trace.WriteLine(out.str());
}

template <typename T>
T Resolve(const char* name) {
  return reinterpret_cast<T>(GetProcAddress(g_provider_module, name));
}

void Initialize() {
  const std::wstring real_dll = GetEnvW(L"OBD_ATLAS_J2534_REAL_DLL");
  const std::wstring trace_path = GetEnvW(L"OBD_ATLAS_J2534_TRACE_PATH");
  if (real_dll.empty() || trace_path.empty()) return;

  const std::wstring provider_path = CanonicalPath(real_dll);
  const std::wstring self_path = SelfModulePath();
  if (!self_path.empty() && !provider_path.empty() &&
      _wcsicmp(self_path.c_str(), provider_path.c_str()) == 0) {
    return;
  }

  g_provider_module = LoadLibraryW(provider_path.c_str());
  if (g_provider_module == nullptr) return;

  g_open = Resolve<PassThruOpenFn>("PassThruOpen");
  g_close = Resolve<PassThruCloseFn>("PassThruClose");
  g_read_version = Resolve<PassThruReadVersionFn>("PassThruReadVersion");
  g_get_last_error =
      Resolve<PassThruGetLastErrorFn>("PassThruGetLastError");
  if (g_open == nullptr || g_close == nullptr || g_read_version == nullptr ||
      g_get_last_error == nullptr) {
    return;
  }

  if (!g_trace.Open(trace_path)) return;
  if (!WriteSession(provider_path)) return;
  g_initialized = true;
}

bool EnsureInitialized() {
  std::call_once(g_init_once, Initialize);
  return g_initialized;
}

}  // namespace

extern "C" __declspec(dllexport) long WINAPI PassThruOpen(
    void* pName, unsigned long* pDeviceID) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const auto call = BeginCall(
      "PassThruOpen", std::nullopt,
      std::string("{\"namePointerPresent\":") +
          (pName == nullptr ? "false}" : "true}"));
  const long result = g_open(pName, pDeviceID);
  std::ostringstream outputs;
  outputs << "{\"deviceId\":";
  if (pDeviceID != nullptr) outputs << *pDeviceID;
  else outputs << "null";
  outputs << "}";
  EndCall(call, "PassThruOpen", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruClose(
    unsigned long DeviceID) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const auto call = BeginCall("PassThruClose", DeviceID, "{}");
  const long result = g_close(DeviceID);
  EndCall(call, "PassThruClose", result, "{}");
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruReadVersion(
    unsigned long DeviceID, char* pFirmwareVersion, char* pDllVersion,
    char* pApiVersion) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const auto call = BeginCall("PassThruReadVersion", DeviceID, "{}");
  const long result =
      g_read_version(DeviceID, pFirmwareVersion, pDllVersion, pApiVersion);
  std::ostringstream outputs;
  outputs << "{\"firmwareVersion\":" << JsonString(BoundedCString(pFirmwareVersion))
          << ",\"dllVersion\":" << JsonString(BoundedCString(pDllVersion))
          << ",\"apiVersion\":" << JsonString(BoundedCString(pApiVersion))
          << "}";
  EndCall(call, "PassThruReadVersion", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruGetLastError(
    char* pErrorDescription) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const auto call = BeginCall("PassThruGetLastError", std::nullopt, "{}");
  const long result = g_get_last_error(pErrorDescription);
  const std::string description = BoundedCString(pErrorDescription);
  EndCall(call, "PassThruGetLastError", result,
          std::string("{\"errorDescription\":") +
              JsonString(description) + "}");
  return result;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    g_self_module = instance;
    DisableThreadLibraryCalls(instance);
  }
  return TRUE;
}
