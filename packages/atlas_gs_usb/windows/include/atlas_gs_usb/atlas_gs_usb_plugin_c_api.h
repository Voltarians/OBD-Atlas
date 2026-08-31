#ifndef FLUTTER_PLUGIN_ATLAS_GS_USB_PLUGIN_C_API_H_
#define FLUTTER_PLUGIN_ATLAS_GS_USB_PLUGIN_C_API_H_

#include <flutter_plugin_registrar.h>

#ifdef ATLAS_GS_USB_PLUGIN_IMPL
#define ATLAS_GS_USB_PLUGIN_EXPORT __declspec(dllexport)
#else
#define ATLAS_GS_USB_PLUGIN_EXPORT __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

ATLAS_GS_USB_PLUGIN_EXPORT void AtlasGsUsbPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // FLUTTER_PLUGIN_ATLAS_GS_USB_PLUGIN_C_API_H_
