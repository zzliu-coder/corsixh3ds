#pragma once

#include <cstdint>
#include <cstddef>
#include <memory>
#include "cth3ds/telemetry.hpp"
#include "cth3ds/memory_telemetry.hpp"

struct lua_State;
struct SDL_Window;
union SDL_Event;

namespace cth3ds {

class ResourceTelemetrySink;
class ResourceBudgetGate;

void register_lua_module(lua_State* state);
[[nodiscard]] bool runtime_initialize(lua_State* state, const char* mode = "loose");
[[nodiscard]] bool runtime_assert_ready(lua_State* state);
[[nodiscard]] bool runtime_audio_reserve(std::size_t bytes, const char* identity) noexcept;
void runtime_tick(lua_State* state);

//! Tell the platform layer which window CorsixTH renders into. SDL2 cannot
//! enumerate windows, and the lower screen has to read that window's surface.
void runtime_set_game_window(SDL_Window* window) noexcept;

//! Called immediately after CorsixTH presents a frame, so the lower screen can
//! mirror it at half size while the pixels are still current.
void runtime_after_frame(bool draw_success = true) noexcept;

// U3: normal-thread observations; success means checked software submission.
std::uint64_t runtime_span_begin(TimingStage stage) noexcept;
bool runtime_span_end(std::uint64_t token, bool success = true) noexcept;
class RuntimeTimingScope {
 public:
  explicit RuntimeTimingScope(TimingStage stage) noexcept : token_(runtime_span_begin(stage)) {}
  ~RuntimeTimingScope() { if (token_) runtime_span_end(token_, success_); }
  RuntimeTimingScope(const RuntimeTimingScope&) = delete;
  RuntimeTimingScope& operator=(const RuntimeTimingScope&) = delete;
  void result(bool success) noexcept { success_ = success; }
  void finish(bool success = true) noexcept { if (token_) runtime_span_end(token_, success); token_ = 0; }
 private:
  std::uint64_t token_; bool success_{true};
};
void runtime_begin_frame() noexcept;
void runtime_top_present_complete(bool success) noexcept;
void runtime_frame_skipped() noexcept;
void runtime_flush_observations(bool force = false) noexcept;
void runtime_observe_memory(const char* checkpoint, const char* phase,
    const char* resource, MemoryGate gate, std::uint64_t requested = 0,
    bool requested_known = false, std::uint64_t held = 0,
    bool held_known = false, bool failed = false,
    bool opaque_temporary_unknown = true) noexcept;

void runtime_shutdown(lua_State* state) noexcept;
[[nodiscard]] bool runtime_consume_sdl_event(const SDL_Event& event) noexcept;
int luaopen_th3ds(lua_State* state);

//! Record a fatal condition on the lower screen and in the SD-card boot log,
//! then hold the screen long enough to be read. Used for conditions that would
//! otherwise reach std::terminate, which on a 3DS looks exactly like a hang.
void report_fatal(const char* reason) noexcept;

//! Low-overhead legacy-load diagnostics for allocation sites outside the Lua
//! bridge. These categories explain the current loose-file loader; they are
//! distinct from the canonical TH3DS resource-pool accounting contract.
void report_resource_memory(const char* category, std::uint64_t bytes,
                            const char* identity = nullptr) noexcept;
void report_memory_checkpoint(const char* checkpoint, const char* phase,
                              const char* identity = nullptr,
                              std::uint64_t bytes = 0U,
                              std::uint64_t requested_bytes = 0U) noexcept;
void report_allocation_failure(const char* category, const char* identity,
                               std::uint64_t requested_bytes,
                               const char* allocator = "app",
                               const char* detail = nullptr) noexcept;

//! Canonical TH3DS pool telemetry and heap gates consumed by ResourceManager.
//! The loose-file diagnostic counters above remain separate.
[[nodiscard]] std::shared_ptr<ResourceTelemetrySink>
make_runtime_resource_telemetry_sink();
[[nodiscard]] std::shared_ptr<ResourceBudgetGate>
make_runtime_resource_budget_gate();

}  // namespace cth3ds
