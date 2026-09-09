cmake_minimum_required(VERSION 3.16)
project(corsixth_3ds_port VERSION 0.6.1 LANGUAGES CXX)

option(CTH3DS_BUILD_TESTS "Build host unit and integration tests" ON)
option(CTH3DS_BUILD_SIMULATOR "Build the host dual-screen simulator" ON)
option(CTH3DS_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(CTH3DS_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" ON)

option(CTH3DS_BUILD_3DS_SYNTAX_CHECK "Compile 3DS platform sources against API-shaped host stubs" ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Python3 COMPONENTS Interpreter REQUIRED)

set(CTH3DS_BUILD_PROFILE "loose" CACHE STRING "Native resource implementation: loose or resource-experiment")
set_property(CACHE CTH3DS_BUILD_PROFILE PROPERTY STRINGS loose resource-experiment)
if(NOT CTH3DS_BUILD_PROFILE STREQUAL "loose" AND NOT CTH3DS_BUILD_PROFILE STREQUAL "resource-experiment")
  message(FATAL_ERROR "Unsupported CTH3DS_BUILD_PROFILE: ${CTH3DS_BUILD_PROFILE}")
endif()
set(CTH3DS_RESOURCE_EXPERIMENT 0)
if(CTH3DS_BUILD_PROFILE STREQUAL "resource-experiment")
  set(CTH3DS_RESOURCE_EXPERIMENT 1)
endif()
include(src/common/sources.cmake)
set(CTH3DS_CLASSIFIED_COMMON ${CTH3DS_PLAYER_SOURCES} ${CTH3DS_RESOURCE_EXPERIMENT_SOURCES} ${CTH3DS_RESOURCE_TOOL_SOURCES})
file(GLOB CTH3DS_ACTUAL_COMMON RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}/src/common" "src/common/*.cpp")
list(SORT CTH3DS_CLASSIFIED_COMMON)
list(SORT CTH3DS_ACTUAL_COMMON)
if(NOT CTH3DS_CLASSIFIED_COMMON STREQUAL CTH3DS_ACTUAL_COMMON)
  message(FATAL_ERROR "Common sources must have exactly one explicit owner in src/common/sources.cmake")
endif()
foreach(group PLAYER RESOURCE_EXPERIMENT RESOURCE_TOOL)
  list(TRANSFORM CTH3DS_${group}_SOURCES PREPEND "src/common/")
endforeach()
add_library(cth3ds_common STATIC ${CTH3DS_PLAYER_SOURCES})
add_library(cth3ds_resource_experiment STATIC ${CTH3DS_RESOURCE_EXPERIMENT_SOURCES})
target_link_libraries(cth3ds_resource_experiment PUBLIC cth3ds_common)
add_library(cth3ds_resource_tools STATIC ${CTH3DS_RESOURCE_TOOL_SOURCES})
target_link_libraries(cth3ds_resource_tools PUBLIC cth3ds_common)

target_include_directories(cth3ds_common PUBLIC include)

foreach(common_target cth3ds_common cth3ds_resource_experiment cth3ds_resource_tools)
target_compile_options(${common_target} PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wsign-conversion;-Wshadow>
)
if(CTH3DS_WARNINGS_AS_ERRORS)
  target_compile_options(${common_target} PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Werror>
  )
endif()

if(CTH3DS_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
  target_compile_options(${common_target} PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(${common_target} PUBLIC -fsanitize=address,undefined)
endif()
endforeach()

if(CTH3DS_BUILD_3DS_SYNTAX_CHECK)
  include(src/3ds/sources.cmake)
  set(CTH3DS_NATIVE_SOURCE_PATHS ${CTH3DS_PLATFORM_SOURCES})
  list(TRANSFORM CTH3DS_NATIVE_SOURCE_PATHS PREPEND "${CMAKE_CURRENT_SOURCE_DIR}/src/3ds/")
  add_library(cth3ds-3ds-syntax OBJECT ${CTH3DS_NATIVE_SOURCE_PATHS})
  target_include_directories(cth3ds-3ds-syntax PRIVATE
    tests/stubs
    include
    src/3ds
  )
  target_compile_definitions(cth3ds-3ds-syntax PRIVATE __3DS__=1 CTH3DS_STUB_BUILD=1 CTH3DS_RESOURCE_EXPERIMENT=${CTH3DS_RESOURCE_EXPERIMENT})
  target_compile_options(cth3ds-3ds-syntax PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wsign-conversion;-Wshadow>
  )
  if(CTH3DS_WARNINGS_AS_ERRORS)
    target_compile_options(cth3ds-3ds-syntax PRIVATE
      $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Werror>
    )
  endif()
endif()

if(CTH3DS_BUILD_SIMULATOR)
  add_executable(cth3ds-simulator src/host/simulator_main.cpp)
  target_link_libraries(cth3ds-simulator PRIVATE cth3ds_common)
  target_compile_options(cth3ds-simulator PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic>
  )
endif()

add_executable(cth3ds-runtime-probe src/host/runtime_probe_main.cpp)
target_link_libraries(cth3ds-runtime-probe PRIVATE cth3ds_resource_experiment)
target_compile_options(cth3ds-runtime-probe PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wsign-conversion;-Wshadow>
)
if(CTH3DS_WARNINGS_AS_ERRORS)
  target_compile_options(cth3ds-runtime-probe PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Werror>
  )
endif()

if(CTH3DS_BUILD_TESTS)
  enable_testing()
  add_executable(cth3ds-tests
    tests/test_main.cpp
    tests/test_action_codec.cpp
    tests/test_allocator_ledger.cpp
    tests/test_audio_mixer.cpp
    tests/test_atomic_save.cpp
    tests/test_bottom_ui.cpp
    tests/test_bounded_log.cpp
    tests/test_build_gesture.cpp
    tests/test_fixed_step.cpp
    tests/test_panel_refresh.cpp
    tests/test_framebuffer_scaler.cpp
    tests/test_handheld_r48.cpp
    tests/test_interval_gate.cpp
    tests/test_input_mapper.cpp
    tests/test_lifecycle.cpp
    tests/test_memory_telemetry.cpp
    tests/test_resource_pack.cpp
    tests/test_resource_manager.cpp
    tests/test_runtime_session.cpp
    tests/test_screen_layout.cpp
    tests/test_telemetry.cpp
    tests/test_texture_cache.cpp
    tests/test_th3ds_runtime.cpp
  )
  target_link_libraries(cth3ds-tests PRIVATE cth3ds_resource_experiment cth3ds_resource_tools)
  target_include_directories(cth3ds-tests PRIVATE tests)
  target_compile_options(cth3ds-tests PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wsign-conversion;-Wshadow>
  )
  if(CTH3DS_WARNINGS_AS_ERRORS)
    target_compile_options(cth3ds-tests PRIVATE
      $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Werror>
    )
  endif()
  add_test(NAME cth3ds-tests COMMAND cth3ds-tests)
  # Each Python fixture owns its profile; host target identity remains explicit above.
  set(CTH3DS_PYTHON_TEST_ENV
    CTH3DS_BUILD_PROFILE=loose
    PYTHONPATH=${CMAKE_SOURCE_DIR}/tools
    PYTHONDONTWRITEBYTECODE=1
    CTH3DS_RUNTIME_PROBE=$<TARGET_FILE:cth3ds-runtime-probe>)
  if(CTH3DS_BUILD_SIMULATOR)
    list(APPEND CTH3DS_PYTHON_TEST_ENV
      CTH3DS_SIMULATOR=$<TARGET_FILE:cth3ds-simulator>)
  endif()
  add_test(NAME python-integration-tests
    COMMAND ${CMAKE_COMMAND} -E env
      ${CTH3DS_PYTHON_TEST_ENV}
      ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/scripts/run_host_python_suite.py
        --repo ${CMAKE_SOURCE_DIR}
        --manifest ${CMAKE_SOURCE_DIR}/tests/host-python-suite.json
        --output ${CMAKE_BINARY_DIR}/host-python-suite-result.json)
  if(CTH3DS_BUILD_SIMULATOR)
    add_test(NAME simulator-smoke
      COMMAND cth3ds-simulator ${CMAKE_BINARY_DIR}/simulator-smoke)
  endif()
endif()
