#ifndef FLUTTER_PLUGIN_ATLAS_GS_USB_PLUGIN_H_
#define FLUTTER_PLUGIN_ATLAS_GS_USB_PLUGIN_H_

#include <flutter/method_channel.h>
#include <flutter/plugin_registrar_windows.h>

#include <memory>
#include <windows.h>

class AtlasGsUsbPlugin : public flutter::Plugin {
 public:
  static void RegisterWithRegistrar(flutter::PluginRegistrarWindows* registrar);

  AtlasGsUsbPlugin();
  virtual ~AtlasGsUsbPlugin();

  AtlasGsUsbPlugin(const AtlasGsUsbPlugin&) = delete;
  AtlasGsUsbPlugin& operator=(const AtlasGsUsbPlugin&) = delete;

 private:
  void HandleMethodCall(
      const flutter::MethodCall<flutter::EncodableValue>& method_call,
      std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result);
};

// WinUsb_Initialize requires the device handle to be opened for overlapped I/O.
// Keep the transport source focused on gs_usb protocol handling while ensuring
// every WinUSB CreateFileW call gets the required FILE_FLAG_OVERLAPPED flag.
inline HANDLE AtlasGsUsbCreateFileW(
    LPCWSTR file_name,
    DWORD desired_access,
    DWORD share_mode,
    LPSECURITY_ATTRIBUTES security_attributes,
    DWORD creation_disposition,
    DWORD flags_and_attributes,
    HANDLE template_file) {
  return ::CreateFileW(file_name, desired_access, share_mode, security_attributes,
                       creation_disposition,
                       flags_and_attributes | FILE_FLAG_OVERLAPPED,
                       template_file);
}

#define CreateFileW AtlasGsUsbCreateFileW

#endif  // FLUTTER_PLUGIN_ATLAS_GS_USB_PLUGIN_H_
