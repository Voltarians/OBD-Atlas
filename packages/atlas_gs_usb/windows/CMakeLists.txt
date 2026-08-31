cmake_minimum_required(VERSION 3.14)
set(PROJECT_NAME "atlas_gs_usb")
project(${PROJECT_NAME} LANGUAGES CXX)

set(PLUGIN_NAME "atlas_gs_usb_plugin")

add_library(${PLUGIN_NAME} SHARED
  "atlas_gs_usb_plugin.cpp"
  "atlas_gs_usb_plugin_c_api.cpp"
)
apply_standard_settings(${PLUGIN_NAME})
set_target_properties(${PLUGIN_NAME} PROPERTIES CXX_VISIBILITY_PRESET hidden)
target_compile_definitions(${PLUGIN_NAME} PRIVATE FLUTTER_PLUGIN_IMPL ATLAS_GS_USB_PLUGIN_IMPL)
target_include_directories(${PLUGIN_NAME} INTERFACE
  "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(${PLUGIN_NAME} PRIVATE flutter flutter_wrapper_plugin setupapi winusb uuid advapi32)

set(atlas_gs_usb_bundled_libraries
  ""
  PARENT_SCOPE
)
