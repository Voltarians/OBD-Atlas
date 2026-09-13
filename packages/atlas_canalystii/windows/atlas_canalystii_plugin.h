#ifndef FLUTTER_PLUGIN_ATLAS_CANALYSTII_PLUGIN_H_
#define FLUTTER_PLUGIN_ATLAS_CANALYSTII_PLUGIN_H_

#include <flutter/method_channel.h>
#include <flutter/plugin_registrar_windows.h>

#include <memory>

class AtlasCanalystiiPlugin : public flutter::Plugin {
 public:
  static void RegisterWithRegistrar(flutter::PluginRegistrarWindows* registrar);

  AtlasCanalystiiPlugin();
  virtual ~AtlasCanalystiiPlugin();

  AtlasCanalystiiPlugin(const AtlasCanalystiiPlugin&) = delete;
  AtlasCanalystiiPlugin& operator=(const AtlasCanalystiiPlugin&) = delete;

 private:
  void HandleMethodCall(
      const flutter::MethodCall<flutter::EncodableValue>& method_call,
      std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result);
};

#endif
