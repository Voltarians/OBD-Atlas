#ifndef FLUTTER_PLUGIN_ATLAS_CANALYSTII_PLUGIN_C_API_H_
#define FLUTTER_PLUGIN_ATLAS_CANALYSTII_PLUGIN_C_API_H_

#include <flutter_plugin_registrar.h>

#ifdef ATLAS_CANALYSTII_PLUGIN_IMPL
#define ATLAS_CANALYSTII_PLUGIN_EXPORT __declspec(dllexport)
#else
#define ATLAS_CANALYSTII_PLUGIN_EXPORT __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

ATLAS_CANALYSTII_PLUGIN_EXPORT void AtlasCanalystiiPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // FLUTTER_PLUGIN_ATLAS_CANALYSTII_PLUGIN_C_API_H_
