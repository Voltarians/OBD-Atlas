//
//  Generated file. Do not edit.
//

// clang-format off

#include "generated_plugin_registrant.h"

#include <atlas_canalystii/atlas_canalystii_plugin_c_api.h>
#include <atlas_gs_usb/atlas_gs_usb_plugin_c_api.h>
#include <atlas_lys_usbcan/atlas_lys_usbcan_plugin_c_api.h>

void RegisterPlugins(flutter::PluginRegistry* registry) {
  AtlasCanalystiiPluginCApiRegisterWithRegistrar(
      registry->GetRegistrarForPlugin("AtlasCanalystiiPluginCApi"));
  AtlasGsUsbPluginCApiRegisterWithRegistrar(
      registry->GetRegistrarForPlugin("AtlasGsUsbPluginCApi"));
  AtlasLysUsbcanPluginCApiRegisterWithRegistrar(
      registry->GetRegistrarForPlugin("AtlasLysUsbcanPluginCApi"));
}
