#include "atlas_gs_usb_plugin.h"

#include <flutter/standard_method_codec.h>

#include <windows.h>
#include <setupapi.h>
#include <usb.h>
#include <winusb.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr uint16_t kGsUsbVid = 0x1D50;
constexpr uint16_t kGsUsbPid = 0x606F;
constexpr uint16_t kCandleLightVid = 0x1209;
constexpr uint16_t kCandleLightPid = 0x2323;
constexpr UCHAR kRequestHostFormat = 0;
constexpr UCHAR kRequestBitTiming = 1;
constexpr UCHAR kRequestMode = 2;
constexpr uint32_t kModeReset = 0;
constexpr uint32_t kModeStart = 1;
constexpr UCHAR kRequestTypeVendorInterfaceOut = 0x41;

#pragma pack(push, 1)
struct GsHostConfig {
  uint32_t byte_order;
};
struct GsDeviceBitTiming {
  uint32_t prop_seg;
  uint32_t phase_seg1;
  uint32_t phase_seg2;
  uint32_t sjw;
  uint32_t brp;
};
struct GsDeviceMode {
  uint32_t mode;
  uint32_t flags;
};
#pragma pack(pop)

HANDLE g_device = INVALID_HANDLE_VALUE;
WINUSB_INTERFACE_HANDLE g_usb = nullptr;
UCHAR g_bulk_in = 0;
UCHAR g_bulk_out = 0;
std::wstring g_path;

std::string WideToUtf8(const std::wstring& value) {
  if (value.empty()) return {};
  const int length = WideCharToMultiByte(CP_UTF8, 0, value.c_str(),
                                         static_cast<int>(value.size()), nullptr,
                                         0, nullptr, nullptr);
  std::string result(length, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()),
                      result.data(), length, nullptr, nullptr);
  return result;
}

std::wstring Utf8ToWide(const std::string& value) {
  if (value.empty()) return {};
  const int length = MultiByteToWideChar(CP_UTF8, 0, value.c_str(),
                                         static_cast<int>(value.size()), nullptr,
                                         0);
  std::wstring result(length, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()),
                      result.data(), length);
  return result;
}

std::wstring Lower(std::wstring value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](wchar_t c) { return static_cast<wchar_t>(towlower(c)); });
  return value;
}

bool IsSupportedPath(const std::wstring& path) {
  const auto lower = Lower(path);
  return (lower.find(L"vid_1d50&pid_606f") != std::wstring::npos) ||
         (lower.find(L"vid_1209&pid_2323") != std::wstring::npos);
}

std::string DeviceLabel(const std::wstring& path) {
  const auto lower = Lower(path);
  if (lower.find(L"vid_1d50&pid_606f") != std::wstring::npos) {
    return "CANable / gs_usb (1D50:606F)";
  }
  return "candleLight / gs_usb (1209:2323)";
}

std::vector<std::wstring> ScanDevicePaths() {
  std::vector<std::wstring> result;
  HDEVINFO info = SetupDiGetClassDevsW(&GUID_DEVINTERFACE_USB_DEVICE, nullptr,
                                       nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
  if (info == INVALID_HANDLE_VALUE) return result;

  SP_DEVICE_INTERFACE_DATA interface_data{};
  interface_data.cbSize = sizeof(interface_data);
  for (DWORD index = 0; SetupDiEnumDeviceInterfaces(
           info, nullptr, &GUID_DEVINTERFACE_USB_DEVICE, index, &interface_data);
       ++index) {
    DWORD required = 0;
    SetupDiGetDeviceInterfaceDetailW(info, &interface_data, nullptr, 0, &required,
                                     nullptr);
    if (required == 0) continue;
    std::vector<uint8_t> buffer(required);
    auto* detail = reinterpret_cast<SP_DEVICE_INTERFACE_DETAIL_DATA_W*>(buffer.data());
    detail->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
    if (!SetupDiGetDeviceInterfaceDetailW(info, &interface_data, detail, required,
                                          nullptr, nullptr)) {
      continue;
    }
    std::wstring path(detail->DevicePath);
    if (IsSupportedPath(path)) result.push_back(path);
  }
  SetupDiDestroyDeviceInfoList(info);
  return result;
}

void CloseDevice() {
  if (g_usb != nullptr) {
    GsDeviceMode reset{kModeReset, 0};
    WINUSB_SETUP_PACKET setup{kRequestTypeVendorInterfaceOut, kRequestMode, 0, 0,
                              static_cast<USHORT>(sizeof(reset))};
    ULONG transferred = 0;
    WinUsb_ControlTransfer(g_usb, setup, reinterpret_cast<PUCHAR>(&reset),
                           sizeof(reset), &transferred, nullptr);
    WinUsb_Free(g_usb);
    g_usb = nullptr;
  }
  if (g_device != INVALID_HANDLE_VALUE) {
    CloseHandle(g_device);
    g_device = INVALID_HANDLE_VALUE;
  }
  g_bulk_in = 0;
  g_bulk_out = 0;
  g_path.clear();
}

bool ControlOut(UCHAR request, void* data, USHORT length, std::string* error) {
  WINUSB_SETUP_PACKET setup{kRequestTypeVendorInterfaceOut, request, 0, 0, length};
  ULONG transferred = 0;
  if (!WinUsb_ControlTransfer(g_usb, setup, reinterpret_cast<PUCHAR>(data), length,
                              &transferred, nullptr)) {
    std::ostringstream out;
    out << "WinUSB control request " << static_cast<int>(request)
        << " failed, Windows error " << GetLastError();
    *error = out.str();
    return false;
  }
  if (transferred != length) {
    *error = "Short WinUSB control transfer.";
    return false;
  }
  return true;
}

uint32_t BrpForBitrate(int bitrate) {
  switch (bitrate) {
    case 125000:
      return 24;
    case 250000:
      return 12;
    case 500000:
      return 6;
    case 1000000:
      return 3;
    default:
      return 0;
  }
}

bool OpenDevice(const std::wstring& path, int bitrate, std::string* error) {
  CloseDevice();
  const uint32_t brp = BrpForBitrate(bitrate);
  if (brp == 0) {
    *error = "Unsupported gs_usb bitrate. Use 125k, 250k, 500k, or 1M.";
    return false;
  }

  g_device = CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                         FILE_ATTRIBUTE_NORMAL, nullptr);
  if (g_device == INVALID_HANDLE_VALUE) {
    std::ostringstream out;
    out << "Could not open candleLight WinUSB device. Windows error "
        << GetLastError();
    *error = out.str();
    return false;
  }

  if (!WinUsb_Initialize(g_device, &g_usb)) {
    std::ostringstream out;
    out << "WinUsb_Initialize failed. Windows error " << GetLastError()
        << ". The adapter must be using the WinUSB driver.";
    *error = out.str();
    CloseDevice();
    return false;
  }

  USB_INTERFACE_DESCRIPTOR descriptor{};
  if (!WinUsb_QueryInterfaceSettings(g_usb, 0, &descriptor)) {
    *error = "Could not read gs_usb interface settings.";
    CloseDevice();
    return false;
  }
  for (UCHAR i = 0; i < descriptor.bNumEndpoints; ++i) {
    WINUSB_PIPE_INFORMATION pipe{};
    if (!WinUsb_QueryPipe(g_usb, 0, i, &pipe)) continue;
    if (pipe.PipeType != UsbdPipeTypeBulk) continue;
    if (USB_ENDPOINT_DIRECTION_IN(pipe.PipeId)) {
      g_bulk_in = pipe.PipeId;
    } else {
      g_bulk_out = pipe.PipeId;
    }
  }
  if (g_bulk_in == 0) {
    *error = "gs_usb bulk IN endpoint was not found.";
    CloseDevice();
    return false;
  }

  ULONG timeout = 2;
  WinUsb_SetPipePolicy(g_usb, g_bulk_in, PIPE_TRANSFER_TIMEOUT, sizeof(timeout),
                       &timeout);

  GsHostConfig host{0x0000BEEF};
  if (!ControlOut(kRequestHostFormat, &host, sizeof(host), error)) {
    CloseDevice();
    return false;
  }

  GsDeviceMode reset{kModeReset, 0};
  if (!ControlOut(kRequestMode, &reset, sizeof(reset), error)) {
    CloseDevice();
    return false;
  }

  // 48 MHz candleLight clock, 16 time quanta per bit, ~81.25% sample point.
  GsDeviceBitTiming timing{1, 11, 3, 1, brp};
  if (!ControlOut(kRequestBitTiming, &timing, sizeof(timing), error)) {
    CloseDevice();
    return false;
  }

  GsDeviceMode start{kModeStart, 0};
  if (!ControlOut(kRequestMode, &start, sizeof(start), error)) {
    CloseDevice();
    return false;
  }

  g_path = path;
  return true;
}

}  // namespace

AtlasGsUsbPlugin::AtlasGsUsbPlugin() = default;
AtlasGsUsbPlugin::~AtlasGsUsbPlugin() { CloseDevice(); }

void AtlasGsUsbPlugin::RegisterWithRegistrar(
    flutter::PluginRegistrarWindows* registrar) {
  auto channel = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      registrar->messenger(), "obd_atlas/gs_usb",
      &flutter::StandardMethodCodec::GetInstance());

  auto plugin = std::make_unique<AtlasGsUsbPlugin>();
  channel->SetMethodCallHandler(
      [plugin_pointer = plugin.get()](const auto& call, auto result) {
        plugin_pointer->HandleMethodCall(call, std::move(result));
      });
  registrar->AddPlugin(std::move(plugin));
}

void AtlasGsUsbPlugin::HandleMethodCall(
    const flutter::MethodCall<flutter::EncodableValue>& method_call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  if (method_call.method_name() == "scan") {
    flutter::EncodableList devices;
    for (const auto& path : ScanDevicePaths()) {
      devices.emplace_back(flutter::EncodableMap{
          {flutter::EncodableValue("path"), flutter::EncodableValue(WideToUtf8(path))},
          {flutter::EncodableValue("label"), flutter::EncodableValue(DeviceLabel(path))},
      });
    }
    result->Success(flutter::EncodableValue(devices));
    return;
  }

  if (method_call.method_name() == "connect") {
    const auto* args = std::get_if<flutter::EncodableMap>(method_call.arguments());
    if (args == nullptr) {
      result->Error("bad_args", "Missing connect arguments.");
      return;
    }
    const auto path_it = args->find(flutter::EncodableValue("path"));
    const auto bitrate_it = args->find(flutter::EncodableValue("bitrate"));
    if (path_it == args->end() || bitrate_it == args->end()) {
      result->Error("bad_args", "Connect requires path and bitrate.");
      return;
    }
    const auto* path = std::get_if<std::string>(&path_it->second);
    const auto* bitrate32 = std::get_if<int32_t>(&bitrate_it->second);
    const auto* bitrate64 = std::get_if<int64_t>(&bitrate_it->second);
    if (path == nullptr || (bitrate32 == nullptr && bitrate64 == nullptr)) {
      result->Error("bad_args", "Invalid path or bitrate.");
      return;
    }
    const int bitrate = bitrate32 != nullptr ? *bitrate32 : static_cast<int>(*bitrate64);
    std::string error;
    if (!OpenDevice(Utf8ToWide(*path), bitrate, &error)) {
      result->Error("gs_usb_connect", error);
      return;
    }
    result->Success();
    return;
  }

  if (method_call.method_name() == "readFrame") {
    if (g_usb == nullptr || g_bulk_in == 0) {
      result->Success();
      return;
    }
    std::vector<uint8_t> buffer(64);
    ULONG transferred = 0;
    if (!WinUsb_ReadPipe(g_usb, g_bulk_in, buffer.data(),
                         static_cast<ULONG>(buffer.size()), &transferred, nullptr)) {
      const DWORD error = GetLastError();
      if (error == ERROR_SEM_TIMEOUT || error == ERROR_TIMEOUT) {
        result->Success();
        return;
      }
      std::ostringstream out;
      out << "WinUSB bulk read failed, Windows error " << error;
      result->Error("gs_usb_read", out.str());
      return;
    }
    if (transferred < 20) {
      result->Success();
      return;
    }
    buffer.resize(transferred);
    result->Success(flutter::EncodableValue(buffer));
    return;
  }

  if (method_call.method_name() == "disconnect") {
    CloseDevice();
    result->Success();
    return;
  }

  result->NotImplemented();
}
