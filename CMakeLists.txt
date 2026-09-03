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

add_library(cth3ds_common STATIC
  src/common/action_codec.cpp
  src/common/allocation_ledger.cpp
  src/common/audio_mixer.cpp
  src/common/atomic_save.cpp
  src/common/bottom_ui.cpp
  src/common/build_gesture.cpp
  src/common/crc32.cpp
  src/common/fixed_step.cpp
  src/common/framebuffer_scaler.cpp
  src/common/interval_gate.cpp
  src/common/input_mapper.cpp
  src/common/lifecycle.cpp
  src/common/resource_pack.cpp
  src/common/resource_manager.cpp
  src/common/runtime_session.cpp
  src/common/screen_layout.cpp
  src/common/sha256.cpp
  src/common/software_canvas.cpp
  src/common/telemetry.cpp
  src/common/th3ds.cpp
  src/common/texture_cache.cpp
)

target_include_directories(cth3ds_common PUBLIC include)

target_compile_options(cth3ds_common PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wsign-conversion;-Wshadow>
)
if(CTH3DS_WARNINGS_AS_ERRORS)
  target_compile_options(cth3ds_common PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Werror>
  )
endif()

if(CTH3DS_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
  target_compile_options(cth3ds_common PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(cth3ds_common PUBLIC -fsanitize=address,undefined)
endif()


if(CTH3DS_BUILD_3DS_SYNTAX_CHECK)
  add_library(cth3ds-3ds-syntax OBJECT src/3ds/runtime_3ds.cpp)
  target_include_directories(cth3ds-3ds-syntax PRIVATE
    tests/stubs
    include
    src/3ds
  )
  target_compile_definitions(cth3ds-3ds-syntax PRIVATE __3DS__=1 CTH3DS_STUB_BUILD=1)
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
target_link_libraries(cth3ds-runtime-probe PRIVATE cth3ds_common)
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
    tests/test_build_gesture.cpp
    tests/test_fixed_step.cpp
    tests/test_framebuffer_scaler.cpp
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
  target_link_libraries(cth3ds-tests PRIVATE cth3ds_common)
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
  set(CTH3DS_PYTHON_TEST_ENV
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
      ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_SOURCE_DIR}/tests -p "test_*.py" -v)
  if(CTH3DS_BUILD_SIMULATOR)
    add_test(NAME simulator-smoke
      COMMAND cth3ds-simulator ${CMAKE_BINARY_DIR}/simulator-smoke)
  endif()
endif()
