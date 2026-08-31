#ifndef FLUTTER_PLUGIN_ATLAS_LYS_USBCAN_PLUGIN_C_API_H_
#define FLUTTER_PLUGIN_ATLAS_LYS_USBCAN_PLUGIN_C_API_H_

#include <flutter_plugin_registrar.h>

#ifdef ATLAS_LYS_USBCAN_PLUGIN_IMPL
#define ATLAS_LYS_USBCAN_PLUGIN_EXPORT __declspec(dllexport)
#else
#define ATLAS_LYS_USBCAN_PLUGIN_EXPORT __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

ATLAS_LYS_USBCAN_PLUGIN_EXPORT void AtlasLysUsbcanPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // FLUTTER_PLUGIN_ATLAS_LYS_USBCAN_PLUGIN_C_API_H_
