#include "atlas_canalystii_plugin.h"

#include <flutter/plugin_registrar_windows.h>

void AtlasCanalystiiPluginRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar) {
  AtlasCanalystiiPlugin::RegisterWithRegistrar(
      flutter::PluginRegistrarManager::GetInstance()
          ->GetRegistrar<flutter::PluginRegistrarWindows>(registrar));
}
