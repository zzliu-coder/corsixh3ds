# Single registration point for native platform files.
# Paths are relative to this file; keep entries explicit and one per line.
set(CTH3DS_PLATFORM_SOURCES
  runtime_3ds.cpp
  runner/adapter.cpp
  runner/core.cpp
  runner/rosalina.cpp
  runtime/game_view.cpp
  runtime/observation.cpp
  runtime/gpu_renderer.cpp
)
set(CTH3DS_PLATFORM_HEADERS
  runtime_3ds.hpp
  runner/adapter.hpp
  runner/core.hpp
  runner/rosalina.hpp
  runtime/game_view.hpp
  runtime/observation.hpp
  embedded_platform_lua.hpp
)
