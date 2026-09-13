#include "include/atlas_gs_usb/atlas_gs_usb_plugin_c_api.h"

#include <flutter/plugin_registrar_windows.h>

#include "atlas_gs_usb_plugin.h"

void AtlasGsUsbPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar) {
  AtlasGsUsbPlugin::RegisterWithRegistrar(
      flutter::PluginRegistrarManager::GetInstance()
          ->GetRegistrar<flutter::PluginRegistrarWindows>(registrar));
}
