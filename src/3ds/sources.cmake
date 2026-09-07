# Single registration point for native platform files.
# Paths are relative to this file; keep entries explicit and one per line.
set(CTH3DS_PLATFORM_SOURCES
  runtime_3ds.cpp
  runtime/game_view.cpp
  runtime/gpu_renderer.cpp
)
set(CTH3DS_PLATFORM_HEADERS
  runtime_3ds.hpp
  runtime/game_view.hpp
  embedded_platform_lua.hpp
)
