#include "atlas_gs_usb_plugin.h"

#include <flutter/standard_method_codec.h>

#include <windows.h>
#include <setupapi.h>
#include <usb.h>
#include <winusb.h>

#include <algorithm>
#include <cstdint>
#include <cwctype>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr UCHAR kRequestHostFormat = 0;
constexpr UCHAR kRequestBitTiming = 1;
constexpr UCHAR kRequestMode = 2;
constexpr uint32_t kModeReset = 0;
constexpr uint32_t kModeStart = 1;
constexpr UCHAR kRequestTypeVendorInterfaceOut = 0x41;

#pragma pack(push, 1)
struct GsHostConfig { uint32_t byte_order; };
struct GsDeviceBitTiming {
  uint32_t prop_seg;
  uint32_t phase_seg1;
  uint32_t phase_seg2;
  uint32_t sjw;
  uint32_t brp;
};
struct GsDeviceMode { uint32_t mode; uint32_t flags; };
#pragma pack(pop)

struct DiscoveredDevice {
  std::wstring path;
  std::wstring instance_id;
  std::wstring service;
};

HANDLE g_device = INVALID_HANDLE_VALUE;
WINUSB_INTERFACE_HANDLE g_usb = nullptr;
UCHAR g_bulk_in = 0;
UCHAR g_bulk_out = 0;
std::wstring g_path;

std::wstring Lower(std::wstring value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](wchar_t c) { return static_cast<wchar_t>(towlower(c)); });
  return value;
}

std::string WideToUtf8(const std::wstring& value) {
  if (value.empty()) return {};
  const int n = WideCharToMultiByte(CP_UTF8, 0, value.c_str(),
                                    static_cast<int>(value.size()), nullptr, 0,
                                    nullptr, nullptr);
  std::string out(n, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value.c_str(),
                      static_cast<int>(value.size()), out.data(), n,
                      nullptr, nullptr);
  return out;
}

std::wstring Utf8ToWide(const std::string& value) {
  if (value.empty()) return {};
  const int n = MultiByteToWideChar(CP_UTF8, 0, value.c_str(),
                                    static_cast<int>(value.size()), nullptr, 0);
  std::wstring out(n, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, value.c_str(),
                      static_cast<int>(value.size()), out.data(), n);
  return out;
}

bool IsGsUsbInstance(const std::wstring& instance_id) {
  const auto lower = Lower(instance_id);
  if (lower.find(L"vid_1d50&pid_606f") != std::wstring::npos) {
    return lower.find(L"mi_00") != std::wstring::npos;
  }
  return lower.find(L"vid_1209&pid_2323") != std::wstring::npos;
}

std::string DeviceLabel(const std::wstring& instance_id) {
  const auto lower = Lower(instance_id);
  if (lower.find(L"vid_1d50&pid_606f") != std::wstring::npos) {
    return "CANable gs_usb (1D50:606F MI_00)";
  }
  return "candleLight / gs_usb (1209:2323)";
}

bool ParseGuid(const std::wstring& text, GUID* guid) {
  if (!guid) return false;
  unsigned long d1 = 0;
  unsigned int d2 = 0, d3 = 0, d4[8]{};
  const int count = swscanf_s(
      text.c_str(), L"{%8lx-%4x-%4x-%2x%2x-%2x%2x%2x%2x%2x%2x}",
      &d1, &d2, &d3, &d4[0], &d4[1], &d4[2], &d4[3], &d4[4],
      &d4[5], &d4[6], &d4[7]);
  if (count != 11) return false;
  guid->Data1 = static_cast<unsigned long>(d1);
  guid->Data2 = static_cast<unsigned short>(d2);
  guid->Data3 = static_cast<unsigned short>(d3);
  for (int i = 0; i < 8; ++i) guid->Data4[i] = static_cast<unsigned char>(d4[i]);
  return true;
}

void AppendGuidValue(HKEY key, const wchar_t* name,
                     std::vector<std::wstring>* guids) {
  if (key == INVALID_HANDLE_VALUE || !guids) return;
  DWORD type = 0, bytes = 0;
  if (RegQueryValueExW(key, name, nullptr, &type, nullptr, &bytes) != ERROR_SUCCESS)
    return;
  if (bytes < sizeof(wchar_t) || (type != REG_SZ && type != REG_MULTI_SZ)) return;
  std::vector<wchar_t> buffer(bytes / sizeof(wchar_t) + 2, L'\0');
  if (RegQueryValueExW(key, name, nullptr, &type,
                       reinterpret_cast<LPBYTE>(buffer.data()), &bytes) != ERROR_SUCCESS)
    return;
  const wchar_t* p = buffer.data();
  while (*p) {
    std::wstring value(p);
    if (!value.empty() &&
        std::find(guids->begin(), guids->end(), value) == guids->end()) {
      guids->push_back(value);
    }
    p += value.size() + 1;
    if (type == REG_SZ) break;
  }
}

std::vector<std::wstring> ReadInterfaceGuids(HDEVINFO info,
                                             SP_DEVINFO_DATA* dev_info) {
  std::vector<std::wstring> guids;

  HKEY driver = SetupDiOpenDevRegKey(info, dev_info, DICS_FLAG_GLOBAL, 0,
                                     DIREG_DRV, KEY_READ);
  if (driver != INVALID_HANDLE_VALUE) {
    AppendGuidValue(driver, L"DeviceInterfaceGUIDs", &guids);
    AppendGuidValue(driver, L"DeviceInterfaceGUID", &guids);
    RegCloseKey(driver);
  }

  HKEY device = SetupDiOpenDevRegKey(info, dev_info, DICS_FLAG_GLOBAL, 0,
                                     DIREG_DEV, KEY_READ);
  if (device != INVALID_HANDLE_VALUE) {
    AppendGuidValue(device, L"DeviceInterfaceGUIDs", &guids);
    AppendGuidValue(device, L"DeviceInterfaceGUID", &guids);

    HKEY params = nullptr;
    if (RegOpenKeyExW(device, L"Device Parameters", 0, KEY_READ, &params) == ERROR_SUCCESS) {
      AppendGuidValue(params, L"DeviceInterfaceGUIDs", &guids);
      AppendGuidValue(params, L"DeviceInterfaceGUID", &guids);
      RegCloseKey(params);
    }
    RegCloseKey(device);
  }

  return guids;
}

std::wstring ReadDevicePropertyString(HDEVINFO info, SP_DEVINFO_DATA* dev_info,
                                      DWORD property) {
  DWORD type = 0, bytes = 0;
  SetupDiGetDeviceRegistryPropertyW(info, dev_info, property, &type, nullptr, 0,
                                    &bytes);
  if (bytes < sizeof(wchar_t)) return {};
  std::vector<BYTE> buffer(bytes + sizeof(wchar_t), 0);
  if (!SetupDiGetDeviceRegistryPropertyW(info, dev_info, property, &type,
                                         buffer.data(), bytes, nullptr)) return {};
  return reinterpret_cast<const wchar_t*>(buffer.data());
}

std::wstring FindInterfacePath(const GUID& guid,
                               const std::wstring& target_instance_id) {
  HDEVINFO info = SetupDiGetClassDevsW(&guid, nullptr, nullptr,
                                       DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
  if (info == INVALID_HANDLE_VALUE) return {};

  std::wstring found;
  SP_DEVICE_INTERFACE_DATA iface{};
  iface.cbSize = sizeof(iface);
  for (DWORD i = 0; SetupDiEnumDeviceInterfaces(info, nullptr, &guid, i, &iface); ++i) {
    DWORD required = 0;
    SP_DEVINFO_DATA dev{};
    dev.cbSize = sizeof(dev);
    SetupDiGetDeviceInterfaceDetailW(info, &iface, nullptr, 0, &required, &dev);
    if (!required) continue;

    std::vector<BYTE> buffer(required);
    auto* detail = reinterpret_cast<SP_DEVICE_INTERFACE_DETAIL_DATA_W*>(buffer.data());
    detail->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
    if (!SetupDiGetDeviceInterfaceDetailW(info, &iface, detail, required,
                                          nullptr, &dev)) continue;

    DWORD id_chars = 0;
    SetupDiGetDeviceInstanceIdW(info, &dev, nullptr, 0, &id_chars);
    if (!id_chars) continue;
    std::vector<wchar_t> id(id_chars + 1, L'\0');
    if (!SetupDiGetDeviceInstanceIdW(info, &dev, id.data(),
                                     static_cast<DWORD>(id.size()), nullptr)) continue;
    if (Lower(id.data()) == Lower(target_instance_id)) {
      found = detail->DevicePath;
      break;
    }
  }
  SetupDiDestroyDeviceInfoList(info);
  return found;
}

std::vector<DiscoveredDevice> ScanDevices() {
  std::vector<DiscoveredDevice> result;
  HDEVINFO info = SetupDiGetClassDevsW(nullptr, nullptr, nullptr,
                                       DIGCF_PRESENT | DIGCF_ALLCLASSES);
  if (info == INVALID_HANDLE_VALUE) return result;

  SP_DEVINFO_DATA dev{};
  dev.cbSize = sizeof(dev);
  for (DWORD i = 0; SetupDiEnumDeviceInfo(info, i, &dev); ++i) {
    DWORD id_chars = 0;
    SetupDiGetDeviceInstanceIdW(info, &dev, nullptr, 0, &id_chars);
    if (!id_chars) continue;
    std::vector<wchar_t> id(id_chars + 1, L'\0');
    if (!SetupDiGetDeviceInstanceIdW(info, &dev, id.data(),
                                     static_cast<DWORD>(id.size()), nullptr)) continue;
    std::wstring instance_id(id.data());
    if (!IsGsUsbInstance(instance_id)) continue;

    const std::wstring service = ReadDevicePropertyString(info, &dev, SPDRP_SERVICE);
    if (Lower(service) != L"winusb") continue;

    for (const auto& guid_text : ReadInterfaceGuids(info, &dev)) {
      GUID guid{};
      if (!ParseGuid(guid_text, &guid)) continue;
      const auto path = FindInterfacePath(guid, instance_id);
      if (!path.empty()) {
        result.push_back({path, instance_id, service});
        break;
      }
    }
  }
  SetupDiDestroyDeviceInfoList(info);
  return result;
}

void CloseDevice() {
  if (g_usb) {
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
  g_bulk_in = g_bulk_out = 0;
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
    case 33333: return 90;
    case 125000: return 24;
    case 250000: return 12;
    case 500000: return 6;
    case 1000000: return 3;
    default: return 0;
  }
}

bool OpenDevice(const std::wstring& path, int bitrate, std::string* error) {
  CloseDevice();
  const uint32_t brp = BrpForBitrate(bitrate);
  if (!brp) {
    *error = "Unsupported gs_usb bitrate. Use 33.333k, 125k, 250k, 500k, or 1M.";
    return false;
  }

  g_device = CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                         OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (g_device == INVALID_HANDLE_VALUE) {
    std::ostringstream out;
    out << "Could not open gs_usb WinUSB interface. Windows error " << GetLastError();
    *error = out.str();
    return false;
  }
  if (!WinUsb_Initialize(g_device, &g_usb)) {
    std::ostringstream out;
    out << "WinUsb_Initialize failed on the MI_00 WinUSB child. Windows error "
        << GetLastError();
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
    if (!WinUsb_QueryPipe(g_usb, 0, i, &pipe) || pipe.PipeType != UsbdPipeTypeBulk)
      continue;
    if (USB_ENDPOINT_DIRECTION_IN(pipe.PipeId)) g_bulk_in = pipe.PipeId;
    else g_bulk_out = pipe.PipeId;
  }
  if (!g_bulk_in) {
    *error = "gs_usb bulk IN endpoint was not found.";
    CloseDevice();
    return false;
  }

  ULONG timeout = 2;
  WinUsb_SetPipePolicy(g_usb, g_bulk_in, PIPE_TRANSFER_TIMEOUT,
                       sizeof(timeout), &timeout);

  GsHostConfig host{0x0000BEEF};
  if (!ControlOut(kRequestHostFormat, &host, sizeof(host), error)) {
    CloseDevice(); return false;
  }
  GsDeviceMode reset{kModeReset, 0};
  if (!ControlOut(kRequestMode, &reset, sizeof(reset), error)) {
    CloseDevice(); return false;
  }
  // 16 tq/bit with an 87.5% sample point. At the CANable's 48 MHz CAN
  // clock, BRP 90 yields 33,333.33 bit/s for Gen-1 Volt SWCAN.
  GsDeviceBitTiming timing{6, 7, 2, 1, brp};
  if (!ControlOut(kRequestBitTiming, &timing, sizeof(timing), error)) {
    CloseDevice(); return false;
  }
  GsDeviceMode start{kModeStart, 0};
  if (!ControlOut(kRequestMode, &start, sizeof(start), error)) {
    CloseDevice(); return false;
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
    for (const auto& device : ScanDevices()) {
      devices.emplace_back(flutter::EncodableMap{
          {flutter::EncodableValue("path"),
           flutter::EncodableValue(WideToUtf8(device.path))},
          {flutter::EncodableValue("label"),
           flutter::EncodableValue(DeviceLabel(device.instance_id))},
      });
    }
    result->Success(flutter::EncodableValue(devices));
    return;
  }

  if (method_call.method_name() == "connect") {
    const auto* args = std::get_if<flutter::EncodableMap>(method_call.arguments());
    if (!args) {
      result->Error("bad_args", "Missing connect arguments."); return;
    }
    const auto path_it = args->find(flutter::EncodableValue("path"));
    const auto bitrate_it = args->find(flutter::EncodableValue("bitrate"));
    if (path_it == args->end() || bitrate_it == args->end()) {
      result->Error("bad_args", "Connect requires path and bitrate."); return;
    }
    const auto* path = std::get_if<std::string>(&path_it->second);
    const auto* bitrate32 = std::get_if<int32_t>(&bitrate_it->second);
    const auto* bitrate64 = std::get_if<int64_t>(&bitrate_it->second);
    if (!path || (!bitrate32 && !bitrate64)) {
      result->Error("bad_args", "Invalid path or bitrate."); return;
    }
    const int bitrate = bitrate32 ? *bitrate32 : static_cast<int>(*bitrate64);
    std::string error;
    if (!OpenDevice(Utf8ToWide(*path), bitrate, &error)) {
      result->Error("gs_usb_connect", error); return;
    }
    result->Success();
    return;
  }

  if (method_call.method_name() == "readFrame") {
    if (!g_usb || !g_bulk_in) { result->Success(); return; }
    std::vector<uint8_t> buffer(64);
    ULONG transferred = 0;
    if (!WinUsb_ReadPipe(g_usb, g_bulk_in, buffer.data(),
                         static_cast<ULONG>(buffer.size()), &transferred, nullptr)) {
      const DWORD error = GetLastError();
      if (error == ERROR_SEM_TIMEOUT || error == ERROR_TIMEOUT) {
        result->Success(); return;
      }
      std::ostringstream out;
      out << "WinUSB bulk read failed, Windows error " << error;
      result->Error("gs_usb_read", out.str()); return;
    }
    if (transferred < 20) { result->Success(); return; }
    buffer.resize(transferred);
    result->Success(flutter::EncodableValue(buffer));
    return;
  }

  if (method_call.method_name() == "disconnect") {
    CloseDevice(); result->Success(); return;
  }

  result->NotImplemented();
}