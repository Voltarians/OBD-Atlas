#include "atlas_canalystii_plugin.h"

#include <flutter/standard_method_codec.h>
#include <windows.h>
#include <setupapi.h>
#include <winusb.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace {

const GUID kCanalystInterfaceGuid =
    {0x58d07210, 0x27c1, 0x11dd, {0xbd, 0x0b, 0x08, 0x00, 0x20, 0x0c, 0x9a, 0x66}};

HANDLE g_device = INVALID_HANDLE_VALUE;
WINUSB_INTERFACE_HANDLE g_usb = nullptr;
std::wstring g_path;

std::string WideToUtf8(const std::wstring& value) {
  if (value.empty()) return {};
  const int n = WideCharToMultiByte(CP_UTF8, 0, value.c_str(),
                                    static_cast<int>(value.size()), nullptr, 0,
                                    nullptr, nullptr);
  std::string out(n, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()),
                      out.data(), n, nullptr, nullptr);
  return out;
}

std::wstring Utf8ToWide(const std::string& value) {
  if (value.empty()) return {};
  const int n = MultiByteToWideChar(CP_UTF8, 0, value.c_str(),
                                    static_cast<int>(value.size()), nullptr, 0);
  std::wstring out(n, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()),
                      out.data(), n);
  return out;
}

std::wstring Lower(std::wstring value) {
  std::transform(value.begin(), value.end(), value.begin(), ::towlower);
  return value;
}

std::vector<std::wstring> ScanPaths() {
  std::vector<std::wstring> result;
  HDEVINFO info = SetupDiGetClassDevsW(&kCanalystInterfaceGuid, nullptr, nullptr,
                                       DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
  if (info == INVALID_HANDLE_VALUE) return result;

  SP_DEVICE_INTERFACE_DATA iface{};
  iface.cbSize = sizeof(iface);
  for (DWORD i = 0; SetupDiEnumDeviceInterfaces(info, nullptr,
                                                &kCanalystInterfaceGuid, i,
                                                &iface); ++i) {
    DWORD required = 0;
    SetupDiGetDeviceInterfaceDetailW(info, &iface, nullptr, 0, &required, nullptr);
    if (!required) continue;
    std::vector<BYTE> buffer(required);
    auto* detail = reinterpret_cast<SP_DEVICE_INTERFACE_DETAIL_DATA_W*>(buffer.data());
    detail->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
    if (!SetupDiGetDeviceInterfaceDetailW(info, &iface, detail, required,
                                          nullptr, nullptr)) continue;
    const std::wstring path(detail->DevicePath);
    const auto lower = Lower(path);
    if (lower.find(L"vid_04d8&pid_0053") != std::wstring::npos) result.push_back(path);
  }
  SetupDiDestroyDeviceInfoList(info);
  return result;
}

void CloseDevice() {
  if (g_usb) {
    WinUsb_Free(g_usb);
    g_usb = nullptr;
  }
  if (g_device != INVALID_HANDLE_VALUE) {
    CloseHandle(g_device);
    g_device = INVALID_HANDLE_VALUE;
  }
  g_path.clear();
}

bool WritePipe(UCHAR ep, const void* data, ULONG len, std::string* error) {
  ULONG written = 0;
  if (!WinUsb_WritePipe(g_usb, ep,
                        reinterpret_cast<PUCHAR>(const_cast<void*>(data)),
                        len, &written, nullptr) || written != len) {
    std::ostringstream out;
    out << "CANalyst-II USB write EP" << static_cast<int>(ep)
        << " failed, Windows error " << GetLastError();
    *error = out.str();
    return false;
  }
  return true;
}

bool ReadPipe(UCHAR ep, std::vector<uint8_t>* data, ULONG len,
              std::string* error) {
  data->assign(len, 0);
  ULONG read = 0;
  if (!WinUsb_ReadPipe(g_usb, ep, data->data(), len, &read, nullptr)) {
    const DWORD code = GetLastError();
    if (code == ERROR_SEM_TIMEOUT || code == ERROR_TIMEOUT) {
      data->clear();
      return true;
    }
    std::ostringstream out;
    out << "CANalyst-II USB read EP" << static_cast<int>(ep)
        << " failed, Windows error " << code;
    *error = out.str();
    return false;
  }
  data->resize(read);
  return true;
}

void PutU32(std::vector<uint8_t>* b, size_t offset, uint32_t value) {
  (*b)[offset] = static_cast<uint8_t>(value);
  (*b)[offset + 1] = static_cast<uint8_t>(value >> 8);
  (*b)[offset + 2] = static_cast<uint8_t>(value >> 16);
  (*b)[offset + 3] = static_cast<uint8_t>(value >> 24);
}

uint32_t GetU32(const std::vector<uint8_t>& b, size_t offset) {
  return static_cast<uint32_t>(b[offset]) |
         (static_cast<uint32_t>(b[offset + 1]) << 8) |
         (static_cast<uint32_t>(b[offset + 2]) << 16) |
         (static_cast<uint32_t>(b[offset + 3]) << 24);
}

bool Timings(int bitrate, uint32_t* t0, uint32_t* t1) {
  switch (bitrate) {
    case 125000: *t0 = 0x03; *t1 = 0x1c; return true;
    case 250000: *t0 = 0x01; *t1 = 0x1c; return true;
    case 500000: *t0 = 0x00; *t1 = 0x1c; return true;
    case 1000000: *t0 = 0x00; *t1 = 0x14; return true;
    default: return false;
  }
}

UCHAR CommandOut(int channel) { return channel == 0 ? 0x02 : 0x04; }
UCHAR CommandIn(int channel) { return channel == 0 ? 0x82 : 0x84; }
UCHAR MessageIn(int channel) { return channel == 0 ? 0x81 : 0x83; }

bool SendSimple(int channel, uint32_t command, std::string* error) {
  std::vector<uint8_t> packet(64, 0);
  PutU32(&packet, 0, command);
  return WritePipe(CommandOut(channel), packet.data(), 64, error);
}

bool InitChannel(int channel, int bitrate, std::string* error) {
  uint32_t t0 = 0, t1 = 0;
  if (!Timings(bitrate, &t0, &t1)) {
    *error = "CANalyst-II supports 125k, 250k, 500k, or 1M in this Atlas build.";
    return false;
  }
  std::vector<uint8_t> packet(64, 0);
  PutU32(&packet, 0, 0x01);
  PutU32(&packet, 4, 0x01);
  PutU32(&packet, 8, 0xffffffff);
  PutU32(&packet, 16, 0x01);
  PutU32(&packet, 24, t0);
  PutU32(&packet, 28, t1);
  PutU32(&packet, 32, 0x00);
  PutU32(&packet, 36, 0x01);
  if (!WritePipe(CommandOut(channel), packet.data(), 64, error)) return false;
  return SendSimple(channel, 0x02, error);
}

bool OpenDevice(const std::wstring& path, int bitrate, std::string* error) {
  CloseDevice();
  g_device = CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                         FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, nullptr);
  if (g_device == INVALID_HANDLE_VALUE) {
    std::ostringstream out;
    out << "Could not open CANalyst-II WinUSB interface, Windows error " << GetLastError();
    *error = out.str();
    return false;
  }
  if (!WinUsb_Initialize(g_device, &g_usb)) {
    std::ostringstream out;
    out << "WinUsb_Initialize failed for CANalyst-II, Windows error " << GetLastError();
    *error = out.str();
    CloseDevice();
    return false;
  }

  ULONG timeout = 10;
  const UCHAR eps[] = {0x81, 0x82, 0x83, 0x84};
  for (UCHAR ep : eps) {
    WinUsb_SetPipePolicy(g_usb, ep, PIPE_TRANSFER_TIMEOUT, sizeof(timeout), &timeout);
  }

  if (!InitChannel(0, bitrate, error) || !InitChannel(1, bitrate, error)) {
    CloseDevice();
    return false;
  }
  g_path = path;
  return true;
}

bool ReadFrames(int channel, std::vector<uint8_t>* frames, std::string* error) {
  frames->clear();
  if (!g_usb) return true;
  if (!SendSimple(channel, 0x0a, error)) return false;
  std::vector<uint8_t> status;
  if (!ReadPipe(CommandIn(channel), &status, 64, error)) return false;
  if (status.size() < 8) return true;
  const uint32_t pending = GetU32(status, 4);
  if (!pending) return true;
  const uint32_t buffers = (pending + 2) / 3 + 1;
  const ULONG bytes = static_cast<ULONG>(std::min<uint32_t>(buffers * 64, 4096));
  return ReadPipe(MessageIn(channel), frames, bytes, error);
}

}  // namespace

AtlasCanalystiiPlugin::AtlasCanalystiiPlugin() = default;
AtlasCanalystiiPlugin::~AtlasCanalystiiPlugin() { CloseDevice(); }

void AtlasCanalystiiPlugin::RegisterWithRegistrar(
    flutter::PluginRegistrarWindows* registrar) {
  auto channel = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      registrar->messenger(), "obd_atlas/canalystii",
      &flutter::StandardMethodCodec::GetInstance());
  auto plugin = std::make_unique<AtlasCanalystiiPlugin>();
  channel->SetMethodCallHandler(
      [plugin_pointer = plugin.get()](const auto& call, auto result) {
        plugin_pointer->HandleMethodCall(call, std::move(result));
      });
  registrar->AddPlugin(std::move(plugin));
}

void AtlasCanalystiiPlugin::HandleMethodCall(
    const flutter::MethodCall<flutter::EncodableValue>& call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  if (call.method_name() == "scan") {
    flutter::EncodableList devices;
    for (const auto& path : ScanPaths()) {
      devices.emplace_back(flutter::EncodableMap{
          {flutter::EncodableValue("path"), flutter::EncodableValue(WideToUtf8(path))},
          {flutter::EncodableValue("label"), flutter::EncodableValue("Chuangxin CANalyst-II (04D8:0053)")},
      });
    }
    result->Success(flutter::EncodableValue(devices));
    return;
  }

  if (call.method_name() == "connect") {
    const auto* args = std::get_if<flutter::EncodableMap>(call.arguments());
    if (!args) { result->Error("bad_args", "Missing connect arguments."); return; }
    const auto p = args->find(flutter::EncodableValue("path"));
    const auto b = args->find(flutter::EncodableValue("bitrate"));
    if (p == args->end() || b == args->end()) { result->Error("bad_args", "Missing path or bitrate."); return; }
    const auto* path = std::get_if<std::string>(&p->second);
    const auto* bitrate32 = std::get_if<int32_t>(&b->second);
    const auto* bitrate64 = std::get_if<int64_t>(&b->second);
    if (!path || (!bitrate32 && !bitrate64)) { result->Error("bad_args", "Invalid path or bitrate."); return; }
    const int bitrate = bitrate32 ? *bitrate32 : static_cast<int>(*bitrate64);
    std::string error;
    if (!OpenDevice(Utf8ToWide(*path), bitrate, &error)) { result->Error("canalystii_connect", error); return; }
    result->Success();
    return;
  }

  if (call.method_name() == "readFrames") {
    const auto* args = std::get_if<flutter::EncodableMap>(call.arguments());
    int channel = 0;
    if (args) {
      const auto c = args->find(flutter::EncodableValue("channel"));
      if (c != args->end()) {
        if (const auto* c32 = std::get_if<int32_t>(&c->second)) channel = *c32;
        if (const auto* c64 = std::get_if<int64_t>(&c->second)) channel = static_cast<int>(*c64);
      }
    }
    if (channel < 0 || channel > 1) { result->Error("bad_args", "CANalyst-II channel must be 0 or 1."); return; }
    std::vector<uint8_t> frames;
    std::string error;
    if (!ReadFrames(channel, &frames, &error)) { result->Error("canalystii_read", error); return; }
    if (frames.empty()) { result->Success(); return; }
    result->Success(flutter::EncodableValue(frames));
    return;
  }

  if (call.method_name() == "disconnect") {
    std::string ignored;
    if (g_usb) {
      SendSimple(0, 0x03, &ignored);
      SendSimple(1, 0x03, &ignored);
    }
    CloseDevice();
    result->Success();
    return;
  }

  result->NotImplemented();
}
