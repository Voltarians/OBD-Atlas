cmake_minimum_required(VERSION 3.14)
set(PROJECT_NAME "atlas_lys_usbcan")
project(${PROJECT_NAME} LANGUAGES CXX)

set(PLUGIN_NAME "atlas_lys_usbcan_plugin")

add_library(${PLUGIN_NAME} SHARED
  "atlas_lys_usbcan_plugin.cpp"
  "atlas_lys_usbcan_plugin_c_api.cpp"
)
apply_standard_settings(${PLUGIN_NAME})
set_target_properties(${PLUGIN_NAME} PROPERTIES CXX_VISIBILITY_PRESET hidden)
target_compile_definitions(${PLUGIN_NAME} PRIVATE FLUTTER_PLUGIN_IMPL ATLAS_LYS_USBCAN_PLUGIN_IMPL)
target_include_directories(${PLUGIN_NAME} INTERFACE
  "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(${PLUGIN_NAME} PRIVATE flutter flutter_wrapper_plugin)

set(atlas_lys_usbcan_bundled_libraries "" PARENT_SCOPE)
