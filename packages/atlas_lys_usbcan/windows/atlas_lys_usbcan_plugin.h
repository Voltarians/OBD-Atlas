#ifndef FLUTTER_PLUGIN_ATLAS_LYS_USBCAN_PLUGIN_H_
#define FLUTTER_PLUGIN_ATLAS_LYS_USBCAN_PLUGIN_H_

#include <flutter/method_channel.h>
#include <flutter/plugin_registrar_windows.h>

#include <memory>

class AtlasLysUsbcanPlugin : public flutter::Plugin {
 public:
  static void RegisterWithRegistrar(flutter::PluginRegistrarWindows* registrar);

  AtlasLysUsbcanPlugin();
  virtual ~AtlasLysUsbcanPlugin();

  AtlasLysUsbcanPlugin(const AtlasLysUsbcanPlugin&) = delete;
  AtlasLysUsbcanPlugin& operator=(const AtlasLysUsbcanPlugin&) = delete;

 private:
  void HandleMethodCall(
      const flutter::MethodCall<flutter::EncodableValue>& method_call,
      std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result);
};

#endif  // FLUTTER_PLUGIN_ATLAS_LYS_USBCAN_PLUGIN_H_
