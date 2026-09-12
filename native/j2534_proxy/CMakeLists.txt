cmake_minimum_required(VERSION 3.20)
project(obd_atlas_j2534_proxy LANGUAGES CXX)

if(NOT WIN32)
  message(FATAL_ERROR "The J2534 proxy is Windows-only.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(obd_atlas_j2534_proxy SHARED
  j2534_proxy.cpp
  j2534_proxy.def
)
target_include_directories(obd_atlas_j2534_proxy PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(obd_atlas_j2534_proxy PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
if(MSVC)
  target_compile_options(obd_atlas_j2534_proxy PRIVATE /W4 /permissive-)
endif()

include(CTest)
if(BUILD_TESTING)
  add_library(fake_j2534_provider SHARED
    tests/fake_j2534_provider.cpp
    tests/fake_j2534_provider.def
  )
  target_include_directories(fake_j2534_provider PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
  target_compile_definitions(fake_j2534_provider PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)

  add_executable(j2534_proxy_lifecycle_test
    tests/proxy_lifecycle_test.cpp
  )
  target_include_directories(j2534_proxy_lifecycle_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
  target_compile_definitions(j2534_proxy_lifecycle_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)

  add_executable(j2534_proxy_invalid_config_test
    tests/proxy_invalid_config_test.cpp
  )
  target_include_directories(j2534_proxy_invalid_config_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
  target_compile_definitions(j2534_proxy_invalid_config_test PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)

  add_test(
    NAME j2534_proxy_lifecycle_transparency
    COMMAND j2534_proxy_lifecycle_test
      $<TARGET_FILE:obd_atlas_j2534_proxy>
      $<TARGET_FILE:fake_j2534_provider>
  )
  add_test(
    NAME j2534_proxy_invalid_provider_identity
    COMMAND j2534_proxy_invalid_config_test
      $<TARGET_FILE:obd_atlas_j2534_proxy>
      $<TARGET_FILE:fake_j2534_provider>
  )
endif()
