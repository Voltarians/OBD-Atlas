#include "atlas_lys_usbcan_plugin.h"

#include <flutter/standard_method_codec.h>
#include <windows.h>
#include <setupapi.h>
#include <winusb.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <cwctype>
#include <deque>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace {

// LYS/iTekon USBCAN-II WinUSB interface installed by the libwdi driver.
// The device itself is VID 0471:PID 1200 and exposes one dual-channel CAN
// interface.  This transport intentionally bypasses ControlCAN.dll so it does
// not enumerate or claim the CANalyst-II device.
const GUID kLysInterfaceGuid =
    {0xec93623e, 0x4a7b, 0x4597, {0xa8, 0x0d, 0xb4, 0xaf, 0x34, 0x41, 0xf3, 0x8d}};

constexpr UCHAR kControlOut = 0x01;
constexpr UCHAR kControlIn = 0x81;
constexpr UCHAR kDataOut = 0x02;
constexpr UCHAR kDataIn = 0x82;
constexpr size_t kWireFrameSize = 19;
constexpr size_t kAtlasRecordSize = 24;
constexpr size_t kMaxReturnedFrames = 256;
constexpr size_t kMaxQueuedFrames = 20000;

HANDLE g_device = INVALID_HANDLE_VALUE;
WINUSB_INTERFACE_HANDLE g_usb = nullptr;
std::wstring g_path;
bool g_started = false;
std::deque<std::array<uint8_t, kAtlasRecordSize>> g_frames[2];
std::vector<uint8_t> g_rxRemainder;

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
  HDEVINFO info = SetupDiGetClassDevsW(&kLysInterfaceGuid, nullptr, nullptr,
                                       DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
  if (info == INVALID_HANDLE_VALUE) return result;

  SP_DEVICE_INTERFACE_DATA iface{};
  iface.cbSize = sizeof(iface);
  for (DWORD i = 0; SetupDiEnumDeviceInterfaces(info, nullptr,
                                                &kLysInterfaceGuid, i,
                                                &iface); ++i) {
    DWORD required = 0;
    SetupDiGetDeviceInterfaceDetailW(info, &iface, nullptr, 0, &required, nullptr);
    if (!required) continue;
    std::vector<BYTE> buffer(required);
    auto* detail = reinterpret_cast<SP_DEVICE_INTERFACE_DETAIL_DATA_W*>(buffer.data());
    detail->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
    if (!SetupDiGetDeviceInterfaceDetailW(info, &iface, detail, required,
                                          nullptr, nullptr)) {
      continue;
    }
    const std::wstring path(detail->DevicePath);
    const auto lower = Lower(path);
    if (lower.find(L"vid_0471&pid_1200") != std::wstring::npos) {
      result.push_back(path);
    }
  }
  SetupDiDestroyDeviceInfoList(info);
  return result;
}

void ClearQueues() {
  g_frames[0].clear();
  g_frames[1].clear();
  g_rxRemainder.clear();
}

void CloseUsbOnly() {
  if (g_usb) {
    WinUsb_Free(g_usb);
    g_usb = nullptr;
  }
  if (g_device != INVALID_HANDLE_VALUE) {
    CloseHandle(g_device);
    g_device = INVALID_HANDLE_VALUE;
  }
  g_path.clear();
  g_started = false;
  ClearQueues();
}

bool WritePipe(UCHAR ep, const uint8_t* data, ULONG len, std::string* error) {
  ULONG written = 0;
  if (!WinUsb_WritePipe(g_usb, ep, const_cast<PUCHAR>(data), len,
                        &written, nullptr) || written != len) {
    std::ostringstream out;
    out << "LYS WinUSB write EP0x" << std::hex << static_cast<int>(ep)
        << " failed, Windows error " << std::dec << GetLastError();
    *error = out.str();
    return false;
  }
  return true;
}

bool ReadPipe(UCHAR ep, uint8_t* data, ULONG maxLen, ULONG* read,
              bool timeoutIsEmpty, std::string* error) {
  *read = 0;
  if (WinUsb_ReadPipe(g_usb, ep, data, maxLen, read, nullptr)) return true;
  const DWORD code = GetLastError();
  if (timeoutIsEmpty && (code == ERROR_SEM_TIMEOUT || code == ERROR_TIMEOUT)) {
    *read = 0;
    return true;
  }
  std::ostringstream out;
  out << "LYS WinUSB read EP0x" << std::hex << static_cast<int>(ep)
      << " failed, Windows error " << std::dec << code;
  *error = out.str();
  return false;
}

bool ControlExchange(const uint8_t* command, ULONG commandLen,
                     std::vector<uint8_t>* response, std::string* error) {
  response->clear();
  if (!WritePipe(kControlOut, command, commandLen, error)) return false;
  std::array<uint8_t, 128> buffer{};
  ULONG read = 0;
  if (!ReadPipe(kControlIn, buffer.data(), static_cast<ULONG>(buffer.size()),
                &read, false, error)) {
    return false;
  }
  response->assign(buffer.begin(), buffer.begin() + read);
  return true;
}

bool ResponseOk(const std::vector<uint8_t>& response, const char* operation,
                std::string* error) {
  if (response.size() >= 3 && response[2] == 0x81) return true;
  std::ostringstream out;
  out << "LYS " << operation << " command was not acknowledged";
  if (response.size() >= 3) {
    out << " (reply byte 2 = 0x" << std::hex << static_cast<int>(response[2])
        << ")";
  } else {
    out << " (short reply: " << std::dec << response.size() << " bytes)";
  }
  *error = out.str();
  return false;
}

bool OpenUsb(const std::wstring& path, std::string* error) {
  CloseUsbOnly();
  // Atlas uses synchronous WinUsb_ReadPipe/WinUsb_WritePipe calls (OVERLAPPED
  // is null), so the underlying device handle must also be opened for
  // synchronous I/O. Opening it with FILE_FLAG_OVERLAPPED while issuing
  // synchronous pipe calls can leave the interrupt-IN reply path timing out.
  g_device = CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                         OPEN_EXISTING,
                         FILE_ATTRIBUTE_NORMAL, nullptr);
  if (g_device == INVALID_HANDLE_VALUE) {
    std::ostringstream out;
    out << "Could not open LYS 0471:1200 WinUSB interface, Windows error "
        << GetLastError();
    *error = out.str();
    return false;
  }
  if (!WinUsb_Initialize(g_device, &g_usb)) {
    std::ostringstream out;
    out << "WinUsb_Initialize failed for LYS, Windows error " << GetLastError();
    *error = out.str();
    CloseUsbOnly();
    return false;
  }

  ULONG controlTimeout = 1000;
  ULONG dataTimeout = 8;
  UCHAR allowPartial = TRUE;
  UCHAR autoClear = TRUE;
  WinUsb_SetPipePolicy(g_usb, kControlIn, PIPE_TRANSFER_TIMEOUT,
                       sizeof(controlTimeout), &controlTimeout);
  WinUsb_SetPipePolicy(g_usb, kDataIn, PIPE_TRANSFER_TIMEOUT,
                       sizeof(dataTimeout), &dataTimeout);
  WinUsb_SetPipePolicy(g_usb, kDataIn, ALLOW_PARTIAL_READS,
                       sizeof(allowPartial), &allowPartial);
  WinUsb_SetPipePolicy(g_usb, kControlIn, AUTO_CLEAR_STALL,
                       sizeof(autoClear), &autoClear);
  WinUsb_SetPipePolicy(g_usb, kDataIn, AUTO_CLEAR_STALL,
                       sizeof(autoClear), &autoClear);

  g_path = path;
  return true;
}

bool Authenticate(std::string* error) {
  // The open iTekon driver authenticates 0471:1200 with SM4 using the key
  // "itekon2012usbcan".  A fixed challenge is sufficient here because Atlas
  // only needs to prove compatibility with the adapter, not establish a
  // confidential session.  The expected block below is SM4-ECB(key,
  // 0123456789abcdeffedcba9876543210).
  const std::array<uint8_t, 20> command = {
      0x13, 0xb0, 0x11, 0x00,
      0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
      0xfe, 0xdc, 0xba, 0x98, 0x76, 0x54, 0x32, 0x10};
  const std::array<uint8_t, 16> expected = {
      0xc3, 0xe5, 0xe0, 0x38, 0x9c, 0x17, 0x65, 0x5f,
      0x26, 0xd9, 0x74, 0x9a, 0xe6, 0x16, 0x85, 0xb3};
  std::vector<uint8_t> response;
  if (!ControlExchange(command.data(), static_cast<ULONG>(command.size()),
                       &response, error)) {
    return false;
  }
  if (response.size() < 20 ||
      !std::equal(expected.begin(), expected.end(), response.begin() + 4)) {
    *error = "LYS hardware authentication failed on the direct WinUSB transport.";
    return false;
  }
  return true;
}

bool BitrateCode(int bitrate, uint32_t* code) {
  switch (bitrate) {
    case 5000: *code = 0x00450257; return true;
    case 10000: *code = 0x00120257; return true;
    case 20000: *code = 0x0012012b; return true;
    case 40000: *code = 0x00780031; return true;
    case 50000: *code = 0x0067002c; return true;
    case 80000: *code = 0x004b0018; return true;
    case 100000: *code = 0x0012003b; return true;
    case 125000: *code = 0x0012002f; return true;
    case 200000: *code = 0x0027000e; return true;
    case 250000: *code = 0x00120017; return true;
    case 400000: *code = 0x00160008; return true;
    case 500000: *code = 0x0012000b; return true;
    case 666000: *code = 0x00240005; return true;
    case 800000: *code = 0x00240004; return true;
    case 1000000: *code = 0x00120005; return true;
    default: return false;
  }
}

bool ConfigureChannel(int channel, int bitrate, std::string* error) {
  if (!Authenticate(error)) return false;

  uint32_t code = 0;
  if (!BitrateCode(bitrate, &code)) {
    *error = "Unsupported LYS direct-WinUSB bitrate.";
    return false;
  }

  std::array<uint8_t, 9> mode = {0x12, 0x23, 0x06, 0x00, 0x00,
                                  0x00, 0x00, 0x00, 0x00};
  mode[4] = static_cast<uint8_t>((channel & 1) << 4);  // normal mode
  mode[5] = static_cast<uint8_t>(code >> 24);
  mode[6] = static_cast<uint8_t>(code >> 16);
  mode[7] = static_cast<uint8_t>(code >> 8);
  mode[8] = static_cast<uint8_t>(code);

  std::vector<uint8_t> response;
  if (!ControlExchange(mode.data(), static_cast<ULONG>(mode.size()),
                       &response, error) ||
      !ResponseOk(response, "bitrate", error)) {
    return false;
  }

  // Configure all 14 hardware filters to accept all frames, matching the
  // public iTekon driver used successfully with this adapter on Linux.
  for (int filterIndex = 0; filterIndex < 14; ++filterIndex) {
    std::array<uint8_t, 14> filter{};
    filter[0] = 0x12;
    filter[1] = 0x24;
    filter[2] = 0x0b;
    filter[3] = static_cast<uint8_t>(filterIndex);
    filter[4] = static_cast<uint8_t>(0x80 | (channel & 1));
    response.clear();
    if (!ControlExchange(filter.data(), static_cast<ULONG>(filter.size()),
                         &response, error) ||
        !ResponseOk(response, "filter", error)) {
      return false;
    }
  }
  return true;
}

bool StartChannel(int channel, std::string* error) {
  std::array<uint8_t, 5> command = {
      0x12, 0x0e, 0x02, 0x00,
      static_cast<uint8_t>((channel & 1) << 4)};
  std::vector<uint8_t> response;
  return ControlExchange(command.data(), static_cast<ULONG>(command.size()),
                         &response, error) &&
         ResponseOk(response, "start", error);
}

void StopChannelBestEffort(int channel) {
  if (!g_usb) return;
  std::array<uint8_t, 5> command = {
      0x12, 0x0f, 0x02, 0x00,
      static_cast<uint8_t>((channel & 1) << 4)};
  std::vector<uint8_t> response;
  std::string ignored;
  ControlExchange(command.data(), static_cast<ULONG>(command.size()),
                  &response, &ignored);
}

bool ConnectDirect(int bitrate, std::string* error) {
  const auto paths = ScanPaths();
  if (paths.empty()) {
    *error = "LYS USBCAN-II 0471:1200 WinUSB interface was not found.";
    return false;
  }
  if (!OpenUsb(paths.front(), error)) return false;

  if (!ConfigureChannel(0, bitrate, error) ||
      !ConfigureChannel(1, bitrate, error) ||
      !StartChannel(0, error) ||
      !StartChannel(1, error)) {
    CloseUsbOnly();
    return false;
  }
  g_started = true;
  return true;
}

uint32_t GetU32(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) |
         (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) |
         (static_cast<uint32_t>(p[3]) << 24);
}

void PutU32(std::array<uint8_t, kAtlasRecordSize>* record, size_t offset,
            uint32_t value) {
  (*record)[offset] = static_cast<uint8_t>(value);
  (*record)[offset + 1] = static_cast<uint8_t>(value >> 8);
  (*record)[offset + 2] = static_cast<uint8_t>(value >> 16);
  (*record)[offset + 3] = static_cast<uint8_t>(value >> 24);
}

void QueueWireFrame(const uint8_t* wire) {
  const uint8_t flags = wire[6];
  const int channel = (flags & 0x10) ? 1 : 0;
  std::array<uint8_t, kAtlasRecordSize> record{};
  PutU32(&record, 0, GetU32(wire + 7));
  PutU32(&record, 4, GetU32(wire));
  record[8] = wire[4];
  record[9] = wire[5];
  record[10] = (flags & 0x40) ? 1 : 0;
  record[11] = (flags & 0x80) ? 1 : 0;
  record[12] = static_cast<uint8_t>(std::min<int>(flags & 0x0f, 8));
  std::memcpy(record.data() + 13, wire + 11, 8);

  auto& queue = g_frames[channel];
  if (queue.size() >= kMaxQueuedFrames) queue.pop_front();
  queue.push_back(record);
}

bool PumpFrames(std::string* error) {
  std::array<uint8_t, kWireFrameSize * 64> buffer{};
  ULONG read = 0;
  if (!ReadPipe(kDataIn, buffer.data(), static_cast<ULONG>(buffer.size()),
                &read, true, error)) {
    return false;
  }
  if (!read) return true;

  g_rxRemainder.insert(g_rxRemainder.end(), buffer.begin(), buffer.begin() + read);
  size_t offset = 0;
  while (g_rxRemainder.size() - offset >= kWireFrameSize) {
    QueueWireFrame(g_rxRemainder.data() + offset);
    offset += kWireFrameSize;
  }
  if (offset) {
    g_rxRemainder.erase(g_rxRemainder.begin(), g_rxRemainder.begin() + offset);
  }
  return true;
}

bool ReadFrames(int channel, std::vector<uint8_t>* bytes, std::string* error) {
  bytes->clear();
  if (!g_started || !g_usb) return true;
  if (channel < 0 || channel > 1) {
    *error = "LYS physical channel must be 0 or 1.";
    return false;
  }

  if (g_frames[channel].empty() && !PumpFrames(error)) return false;

  auto& queue = g_frames[channel];
  const size_t count = std::min(queue.size(), kMaxReturnedFrames);
  bytes->reserve(count * kAtlasRecordSize);
  for (size_t i = 0; i < count; ++i) {
    const auto& record = queue.front();
    bytes->insert(bytes->end(), record.begin(), record.end());
    queue.pop_front();
  }
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
AtlasLysUsbcanPlugin::~AtlasLysUsbcanPlugin() {
  if (g_started) {
    StopChannelBestEffort(1);
    StopChannelBestEffort(0);
  }
  CloseUsbOnly();
}

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
    const auto paths = ScanPaths();
    if (paths.empty()) {
      result->Error("lys_probe", "LYS USBCAN-II 0471:1200 WinUSB interface was not found.");
      return;
    }
    std::string error;
    if (!OpenUsb(paths.front(), &error)) {
      result->Error("lys_probe", error);
      return;
    }
    CloseUsbOnly();
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
    int bitrate = 500000;
    if (bitrateValue == args->end() ||
        !ReadInt(bitrateValue->second, &bitrate)) {
      result->Error("bad_args", "Invalid bitrate.");
      return;
    }

    std::string error;
    if (!ConnectDirect(bitrate, &error)) {
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
    if (g_started) {
      StopChannelBestEffort(1);
      StopChannelBestEffort(0);
    }
    CloseUsbOnly();
    result->Success();
    return;
  }

  result->NotImplemented();
}