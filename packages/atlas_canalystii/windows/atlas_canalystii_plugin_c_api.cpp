#include "include/atlas_canalystii/atlas_canalystii_plugin_c_api.h"

#include <flutter/plugin_registrar_windows.h>

#include "atlas_canalystii_plugin.h"

void AtlasCanalystiiPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar) {
  AtlasCanalystiiPlugin::RegisterWithRegistrar(
      flutter::PluginRegistrarManager::GetInstance()
          ->GetRegistrar<flutter::PluginRegistrarWindows>(registrar));
}
