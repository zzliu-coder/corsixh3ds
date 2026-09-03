cmake_minimum_required(VERSION 3.16)
project(cth3ds_runtime_core_v2_red_contract LANGUAGES CXX)

set(CTH3DS_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(CTH3DS_BUILD_SIMULATOR OFF CACHE BOOL "" FORCE)
set(CTH3DS_BUILD_3DS_SYNTAX_CHECK OFF CACHE BOOL "" FORCE)
set(CTH3DS_WARNINGS_AS_ERRORS ON CACHE BOOL "" FORCE)

add_subdirectory("${CMAKE_CURRENT_LIST_DIR}/../.."
                 "${CMAKE_CURRENT_BINARY_DIR}/product" EXCLUDE_FROM_ALL)

function(add_runtime_core_v2_observer target source)
  add_executable(${target} "${source}")
  target_link_libraries(${target} PRIVATE cth3ds_common)
  target_compile_features(${target} PRIVATE cxx_std_17)
  target_compile_options(${target} PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wsign-conversion;-Wshadow;-Werror>
  )
endfunction()

add_runtime_core_v2_observer(
  cth3ds-red-h1-level-requires-package
  cpp/test_h1_level_requires_package.cpp)
add_runtime_core_v2_observer(
  cth3ds-red-h2-transition-lease-escape
  cpp/test_h2_transition_lease_escape.cpp)
