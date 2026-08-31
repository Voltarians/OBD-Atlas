cmake_minimum_required(VERSION 3.14)
set(PROJECT_NAME "atlas_canalystii")
project(${PROJECT_NAME} LANGUAGES CXX)

set(PLUGIN_NAME "atlas_canalystii_plugin")

add_library(${PLUGIN_NAME} SHARED
  "atlas_canalystii_plugin.cpp"
  "atlas_canalystii_plugin_c_api.cpp"
)
apply_standard_settings(${PLUGIN_NAME})
set_target_properties(${PLUGIN_NAME} PROPERTIES CXX_VISIBILITY_PRESET hidden)
target_compile_definitions(${PLUGIN_NAME} PRIVATE FLUTTER_PLUGIN_IMPL)
target_link_libraries(${PLUGIN_NAME} PRIVATE flutter flutter_wrapper_plugin setupapi winusb)

set(atlas_canalystii_bundled_libraries "" PARENT_SCOPE)
