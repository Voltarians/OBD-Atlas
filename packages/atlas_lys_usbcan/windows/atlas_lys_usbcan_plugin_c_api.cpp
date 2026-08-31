#include "include/atlas_lys_usbcan/atlas_lys_usbcan_plugin_c_api.h"

#include <flutter/plugin_registrar_windows.h>

#include "atlas_lys_usbcan_plugin.h"

void AtlasLysUsbcanPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar) {
  AtlasLysUsbcanPlugin::RegisterWithRegistrar(
      flutter::PluginRegistrarManager::GetInstance()
          ->GetRegistrar<flutter::PluginRegistrarWindows>(registrar));
}
