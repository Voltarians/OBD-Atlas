#include "atlas_lys_usbcan_plugin.h"

#include <flutter/standard_method_codec.h>
#include <windows.h>

#include <cstdint>
#include <cstring>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr DWORD kVciUsbCan2 = 4;
constexpr DWORD kStatusOk = 1;
constexpr DWORD kBatchSize = 256;

struct VciCanObj {
  uint32_t id;
  uint32_t timeStamp;
  uint8_t timeFlag;
  uint8_t sendType;
  uint8_t remoteFlag;
  uint8_t externFlag;
  uint8_t dataLen;
  uint8_t data[8];
  uint8_t reserved[3];
};
static_assert(sizeof(VciCanObj) == 24, "Unexpected VCI_CAN_OBJ layout");

struct VciInitConfig {
  uint32_t accCode;
  uint32_t accMask;
  uint32_t reserved;
  uint8_t filter;
  uint8_t timing0;
  uint8_t timing1;
  uint8_t mode;
};
static_assert(sizeof(VciInitConfig) == 16, "Unexpected VCI_INIT_CONFIG layout");

using OpenDeviceFn = DWORD(WINAPI*)(DWORD, DWORD, DWORD);
using CloseDeviceFn = DWORD(WINAPI*)(DWORD, DWORD);
using InitCanFn = DWORD(WINAPI*)(DWORD, DWORD, DWORD, VciInitConfig*);
using StartCanFn = DWORD(WINAPI*)(DWORD, DWORD, DWORD);
using ResetCanFn = DWORD(WINAPI*)(DWORD, DWORD, DWORD);
using ReceiveFn = DWORD(WINAPI*)(DWORD, DWORD, DWORD, VciCanObj*, DWORD, int);

HMODULE g_module = nullptr;
OpenDeviceFn g_openDevice = nullptr;
CloseDeviceFn g_closeDevice = nullptr;
InitCanFn g_initCan = nullptr;
StartCanFn g_startCan = nullptr;
ResetCanFn g_resetCan = nullptr;
ReceiveFn g_receive = nullptr;
bool g_open = false;
DWORD g_deviceIndex = 0;
int g_selectedDeviceIndex = -1;
std::wstring g_loadedPath;

std::string WindowsError(DWORD code) {
  std::ostringstream out;
  out << code;
  return out.str();
}

bool FileExists(const std::wstring& path) {
  const DWORD attrs = GetFileAttributesW(path.c_str());
  return attrs != INVALID_FILE_ATTRIBUTES &&
         (attrs & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

std::wstring ExecutableDirectory() {
  std::vector<wchar_t> buffer(32768, L'\0');
  const DWORD length = GetModuleFileNameW(
      nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
  if (length == 0 || length >= buffer.size()) return {};
  std::wstring path(buffer.data(), length);
  const auto slash = path.find_last_of(L"\\/");
  if (slash == std::wstring::npos) return {};
  return path.substr(0, slash);
}

std::wstring EnvironmentDllPath() {
  const wchar_t* name = L"OBD_ATLAS_CONTROLCAN_DLL";
  const DWORD needed = GetEnvironmentVariableW(name, nullptr, 0);
  if (needed == 0) return {};
  std::vector<wchar_t> buffer(needed, L'\0');
  const DWORD length = GetEnvironmentVariableW(name, buffer.data(), needed);
  if (length == 0 || length >= needed) return {};
  return std::wstring(buffer.data(), length);
}

std::wstring CurrentDirectoryDllPath() {
  const DWORD needed = GetCurrentDirectoryW(0, nullptr);
  if (needed == 0) return {};
  std::vector<wchar_t> buffer(needed, L'\0');
  const DWORD length = GetCurrentDirectoryW(needed, buffer.data());
  if (length == 0 || length >= needed) return {};
  std::wstring path(buffer.data(), length);
  if (!path.empty() && path.back() != L'\\') path.push_back(L'\\');
  path += L"ControlCAN.dll";
  return path;
}

std::wstring FindDllPath() {
  const std::wstring env = EnvironmentDllPath();
  if (!env.empty() && FileExists(env)) return env;

  const std::wstring exeDir = ExecutableDirectory();
  if (!exeDir.empty()) {
    const std::wstring besideExe = exeDir + L"\\ControlCAN.dll";
    if (FileExists(besideExe)) return besideExe;
  }

  const std::wstring current = CurrentDirectoryDllPath();
  if (!current.empty() && FileExists(current)) return current;
  return {};
}

template <typename T>
T Proc(const char* name) {
  return reinterpret_cast<T>(GetProcAddress(g_module, name));
}

bool EnsureLoaded(std::string* error) {
  if (g_module) return true;

  const std::wstring path = FindDllPath();
  if (path.empty()) {
    *error = "ControlCAN.dll not found beside obd_atlas.exe or in OBD_ATLAS_CONTROLCAN_DLL.";
    return false;
  }

  g_module = LoadLibraryW(path.c_str());
  if (!g_module) {
    *error = "LoadLibraryW failed for ControlCAN.dll, Windows error " +
             WindowsError(GetLastError());
    return false;
  }

  g_openDevice = Proc<OpenDeviceFn>("VCI_OpenDevice");
  g_closeDevice = Proc<CloseDeviceFn>("VCI_CloseDevice");
  g_initCan = Proc<InitCanFn>("VCI_InitCAN");
  g_startCan = Proc<StartCanFn>("VCI_StartCAN");
  g_resetCan = Proc<ResetCanFn>("VCI_ResetCAN");
  g_receive = Proc<ReceiveFn>("VCI_Receive");

  if (!g_openDevice || !g_closeDevice || !g_initCan || !g_startCan ||
      !g_receive) {
    *error = "ControlCAN.dll is missing one or more required VCI exports.";
    FreeLibrary(g_module);
    g_module = nullptr;
    g_openDevice = nullptr;
    g_closeDevice = nullptr;
    g_initCan = nullptr;
    g_startCan = nullptr;
    g_resetCan = nullptr;
    g_receive = nullptr;
    return false;
  }

  g_loadedPath = path;
  return true;
}

void CloseVci() {
  if (!g_open) return;
  if (g_resetCan) {
    g_resetCan(kVciUsbCan2, g_deviceIndex, 1);
    g_resetCan(kVciUsbCan2, g_deviceIndex, 0);
  }
  if (g_closeDevice) g_closeDevice(kVciUsbCan2, g_deviceIndex);
  g_open = false;
}

void UnloadDll() {
  CloseVci();
  if (g_module) FreeLibrary(g_module);
  g_module = nullptr;
  g_openDevice = nullptr;
  g_closeDevice = nullptr;
  g_initCan = nullptr;
  g_startCan = nullptr;
  g_resetCan = nullptr;
  g_receive = nullptr;
  g_selectedDeviceIndex = -1;
  g_loadedPath.clear();
}

bool RawTiming(int bitrate, uint8_t* timing0, uint8_t* timing1) {
  uint16_t raw = 0;
  switch (bitrate) {
    case 1000000: raw = 0x1400; break;
    case 800000: raw = 0x1600; break;
    case 500000: raw = 0x1c00; break;
    case 250000: raw = 0x1c01; break;
    case 125000: raw = 0x1c03; break;
    case 100000: raw = 0x1c04; break;
    case 50000: raw = 0x1c09; break;
    case 20000: raw = 0x1c18; break;
    case 10000: raw = 0x1c31; break;
    default: return false;
  }
  *timing0 = static_cast<uint8_t>(raw & 0xff);
  *timing1 = static_cast<uint8_t>((raw >> 8) & 0xff);
  return true;
}

bool ProbeDevice(std::string* error) {
  if (!EnsureLoaded(error)) return false;
  if (g_open) {
    g_selectedDeviceIndex = static_cast<int>(g_deviceIndex);
    return true;
  }

  // ControlCAN numbers every device of VCI_USBCAN2 type with a DevIndex.
  // CANalyst-II also presents itself through that compatible API, so index 0
  // is not necessarily the LYS adapter when both are attached. Prefer the
  // nonzero slots first and keep index 0 as the single-adapter fallback.
  const DWORD candidates[] = {1, 2, 3, 4, 5, 6, 7, 0};
  std::ostringstream attempts;
  bool firstAttempt = true;

  for (const DWORD index : candidates) {
    const DWORD opened = g_openDevice(kVciUsbCan2, index, 0);
    if (!firstAttempt) attempts << ", ";
    attempts << index << "=" << opened;
    firstAttempt = false;
    if (opened != kStatusOk) continue;

    const DWORD closed = g_closeDevice(kVciUsbCan2, index);
    if (closed != kStatusOk) {
      std::ostringstream out;
      out << "VCI_CloseDevice(4," << index << ") returned " << closed
          << " after a successful auto-index probe.";
      *error = out.str();
      return false;
    }

    g_selectedDeviceIndex = static_cast<int>(index);
    return true;
  }

  std::ostringstream out;
  out << "No available ControlCAN USBCAN-II index opened. Tried DevIndex "
      << attempts.str()
      << ". With CANalyst-II already connected, the free index should identify the LYS adapter.";
  *error = out.str();
  return false;
}

bool OpenVci(int bitrate, int requestedDeviceIndex, std::string* error) {
  if (!EnsureLoaded(error)) return false;
  CloseVci();

  int selectedIndex = requestedDeviceIndex;
  if (selectedIndex < 0) {
    if (g_selectedDeviceIndex < 0 && !ProbeDevice(error)) return false;
    selectedIndex = g_selectedDeviceIndex;
  }
  if (selectedIndex < 0) {
    *error = "No LYS ControlCAN device index has been selected.";
    return false;
  }

  const DWORD deviceIndex = static_cast<DWORD>(selectedIndex);
  const DWORD opened = g_openDevice(kVciUsbCan2, deviceIndex, 0);
  if (opened != kStatusOk) {
    std::ostringstream out;
    out << "VCI_OpenDevice(4," << deviceIndex << ",0) returned " << opened
        << " from the native Windows plugin after auto-index selection.";
    *error = out.str();
    if (requestedDeviceIndex < 0) g_selectedDeviceIndex = -1;
    return false;
  }

  uint8_t timing0 = 0;
  uint8_t timing1 = 0;
  if (!RawTiming(bitrate, &timing0, &timing1)) {
    g_closeDevice(kVciUsbCan2, deviceIndex);
    *error = "Unsupported ControlCAN bitrate.";
    return false;
  }

  VciInitConfig config{};
  config.accCode = 0;
  config.accMask = 0xffffffff;
  config.reserved = 0;
  config.filter = 1;
  config.timing0 = timing0;
  config.timing1 = timing1;
  config.mode = 0;

  for (DWORD channel = 0; channel < 2; ++channel) {
    const DWORD initialized =
        g_initCan(kVciUsbCan2, deviceIndex, channel, &config);
    if (initialized != kStatusOk) {
      std::ostringstream out;
      out << "VCI_InitCAN channel " << channel << " on DevIndex "
          << deviceIndex << " returned " << initialized << ".";
      *error = out.str();
      g_closeDevice(kVciUsbCan2, deviceIndex);
      return false;
    }
    const DWORD started = g_startCan(kVciUsbCan2, deviceIndex, channel);
    if (started != kStatusOk) {
      std::ostringstream out;
      out << "VCI_StartCAN channel " << channel << " on DevIndex "
          << deviceIndex << " returned " << started << ".";
      *error = out.str();
      g_closeDevice(kVciUsbCan2, deviceIndex);
      return false;
    }
  }

  g_deviceIndex = deviceIndex;
  g_selectedDeviceIndex = selectedIndex;
  g_open = true;
  return true;
}

bool ReadFrames(int channel, std::vector<uint8_t>* bytes, std::string* error) {
  bytes->clear();
  if (!g_open) return true;
  if (channel < 0 || channel > 1) {
    *error = "LYS USBCAN physical channel must be 0 or 1.";
    return false;
  }

  std::vector<VciCanObj> frames(kBatchSize);
  const DWORD received = g_receive(kVciUsbCan2, g_deviceIndex,
                                   static_cast<DWORD>(channel), frames.data(),
                                   kBatchSize, 0);
  if (received == 0) return true;
  if (received > kBatchSize) {
    std::ostringstream out;
    out << "VCI_Receive returned invalid frame count " << received << ".";
    *error = out.str();
    return false;
  }

  bytes->resize(received * sizeof(VciCanObj));
  std::memcpy(bytes->data(), frames.data(), bytes->size());
  return true;
}

bool ReadInt(const flutter::EncodableValue& value, int* out) {
  if (const auto* value32 = std::get_if<int32_t>(&value)) {
    *out = *value32;
    return true;
  }
  if (const auto* value64 = std::get_if<int64_t>(&value)) {
    *out = static_cast<int>(*value64);
    return true;
  }
  return false;
}

}  // namespace

AtlasLysUsbcanPlugin::AtlasLysUsbcanPlugin() = default;
AtlasLysUsbcanPlugin::~AtlasLysUsbcanPlugin() { UnloadDll(); }

void AtlasLysUsbcanPlugin::RegisterWithRegistrar(
    flutter::PluginRegistrarWindows* registrar) {
  auto channel = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      registrar->messenger(), "obd_atlas/lys_usbcan",
      &flutter::StandardMethodCodec::GetInstance());
  auto plugin = std::make_unique<AtlasLysUsbcanPlugin>();
  channel->SetMethodCallHandler(
      [plugin_pointer = plugin.get()](const auto& call, auto result) {
        plugin_pointer->HandleMethodCall(call, std::move(result));
      });
  registrar->AddPlugin(std::move(plugin));
}

void AtlasLysUsbcanPlugin::HandleMethodCall(
    const flutter::MethodCall<flutter::EncodableValue>& call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  if (call.method_name() == "probe") {
    std::string error;
    if (!ProbeDevice(&error)) {
      result->Error("lys_probe", error);
      return;
    }
    result->Success(flutter::EncodableValue(true));
    return;
  }

  if (call.method_name() == "connect") {
    const auto* args = std::get_if<flutter::EncodableMap>(call.arguments());
    if (!args) {
      result->Error("bad_args", "Missing connect arguments.");
      return;
    }

    const auto bitrateValue = args->find(flutter::EncodableValue("bitrate"));
    const auto indexValue = args->find(flutter::EncodableValue("deviceIndex"));
    int bitrate = 500000;
    int deviceIndex = -1;
    if (bitrateValue == args->end() ||
        !ReadInt(bitrateValue->second, &bitrate)) {
      result->Error("bad_args", "Invalid bitrate.");
      return;
    }
    if (indexValue != args->end() &&
        !ReadInt(indexValue->second, &deviceIndex)) {
      result->Error("bad_args", "Invalid device index.");
      return;
    }
    if (deviceIndex < -1) {
      result->Error("bad_args", "Device index must be -1 for auto or zero or greater.");
      return;
    }

    std::string error;
    if (!OpenVci(bitrate, deviceIndex, &error)) {
      result->Error("lys_connect", error);
      return;
    }
    result->Success();
    return;
  }

  if (call.method_name() == "readFrames") {
    const auto* args = std::get_if<flutter::EncodableMap>(call.arguments());
    int channel = 0;
    if (args) {
      const auto channelValue = args->find(flutter::EncodableValue("channel"));
      if (channelValue != args->end() &&
          !ReadInt(channelValue->second, &channel)) {
        result->Error("bad_args", "Invalid LYS channel.");
        return;
      }
    }

    std::vector<uint8_t> bytes;
    std::string error;
    if (!ReadFrames(channel, &bytes, &error)) {
      result->Error("lys_read", error);
      return;
    }
    if (bytes.empty()) {
      result->Success();
      return;
    }
    result->Success(flutter::EncodableValue(bytes));
    return;
  }

  if (call.method_name() == "disconnect") {
    CloseVci();
    result->Success();
    return;
  }

  result->NotImplemented();
}
