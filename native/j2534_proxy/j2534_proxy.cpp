#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>

#include <algorithm>
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
#include <vector>

#include "j2534_api.h"
#include "programming_voltage_policy.h"

namespace {

using namespace atlas_j2534;

HMODULE g_self_module = nullptr;
HMODULE g_provider_module = nullptr;
PassThruOpenFn g_open = nullptr;
PassThruCloseFn g_close = nullptr;
PassThruConnectFn g_connect = nullptr;
PassThruDisconnectFn g_disconnect = nullptr;
PassThruStartMsgFilterFn g_start_filter = nullptr;
PassThruStopMsgFilterFn g_stop_filter = nullptr;
PassThruReadMsgsFn g_read_msgs = nullptr;
PassThruWriteMsgsFn g_write_msgs = nullptr;
PassThruIoctlFn g_ioctl = nullptr;
ProgrammingVoltageProviderFn g_set_programming_voltage = nullptr;
PassThruReadVersionFn g_read_version = nullptr;
PassThruGetLastErrorFn g_get_last_error = nullptr;
std::once_flag g_init_once;
bool g_initialized = false;
std::atomic<unsigned long long> g_call_sequence{0};
std::atomic<unsigned long long> g_record_sequence{0};
std::mutex g_record_mutex;

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
  const DWORD written = GetModuleFileNameW(
      g_self_module, buffer, static_cast<DWORD>(std::size(buffer)));
  if (written == 0 || written >= std::size(buffer)) return {};
  return CanonicalPath(std::wstring(buffer, written));
}

std::string BoundedCString(const char* value, size_t max_length) {
  if (value == nullptr) return {};
  const size_t length = strnlen_s(value, max_length);
  return std::string(value, length);
}

bool IsLowerHexSha256(const std::wstring& value) {
  if (value.size() != 64) return false;
  for (const wchar_t ch : value) {
    if (!((ch >= L'0' && ch <= L'9') || (ch >= L'a' && ch <= L'f'))) {
      return false;
    }
  }
  return true;
}

std::string HexBytes(const unsigned char* data, size_t size) {
  std::ostringstream out;
  out << std::uppercase << std::hex << std::setfill('0');
  for (size_t index = 0; index < size; ++index) {
    out << std::setw(2) << static_cast<unsigned int>(data[index]);
  }
  return out.str();
}

template <typename T>
bool SnapshotObject(const void* address, T* output) {
  if (address == nullptr || output == nullptr) return false;
  SIZE_T bytes_read = 0;
  return ReadProcessMemory(GetCurrentProcess(), address, output, sizeof(T),
                           &bytes_read) != FALSE &&
         bytes_read == sizeof(T);
}

std::optional<std::string> Sha256Hex(const unsigned char* data, size_t size) {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  DWORD object_size = 0;
  DWORD hash_size = 0;
  DWORD result_size = 0;
  std::vector<unsigned char> object;
  std::vector<unsigned char> digest;

  if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr,
                                  0) < 0) {
    return std::nullopt;
  }
  auto close_algorithm = [&]() {
    if (algorithm != nullptr) BCryptCloseAlgorithmProvider(algorithm, 0);
  };
  if (BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                        reinterpret_cast<PUCHAR>(&object_size),
                        sizeof(object_size), &result_size, 0) < 0 ||
      BCryptGetProperty(algorithm, BCRYPT_HASH_LENGTH,
                        reinterpret_cast<PUCHAR>(&hash_size),
                        sizeof(hash_size), &result_size, 0) < 0 ||
      hash_size == 0) {
    close_algorithm();
    return std::nullopt;
  }

  object.resize(object_size);
  digest.resize(hash_size);
  if (BCryptCreateHash(algorithm, &hash, object.data(), object_size, nullptr, 0,
                       0) < 0) {
    close_algorithm();
    return std::nullopt;
  }
  if (size > 0 &&
      BCryptHashData(hash, const_cast<PUCHAR>(data),
                     static_cast<ULONG>(size), 0) < 0) {
    BCryptDestroyHash(hash);
    close_algorithm();
    return std::nullopt;
  }
  if (BCryptFinishHash(hash, digest.data(), hash_size, 0) < 0) {
    BCryptDestroyHash(hash);
    close_algorithm();
    return std::nullopt;
  }
  BCryptDestroyHash(hash);
  close_algorithm();

  std::ostringstream out;
  out << std::nouppercase << std::hex << std::setfill('0');
  for (const unsigned char value : digest) {
    out << std::setw(2) << static_cast<unsigned int>(value);
  }
  return out.str();
}

struct SensitiveService {
  unsigned char service = 0;
  const char* name = nullptr;
};

std::optional<SensitiveService> DetectSensitiveService(
    const PASSTHRU_MSG* message) {
  if (message == nullptr || message->ProtocolID != PROTOCOL_ISO15765) {
    return std::nullopt;
  }
  const size_t size = std::min<size_t>(message->DataSize, sizeof(message->Data));
  if (size <= 4) return std::nullopt;

  size_t service_index = 4;
  const unsigned char first = message->Data[service_index];
  const unsigned char frame_type = static_cast<unsigned char>(first & 0xF0);
  if (frame_type == 0x00 && size > service_index + 1) {
    const unsigned char single_frame_length =
        static_cast<unsigned char>(first & 0x0F);
    if (single_frame_length > 0 && single_frame_length <= 7) {
      service_index += 1;
    }
  } else if (frame_type == 0x10 && size > service_index + 2) {
    const unsigned int first_frame_length =
        (static_cast<unsigned int>(first & 0x0F) << 8) |
        static_cast<unsigned int>(message->Data[service_index + 1]);
    if (first_frame_length > 7) service_index += 2;
  }
  if (service_index >= size) return std::nullopt;

  const unsigned char service = message->Data[service_index];
  if (service == 0x27) return SensitiveService{service, "SecurityAccess"};
  if (service == 0x36) return SensitiveService{service, "TransferData"};
  return std::nullopt;
}

std::string MessageJson(const PASSTHRU_MSG* message) {
  if (message == nullptr) return "null";
  const size_t requested = static_cast<size_t>(message->DataSize);
  const size_t capacity = sizeof(message->Data);
  const size_t captured = requested <= capacity ? requested : capacity;
  std::ostringstream out;
  out << "{\"protocolId\":" << message->ProtocolID
      << ",\"rxStatus\":" << message->RxStatus
      << ",\"txFlags\":" << message->TxFlags
      << ",\"timestamp\":" << message->Timestamp
      << ",\"dataSize\":" << message->DataSize
      << ",\"extraDataIndex\":" << message->ExtraDataIndex
      << ",\"payloadHex\":" << JsonString(HexBytes(message->Data, captured))
      << ",\"payloadTruncated\":"
      << (captured != requested ? "true" : "false") << "}";
  return out.str();
}

std::string TraceMessageJson(const PASSTHRU_MSG* message) {
  if (message == nullptr) return "null";
  const size_t requested = static_cast<size_t>(message->DataSize);
  const size_t capacity = sizeof(message->Data);
  const size_t captured = requested <= capacity ? requested : capacity;
  const auto sensitive = DetectSensitiveService(message);
  std::ostringstream out;
  out << "{\"protocolId\":" << message->ProtocolID
      << ",\"rxStatus\":" << message->RxStatus
      << ",\"txFlags\":" << message->TxFlags
      << ",\"timestamp\":" << message->Timestamp
      << ",\"dataLength\":" << message->DataSize
      << ",\"extraDataIndex\":" << message->ExtraDataIndex;
  if (sensitive.has_value()) {
    const auto digest = Sha256Hex(message->Data, captured);
    out << ",\"service\":" << static_cast<unsigned int>(sensitive->service)
        << ",\"payloadRedacted\":true"
        << ",\"sensitiveService\":" << JsonString(sensitive->name);
    if (digest.has_value()) {
      out << ",\"payloadSha256\":" << JsonString(*digest);
    } else {
      out << ",\"payloadHashUnavailable\":true";
    }
  } else {
    out << ",\"payloadRedacted\":false"
        << ",\"payloadHex\":" << JsonString(HexBytes(message->Data, captured));
  }
  out << ",\"payloadTruncated\":"
      << (captured != requested ? "true" : "false") << "}";
  return out.str();
}

std::string MessageArrayJson(const PASSTHRU_MSG* messages,
                             unsigned long count) {
  if (messages == nullptr || count == 0) return "[]";
  std::ostringstream out;
  out << "[";
  for (unsigned long index = 0; index < count; ++index) {
    if (index != 0) out << ",";
    out << MessageJson(&messages[index]);
  }
  out << "]";
  return out.str();
}

std::string TraceMessageArrayJson(const PASSTHRU_MSG* messages,
                                  unsigned long count) {
  if (messages == nullptr || count == 0) return "[]";
  std::ostringstream out;
  out << "[";
  for (unsigned long index = 0; index < count; ++index) {
    if (index != 0) out << ",";
    out << TraceMessageJson(&messages[index]);
  }
  out << "]";
  return out.str();
}

std::string ConfigListJson(const void* pointer) {
  if (pointer == nullptr) return "null";
  SCONFIG_LIST list{};
  if (!SnapshotObject(pointer, &list)) {
    return "{\"readable\":false}";
  }

  constexpr unsigned long kMaxObservedConfigs = 64;
  const unsigned long captured =
      std::min(list.NumOfParams, kMaxObservedConfigs);
  std::ostringstream out;
  out << "{\"readable\":true"
      << ",\"numOfParams\":" << list.NumOfParams
      << ",\"configPtrPresent\":"
      << (list.ConfigPtr != nullptr ? "true" : "false")
      << ",\"capturedParams\":" << (list.ConfigPtr != nullptr ? captured : 0)
      << ",\"paramsTruncated\":"
      << (list.NumOfParams > captured ? "true" : "false")
      << ",\"configs\":[";

  if (list.ConfigPtr != nullptr) {
    const uintptr_t base = reinterpret_cast<uintptr_t>(list.ConfigPtr);
    for (unsigned long index = 0; index < captured; ++index) {
      if (index != 0) out << ",";
      SCONFIG config{};
      const void* address = reinterpret_cast<const void*>(
          base + static_cast<uintptr_t>(index) * sizeof(SCONFIG));
      if (SnapshotObject(address, &config)) {
        out << "{\"index\":" << index
            << ",\"readable\":true"
            << ",\"parameter\":" << config.Parameter
            << ",\"value\":" << config.Value << "}";
      } else {
        out << "{\"index\":" << index
            << ",\"readable\":false}";
      }
    }
  }
  out << "]}";
  return out.str();
}

std::string IoctlArgumentsJson(unsigned long ioctl_id, void* input,
                               void* output) {
  std::ostringstream out;
  out << "{\"ioctlId\":" << ioctl_id
      << ",\"inputPointerPresent\":"
      << (input != nullptr ? "true" : "false")
      << ",\"outputPointerPresent\":"
      << (output != nullptr ? "true" : "false");
  if (ioctl_id == IOCTL_GET_CONFIG || ioctl_id == IOCTL_SET_CONFIG) {
    out << ",\"configInput\":" << ConfigListJson(input);
  }
  out << "}";
  return out.str();
}

std::string IoctlOutputsJson(unsigned long ioctl_id, void* input,
                             void* output) {
  std::ostringstream out;
  out << "{\"ioctlId\":" << ioctl_id;
  if (ioctl_id == IOCTL_GET_CONFIG || ioctl_id == IOCTL_SET_CONFIG) {
    out << ",\"configInputAfter\":" << ConfigListJson(input);
  } else if (ioctl_id == IOCTL_READ_VBATT ||
             ioctl_id == IOCTL_READ_PROG_VOLTAGE) {
    unsigned long value = 0;
    const bool readable = SnapshotObject(output, &value);
    out << ",\"outputUnsignedLongReadable\":"
        << (readable ? "true" : "false")
        << ",\"outputUnsignedLong\":";
    if (readable) out << value;
    else out << "null";
  }
  out << "}";
  return out.str();
}

class TraceWriter {
 public:
  bool Open(const std::wstring& path) {
    std::lock_guard<std::mutex> lock(mutex_);
    handle_ = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                          CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    return handle_ != INVALID_HANDLE_VALUE;
  }

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
  std::lock_guard<std::mutex> record_lock(g_record_mutex);
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
  if (source_version.empty()) out << "null";
  else out << JsonString(source_version);
  out << ",\"processId\":" << GetCurrentProcessId()
      << ",\"provider\":{\"registryPath\":";
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
      << ",\"providerFingerprintSha256\":" << JsonString(provider_fingerprint)
      << ",\"sensitivePayloadPolicy\":\"redact-security-access-and-transfer-data\"}";
  return g_trace.WriteLine(out.str());
}

CallContext BeginCall(const char* api, std::optional<unsigned long> device_id,
                      const std::string& arguments_json,
                      std::optional<unsigned long> channel_id = std::nullopt,
                      std::optional<std::string> messages_json = std::nullopt) {
  std::lock_guard<std::mutex> record_lock(g_record_mutex);
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
  out << ",\"channelId\":";
  if (channel_id.has_value()) out << channel_id.value();
  else out << "null";
  out << ",\"arguments\":" << arguments_json;
  if (messages_json.has_value()) out << ",\"messages\":" << *messages_json;
  out << "}";
  g_trace.WriteLine(out.str());
  return context;
}

void EndCall(const CallContext& context, const char* api, long return_code,
             const std::string& outputs_json) {
  std::lock_guard<std::mutex> record_lock(g_record_mutex);
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
  const std::wstring provider_fingerprint =
      GetEnvW(L"OBD_ATLAS_J2534_PROVIDER_FINGERPRINT");
  if (real_dll.empty() || trace_path.empty() ||
      !IsLowerHexSha256(provider_fingerprint)) {
    return;
  }

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
  g_connect = Resolve<PassThruConnectFn>("PassThruConnect");
  g_disconnect = Resolve<PassThruDisconnectFn>("PassThruDisconnect");
  g_start_filter = Resolve<PassThruStartMsgFilterFn>("PassThruStartMsgFilter");
  g_stop_filter = Resolve<PassThruStopMsgFilterFn>("PassThruStopMsgFilter");
  g_read_msgs = Resolve<PassThruReadMsgsFn>("PassThruReadMsgs");
  g_write_msgs = Resolve<PassThruWriteMsgsFn>("PassThruWriteMsgs");
  g_ioctl = Resolve<PassThruIoctlFn>("PassThruIoctl");
  g_set_programming_voltage = Resolve<ProgrammingVoltageProviderFn>(
      "PassThruSetProgrammingVoltage");
  g_read_version = Resolve<PassThruReadVersionFn>("PassThruReadVersion");
  g_get_last_error = Resolve<PassThruGetLastErrorFn>("PassThruGetLastError");
  if (g_open == nullptr || g_close == nullptr || g_connect == nullptr ||
      g_disconnect == nullptr || g_start_filter == nullptr ||
      g_stop_filter == nullptr || g_read_msgs == nullptr ||
      g_write_msgs == nullptr || g_ioctl == nullptr ||
      g_read_version == nullptr || g_get_last_error == nullptr) {
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
  if (result == atlas_j2534::STATUS_NOERROR && pDeviceID != nullptr) {
    outputs << *pDeviceID;
  } else {
    outputs << "null";
  }
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

extern "C" __declspec(dllexport) long WINAPI PassThruConnect(
    unsigned long DeviceID, unsigned long ProtocolID, unsigned long Flags,
    unsigned long BaudRate, unsigned long* pChannelID) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  std::ostringstream arguments;
  arguments << "{\"protocolId\":" << ProtocolID
            << ",\"flags\":" << Flags
            << ",\"baudRate\":" << BaudRate
            << ",\"channelIdPointerPresent\":"
            << (pChannelID == nullptr ? "false" : "true") << "}";
  const auto call = BeginCall("PassThruConnect", DeviceID, arguments.str());
  const long result =
      g_connect(DeviceID, ProtocolID, Flags, BaudRate, pChannelID);
  std::ostringstream outputs;
  outputs << "{\"channelId\":";
  if (result == atlas_j2534::STATUS_NOERROR && pChannelID != nullptr) {
    outputs << *pChannelID;
  } else {
    outputs << "null";
  }
  outputs << "}";
  EndCall(call, "PassThruConnect", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruDisconnect(
    unsigned long ChannelID) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const auto call =
      BeginCall("PassThruDisconnect", std::nullopt, "{}", ChannelID);
  const long result = g_disconnect(ChannelID);
  EndCall(call, "PassThruDisconnect", result, "{}");
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruStartMsgFilter(
    unsigned long ChannelID, unsigned long FilterType,
    atlas_j2534::PASSTHRU_MSG* pMaskMsg,
    atlas_j2534::PASSTHRU_MSG* pPatternMsg,
    atlas_j2534::PASSTHRU_MSG* pFlowControlMsg,
    unsigned long* pFilterID) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  std::ostringstream arguments;
  arguments << "{\"filterType\":" << FilterType
            << ",\"filterIdPointerPresent\":"
            << (pFilterID == nullptr ? "false" : "true")
            << ",\"maskMsg\":" << MessageJson(pMaskMsg)
            << ",\"patternMsg\":" << MessageJson(pPatternMsg)
            << ",\"flowControlMsg\":" << MessageJson(pFlowControlMsg)
            << "}";
  const auto call = BeginCall(
      "PassThruStartMsgFilter", std::nullopt, arguments.str(), ChannelID);
  const long result = g_start_filter(
      ChannelID, FilterType, pMaskMsg, pPatternMsg, pFlowControlMsg, pFilterID);
  std::ostringstream outputs;
  outputs << "{\"filterId\":";
  if (result == atlas_j2534::STATUS_NOERROR && pFilterID != nullptr) {
    outputs << *pFilterID;
  } else {
    outputs << "null";
  }
  outputs << "}";
  EndCall(call, "PassThruStartMsgFilter", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruStopMsgFilter(
    unsigned long ChannelID, unsigned long FilterID) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  std::ostringstream arguments;
  arguments << "{\"filterId\":" << FilterID << "}";
  const auto call = BeginCall(
      "PassThruStopMsgFilter", std::nullopt, arguments.str(), ChannelID);
  const long result = g_stop_filter(ChannelID, FilterID);
  EndCall(call, "PassThruStopMsgFilter", result, "{}");
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruReadMsgs(
    unsigned long ChannelID, atlas_j2534::PASSTHRU_MSG* pMsg,
    unsigned long* pNumMsgs, unsigned long Timeout) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;

  const bool count_pointer_present = pNumMsgs != nullptr;
  const unsigned long requested_count = count_pointer_present ? *pNumMsgs : 0;
  std::ostringstream arguments;
  arguments << "{\"messageBufferPresent\":"
            << (pMsg == nullptr ? "false" : "true")
            << ",\"numMsgsPointerPresent\":"
            << (count_pointer_present ? "true" : "false")
            << ",\"requestedMessageCount\":";
  if (count_pointer_present) arguments << requested_count;
  else arguments << "null";
  arguments << ",\"timeoutMs\":" << Timeout << "}";

  const auto call = BeginCall(
      "PassThruReadMsgs", std::nullopt, arguments.str(), ChannelID);
  const long result = g_read_msgs(ChannelID, pMsg, pNumMsgs, Timeout);

  const unsigned long returned_count = count_pointer_present ? *pNumMsgs : 0;
  const unsigned long captured_count =
      (pMsg != nullptr && count_pointer_present)
          ? std::min(returned_count, requested_count)
          : 0;
  std::ostringstream outputs;
  outputs << "{\"returnedMessageCount\":";
  if (count_pointer_present) outputs << returned_count;
  else outputs << "null";
  outputs << ",\"capturedMessageCount\":" << captured_count
          << ",\"messagesTruncated\":"
          << (returned_count > captured_count ? "true" : "false")
          << ",\"messages\":" << MessageArrayJson(pMsg, captured_count)
          << "}";
  EndCall(call, "PassThruReadMsgs", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruWriteMsgs(
    unsigned long ChannelID, atlas_j2534::PASSTHRU_MSG* pMsg,
    unsigned long* pNumMsgs, unsigned long Timeout) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;

  const bool count_pointer_present = pNumMsgs != nullptr;
  const unsigned long requested_count = count_pointer_present ? *pNumMsgs : 0;
  const unsigned long captured_count =
      (pMsg != nullptr && count_pointer_present) ? requested_count : 0;
  std::ostringstream arguments;
  arguments << "{\"messageBufferPresent\":"
            << (pMsg == nullptr ? "false" : "true")
            << ",\"numMsgsPointerPresent\":"
            << (count_pointer_present ? "true" : "false")
            << ",\"requestedMessageCount\":";
  if (count_pointer_present) arguments << requested_count;
  else arguments << "null";
  arguments << ",\"timeoutMs\":" << Timeout << "}";

  const auto call = BeginCall(
      "PassThruWriteMsgs", std::nullopt, arguments.str(), ChannelID,
      TraceMessageArrayJson(pMsg, captured_count));
  const long result = g_write_msgs(ChannelID, pMsg, pNumMsgs, Timeout);

  std::ostringstream outputs;
  outputs << "{\"returnedMessageCount\":";
  if (count_pointer_present) outputs << *pNumMsgs;
  else outputs << "null";
  outputs << "}";
  EndCall(call, "PassThruWriteMsgs", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruIoctl(
    unsigned long ChannelID, unsigned long IoctlID,
    void* pInput, void* pOutput) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const std::string arguments = IoctlArgumentsJson(IoctlID, pInput, pOutput);
  const auto call = BeginCall(
      "PassThruIoctl", std::nullopt, arguments, ChannelID);
  const long result = g_ioctl(ChannelID, IoctlID, pInput, pOutput);
  EndCall(call, "PassThruIoctl", result,
          IoctlOutputsJson(IoctlID, pInput, pOutput));
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruSetProgrammingVoltage(
    unsigned long DeviceID, unsigned long PinNumber, unsigned long Voltage) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const bool policy_enabled = ProgrammingVoltageExplicitlyEnabled();
  std::ostringstream arguments;
  arguments << "{\"pinNumber\":" << PinNumber
            << ",\"voltage\":" << Voltage
            << ",\"policyEnabled\":"
            << (policy_enabled ? "true" : "false")
            << ",\"providerFunctionPresent\":"
            << (g_set_programming_voltage != nullptr ? "true" : "false")
            << "}";
  const auto call = BeginCall(
      "PassThruSetProgrammingVoltage", DeviceID, arguments.str());
  bool provider_called = false;
  const long result = ForwardProgrammingVoltageWithPolicy(
      policy_enabled, g_set_programming_voltage, DeviceID, PinNumber, Voltage,
      &provider_called);
  std::ostringstream outputs;
  outputs << "{\"providerCalled\":"
          << (provider_called ? "true" : "false") << "}";
  EndCall(call, "PassThruSetProgrammingVoltage", result, outputs.str());
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
  outputs << "{\"firmwareVersion\":"
          << JsonString(BoundedCString(pFirmwareVersion, 80))
          << ",\"dllVersion\":"
          << JsonString(BoundedCString(pDllVersion, 80))
          << ",\"apiVersion\":"
          << JsonString(BoundedCString(pApiVersion, 80)) << "}";
  EndCall(call, "PassThruReadVersion", result, outputs.str());
  return result;
}

extern "C" __declspec(dllexport) long WINAPI PassThruGetLastError(
    char* pErrorDescription) {
  if (!EnsureInitialized()) return atlas_j2534::ERR_FAILED;
  const auto call = BeginCall("PassThruGetLastError", std::nullopt, "{}");
  const long result = g_get_last_error(pErrorDescription);
  const std::string description = BoundedCString(pErrorDescription, 80);
  EndCall(call, "PassThruGetLastError", result,
          std::string("{\"errorDescription\":") + JsonString(description) + "}");
  return result;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    g_self_module = instance;
    DisableThreadLibraryCalls(instance);
  }
  return TRUE;
}
