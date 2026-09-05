#include "runtime_3ds.hpp"

#include <3ds.h>
#include <SDL.h>
#include <SDL_mixer.h>

#include <atomic>
#include <algorithm>
#include <array>
#include <cstdarg>
#include <cstddef>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <limits>
#include <malloc.h>
#include <memory>
#include <new>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "lua.hpp"

#include "cth3ds/action_codec.hpp"
#include "cth3ds/atomic_save.hpp"
#include "cth3ds/bottom_ui.hpp"
#include "cth3ds/crc32.hpp"
#include "cth3ds/events.hpp"
#include "cth3ds/fixed_step.hpp"
#include "cth3ds/framebuffer_scaler.hpp"
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/interval_gate.hpp"
#include "cth3ds/lifecycle.hpp"
#include "cth3ds/memory_telemetry.hpp"
#include "cth3ds/resource_manager.hpp"
#include "cth3ds/runtime_session.hpp"
#include "cth3ds/screen_layout.hpp"
#include "cth3ds/software_canvas.hpp"
#include "cth3ds/telemetry.hpp"
#include "embedded_platform_lua.hpp"

extern "C" int luaopen_lfs(lua_State* state);
extern "C" int luaopen_lpeg(lua_State* state);

// libctru's default allocator reserves as much as 32 MiB for linear memory on
// an Old 3DS. CorsixTH's startup pressure is ordinary malloc/new memory (Lua,
// decoded resource tables and SDL software surfaces), while this port does not
// allocate large linear GPU buffers. A strong definition overrides libctru's
// weak default and leaves the rest of the process allocation to the app heap.
extern "C" {
u32 __ctru_linear_heap_size = 8U * 1024U * 1024U;
}

namespace cth3ds {

int luaopen_th3ds(lua_State* state);

namespace {

constexpr std::uint32_t kLifecycleSuspend = 1U << 0U;
constexpr std::uint32_t kLifecycleRestore = 1U << 1U;
constexpr std::uint32_t kLifecycleSleep = 1U << 2U;
constexpr std::uint32_t kLifecycleWake = 1U << 3U;
constexpr std::uint32_t kLifecycleExit = 1U << 4U;

// Talking to Lua is not free: syncBottomState walks the hospital tables. Half a
// second is well inside human reaction time for a status readout and costs a
// quarter of what the previous 250 ms gate did.
constexpr std::uint64_t kStateRefreshUs = 500000U;
constexpr std::uint64_t kSystemRefreshUs = 2000000U;
constexpr std::uint64_t kBatteryRefreshUs = 10000000U;
constexpr std::uint64_t kTelemetryLogUs = 60000000U;

constexpr const char* kOverlayVersion = "0.6.1";
constexpr const char* kLogPath = "sdmc:/3ds/corsixth/boot.log";
constexpr const char* kResourceBundlePath =
    "sdmc:/3ds/corsixth/resources/bundle.th3ds.json";
constexpr const char* kAdapterModule = "3ds.platform";

std::uint32_t resource_group_id(std::string_view identity) noexcept {
  std::uint32_t hash = 2166136261U;
  for (const char character : identity) {
    const auto byte = static_cast<unsigned char>(character);
    hash ^= byte;
    hash *= 16777619U;
  }
  // Group 0 is ungrouped and group 1 is the menu contract.
  return 2U + (hash % 0x7FFFFFFDU);
}

// Dropping this file on the SD card switches the lower screen back to the
// standalone management panel. Game mirroring is the default; the file exists
// so a device can fall back without a rebuild.
constexpr const char* kPanelModeMarker = "sdmc:/3ds/corsixth/bottom-screen-panel.txt";

// How long the build stamp stays on top of the mirrored game view after boot.

enum class BottomScreenMode { Game, Panel };

// Height of the status strip drawn over the mirrored game view.
constexpr int kOverlayHeight = 13;

// ---------------------------------------------------------------------------
// Boot log
//
// stderr on a 3DS goes nowhere, so a hang during Lua initialisation used to be
// completely opaque: the only signal was whatever the lower screen happened to
// show. Everything below writes to the SD card instead, unbuffered, so the
// last line on disk is the last thing that actually executed.
// ---------------------------------------------------------------------------
std::FILE* g_log = nullptr;
bool g_log_attempted = false;
u64 g_boot_started_ms = 0U;
bool g_heap_watermarks_initialized = false;
std::uint64_t g_min_heap_available = 0U;
std::uint64_t g_min_linear_free = std::numeric_limits<std::uint64_t>::max();
std::uint64_t g_lua_bytes = 0U;
std::uint64_t g_lua_peak_bytes = 0U;
std::array<std::uint64_t,
           static_cast<std::size_t>(ResourceMemoryCategory::Count)>
    g_resource_bytes{};
std::uint32_t g_resource_categories_supplied = 0U;
std::array<std::uint64_t, static_cast<std::size_t>(ResourcePool::Count)>
    g_resource_pool_bytes{};
std::uint64_t g_resource_cache_entries = 0U;
std::uint64_t g_resource_cache_leases = 0U;
std::uint64_t g_resource_cache_evictions = 0U;
std::uint64_t g_resource_cache_rejects = 0U;
char g_current_stage[16] = "PREBOOT";
char g_current_stage_label[96] = "PROCESS START";

struct HeapSnapshot {
  std::uint64_t heap_total{0U};
  std::uint64_t arena{0U};
  std::uint64_t uordblks{0U};
  std::uint64_t fordblks{0U};
  std::uint64_t heap_available_estimate{0U};
  std::uint64_t heap_used_estimate{0U};
  std::uint64_t linear_total{0U};
  std::uint64_t linear_free{0U};
  std::uint64_t heap_available_low_water{0U};
  std::uint64_t linear_low_water{0U};
  std::uint64_t lua_bytes{0U};
  std::uint64_t lua_peak_bytes{0U};
  bool low_water_valid{false};
};

std::uint64_t non_negative_allocator_field(int value) noexcept {
  return value > 0 ? static_cast<std::uint64_t>(value) : 0U;
}

HeapSnapshot heap_snapshot(bool update_watermarks = true) noexcept {
  const struct mallinfo info = mallinfo();
  HeapSnapshot result;
  result.heap_total = static_cast<std::uint64_t>(envGetHeapSize());
  result.arena = non_negative_allocator_field(info.arena);
  result.uordblks = non_negative_allocator_field(info.uordblks);
  result.fordblks = non_negative_allocator_field(info.fordblks);
  result.heap_available_estimate =
      estimate_heap_available(result.heap_total, result.arena, result.fordblks);
  result.heap_used_estimate = result.heap_total - result.heap_available_estimate;
  result.linear_total = static_cast<std::uint64_t>(envGetLinearHeapSize());
  result.linear_free = static_cast<std::uint64_t>(linearSpaceFree());
  if (g_heap_watermarks_initialized && update_watermarks) {
    g_min_heap_available =
        std::min(g_min_heap_available, result.heap_available_estimate);
    g_min_linear_free = std::min(g_min_linear_free, result.linear_free);
  }
  result.low_water_valid = g_heap_watermarks_initialized;
  if (result.low_water_valid) {
    result.heap_available_low_water = g_min_heap_available;
    result.linear_low_water = g_min_linear_free;
  }
  result.lua_bytes = g_lua_bytes;
  result.lua_peak_bytes = g_lua_peak_bytes;
  return result;
}

void initialize_heap_watermarks() noexcept {
  if (g_heap_watermarks_initialized) {
    return;
  }
  // libctru constructs both process heaps before entering the application.
  // register_lua_module is our first application-owned entry point, so defer
  // the low-water baseline until that point instead of sampling at static init.
  const HeapSnapshot initial = heap_snapshot(false);
  g_min_heap_available = initial.heap_available_estimate;
  g_min_linear_free = initial.linear_free;
  g_heap_watermarks_initialized = true;
}

void update_lua_memory(lua_State* state) noexcept {
  if (state == nullptr) {
    return;
  }
  const int kib = lua_gc(state, LUA_GCCOUNT, 0);
  const int remainder = lua_gc(state, LUA_GCCOUNTB, 0);
  if (kib >= 0 && remainder >= 0) {
    g_lua_bytes = static_cast<std::uint64_t>(kib) * 1024U +
                  static_cast<std::uint64_t>(remainder);
    g_lua_peak_bytes = std::max(g_lua_peak_bytes, g_lua_bytes);
  }
}

void boot_log_open() {
  if (g_log_attempted) {
    return;
  }
  g_log_attempted = true;
  g_boot_started_ms = osGetTime();
  g_log = std::fopen(kLogPath, "w");
  if (g_log == nullptr) {
    return;
  }
  // Unbuffered: a freeze must not swallow the line that explains it.
  std::setvbuf(g_log, nullptr, _IONBF, 0);
  // Give CorsixTH's own diagnostics somewhere to land too.
  if (std::freopen(kLogPath, "a", stderr) != nullptr) {
    std::setvbuf(stderr, nullptr, _IONBF, 0);
  }
}

void boot_log(const char* format, ...) {
  if (g_log == nullptr) {
    return;
  }
  std::va_list arguments;
  va_start(arguments, format);
  std::vfprintf(g_log, format, arguments);
  va_end(arguments);
  std::fputc('\n', g_log);
}

void boot_log_close() {
  if (g_log != nullptr) {
    std::fclose(g_log);
    g_log = nullptr;
  }
}

u64 boot_elapsed_ms() noexcept {
  return g_boot_started_ms == 0U ? 0U : osGetTime() - g_boot_started_ms;
}

void boot_log_resources(const char* stage) {
  if (g_resource_categories_supplied == 0U) {
    return;
  }
  for (std::size_t index = 0U; index < g_resource_bytes.size(); ++index) {
    const std::uint32_t bit = 1U << static_cast<std::uint32_t>(index);
    if ((g_resource_categories_supplied & bit) == 0U) {
      continue;
    }
    const std::string_view name = kResourceMemoryCategoryNames[index];
    boot_log("diagnostic-memory[%s] +%llums: category=%.*s bytes=%llu",
             stage != nullptr ? stage : "?",
             static_cast<unsigned long long>(boot_elapsed_ms()),
             static_cast<int>(name.size()), name.data(),
             static_cast<unsigned long long>(g_resource_bytes[index]));
  }
}

void boot_log_memory(const char* stage) {
  const HeapSnapshot memory = heap_snapshot();
  boot_log(
      "memory[%s] +%llums: env_heap_total=%llu arena=%llu uordblks=%llu "
      "fordblks=%llu heap_available_estimate=%llu heap_used_estimate=%llu "
      "linear_total=%llu linear_free=%llu heap_available_low=%llu linear_low=%llu "
      "low_water_valid=%s lua_current=%llu lua_peak=%llu",
      stage != nullptr ? stage : "?",
      static_cast<unsigned long long>(boot_elapsed_ms()),
      static_cast<unsigned long long>(memory.heap_total),
      static_cast<unsigned long long>(memory.arena),
      static_cast<unsigned long long>(memory.uordblks),
      static_cast<unsigned long long>(memory.fordblks),
      static_cast<unsigned long long>(memory.heap_available_estimate),
      static_cast<unsigned long long>(memory.heap_used_estimate),
      static_cast<unsigned long long>(memory.linear_total),
      static_cast<unsigned long long>(memory.linear_free),
      static_cast<unsigned long long>(memory.heap_available_low_water),
      static_cast<unsigned long long>(memory.linear_low_water),
      memory.low_water_valid ? "yes" : "no",
      static_cast<unsigned long long>(memory.lua_bytes),
      static_cast<unsigned long long>(memory.lua_peak_bytes));
  boot_log_resources(stage);
}

void boot_log_checkpoint(const char* checkpoint, const char* phase,
                         const char* identity = nullptr,
                         std::uint64_t bytes = 0U,
                         std::uint64_t requested_bytes = 0U) {
  const char* safe_checkpoint = checkpoint != nullptr ? checkpoint : "unknown";
  const bool known = is_memory_checkpoint(safe_checkpoint);
  if (bytes > 0U) {
    const ResourceMemoryCategory category =
        checkpoint_resource_category(safe_checkpoint);
    const std::size_t index = static_cast<std::size_t>(category);
    g_resource_bytes[index] = bytes;
    g_resource_categories_supplied |= 1U << static_cast<std::uint32_t>(index);
  }
  boot_log(
      "checkpoint[%s] +%llums: stage=%s phase=%s identity=%s bytes=%llu "
      "requested=%llu known=%s",
      safe_checkpoint, static_cast<unsigned long long>(boot_elapsed_ms()),
      g_current_stage, phase != nullptr ? phase : "event",
      identity != nullptr ? identity : "-", static_cast<unsigned long long>(bytes),
      static_cast<unsigned long long>(requested_bytes), known ? "yes" : "no");
  boot_log_memory(g_current_stage);
}

void* regular_probe_allocate(std::size_t bytes, void*) noexcept {
  auto* allocation = static_cast<std::uint8_t*>(std::malloc(bytes));
  if (allocation == nullptr) return nullptr;
  if (!touch_probe_pages(allocation, bytes)) {
    std::free(allocation);
    return nullptr;
  }
  return allocation;
}

void regular_probe_release(void* allocation, void*) noexcept {
  std::free(allocation);
}

void record_resource_memory(const char* category, std::uint64_t bytes,
                            const char* identity) {
  const ResourceMemoryCategory parsed =
      resource_memory_category(category != nullptr ? category : "other");
  const std::size_t index = static_cast<std::size_t>(parsed);
  g_resource_bytes[index] = bytes;
  g_resource_categories_supplied |= 1U << static_cast<std::uint32_t>(index);
  const std::string_view name = kResourceMemoryCategoryNames[index];
  boot_log("resource-update +%llums: stage=%s category=%.*s identity=%s bytes=%llu",
           static_cast<unsigned long long>(boot_elapsed_ms()),
           g_current_stage, static_cast<int>(name.size()), name.data(),
           identity != nullptr ? identity : "-",
           static_cast<unsigned long long>(bytes));
}

void log_allocation_failure(const char* category, const char* identity,
                            std::uint64_t requested_bytes, const char* allocator,
                            const char* detail) {
  boot_log(
      "allocation-failure +%llums: stage=%s category=%s resource=%s "
      "allocator=%s requested=%llu detail=%s",
      static_cast<unsigned long long>(boot_elapsed_ms()),
      g_current_stage, category != nullptr ? category : "other",
      identity != nullptr ? identity : "unknown",
      allocator != nullptr ? allocator : "app",
      static_cast<unsigned long long>(requested_bytes),
      detail != nullptr ? detail : "allocation returned null");
  boot_log_memory(g_current_stage);
}

std::array<char, 33> resource_identity(const ResourceId& id) noexcept {
  constexpr char digits[] = "0123456789abcdef";
  std::array<char, 33> result{};
  for (std::size_t index = 0U; index < id.size(); ++index) {
    result[index * 2U] = digits[id[index] >> 4U];
    result[index * 2U + 1U] = digits[id[index] & 0x0FU];
  }
  return result;
}

class RuntimeResourceTelemetry final : public ResourceTelemetrySink {
 public:
  void pool_changed(ResourcePool pool, std::uint64_t bytes,
                    const ResourceId& id) noexcept override {
    const std::size_t index = static_cast<std::size_t>(pool);
    if (index >= g_resource_pool_bytes.size()) return;
    g_resource_pool_bytes[index] = bytes;
    const std::string_view name = kResourcePoolNames[index];
    const auto identity = resource_identity(id);
    boot_log(
        "resource-pool +%llums: stage=%s pool=%.*s bytes=%llu resource=%s",
        static_cast<unsigned long long>(boot_elapsed_ms()), g_current_stage,
        static_cast<int>(name.size()), name.data(),
        static_cast<unsigned long long>(bytes), identity.data());
  }

  void cache_event(CacheEvent event, ResourcePool pool, const ResourceId& id,
                   std::uint64_t bytes, std::uint32_t refcount,
                   std::uint32_t group_id) noexcept override {
    const std::size_t index = static_cast<std::size_t>(pool);
    const std::string_view name = index < kResourcePoolNames.size()
                                      ? kResourcePoolNames[index]
                                      : std::string_view{"unknown"};
    const auto identity = resource_identity(id);
    if (event == CacheEvent::Allocate) {
      ++g_resource_cache_entries;
      ++g_resource_cache_leases;
    } else if (event == CacheEvent::Acquire) {
      ++g_resource_cache_leases;
    } else if (event == CacheEvent::Release && g_resource_cache_leases != 0U) {
      --g_resource_cache_leases;
    } else if (event == CacheEvent::Evict) {
      if (g_resource_cache_entries != 0U) --g_resource_cache_entries;
      ++g_resource_cache_evictions;
    }
    boot_log(
        "resource-cache +%llums: stage=%s event=%u pool=%.*s resource=%s "
        "bytes=%llu refcount=%lu group=%lu",
        static_cast<unsigned long long>(boot_elapsed_ms()), g_current_stage,
        static_cast<unsigned int>(event), static_cast<int>(name.size()),
        name.data(), identity.data(), static_cast<unsigned long long>(bytes),
        static_cast<unsigned long>(refcount), static_cast<unsigned long>(group_id));
  }

  void allocation_rejected(const ResourceError& resource_error, ResourcePool pool,
                           std::uint64_t requested_bytes) noexcept override {
    ++g_resource_cache_rejects;
    const std::size_t index = static_cast<std::size_t>(pool);
    const std::string_view name = index < kResourcePoolNames.size()
                                      ? kResourcePoolNames[index]
                                      : std::string_view{"unknown"};
    const auto identity = resource_identity(resource_error.resource_id);
    log_allocation_failure(name.data(), identity.data(), requested_bytes,
                           "resource-manager",
                           resource_error_name(resource_error.code));
  }
};

class RuntimeResourceBudgetGate final : public ResourceBudgetGate {
 public:
  bool allow_allocation(ResourceStage stage, ResourcePool pool,
                        std::uint64_t requested_bytes,
                        std::uint64_t, std::uint64_t scratch_bytes,
                        ResourceError& resource_error) noexcept override {
    const HeapSnapshot memory = heap_snapshot(false);
    const MemoryGatePolicy policy = memory_gate_policy(to_memory_gate(stage));
    const std::uint64_t extra = pool == ResourcePool::Scratch
                                    ? requested_bytes
                                    : (scratch_bytes >
                                               std::numeric_limits<std::uint64_t>::max() -
                                                   requested_bytes
                                           ? std::numeric_limits<std::uint64_t>::max()
                                           : requested_bytes + scratch_bytes);
    const bool used_ok =
        extra <= policy.maximum_heap_used &&
        memory.heap_used_estimate <= policy.maximum_heap_used - extra;
    const bool available_ok =
        extra <= memory.heap_available_estimate &&
        memory.heap_available_estimate - extra >= policy.minimum_heap_available;
    const bool totals_ok = memory.heap_total >= kMinimumHeapTotal &&
                           memory.linear_total == kRequiredLinearTotal;
    if (totals_ok && used_ok && available_ok) return true;
    resource_error = {ResourceErrorCode::BudgetContract,
                      "runtime heap stage gate rejected allocation", {}};
    return false;
  }

  bool allow_operation(TransitionKind kind,
                       ResourceError& resource_error) noexcept override {
    const HeapSnapshot memory = heap_snapshot(false);
    if (memory.heap_available_estimate < 8U * kMiB) {
      resource_error = {
          kind == TransitionKind::SaveLoad ? ResourceErrorCode::SaveReserve
                                           : ResourceErrorCode::TransitionReserve,
          "operation requires at least 8 MiB heap headroom", {}};
      return false;
    }
    ContiguousProbePolicy probe_policy;
    probe_policy.minimum_success_bytes = 4U * static_cast<std::size_t>(kMiB);
    probe_policy.reserve_bytes = 4U * static_cast<std::size_t>(kMiB);
    probe_policy.maximum_probe_bytes = 4U * static_cast<std::size_t>(kMiB);
    const ContiguousProbeResult probe = probe_largest_contiguous(
        static_cast<std::size_t>(memory.heap_available_estimate), probe_policy,
        regular_probe_allocate, regular_probe_release);
    if (probe.met_minimum) return true;
    resource_error = {
        kind == TransitionKind::SaveLoad ? ResourceErrorCode::SaveReserve
                                         : ResourceErrorCode::TransitionReserve,
        "operation 4 MiB contiguous reserve probe failed", {}};
    return false;
  }

 private:
  static MemoryGate to_memory_gate(ResourceStage stage) noexcept {
    switch (stage) {
      case ResourceStage::Boot: return MemoryGate::Boot;
      case ResourceStage::SelectedLanguage: return MemoryGate::SelectedLanguage;
      case ResourceStage::Menu: return MemoryGate::MenuStable;
      case ResourceStage::FirstLevel: return MemoryGate::LevelStable;
      case ResourceStage::Operation: return MemoryGate::Operation;
    }
    return MemoryGate::Operation;
  }
};

// Identity of the Lua adapter this process actually ended up running. Printed
// on the lower screen so a binary/SD-card mismatch is visible without a
// debugger; that mismatch is exactly what "3DS ADAPTER IS NOT ATTACHED" means.
std::string g_adapter_origin = "none";
std::uint32_t g_adapter_crc = 0U;

constexpr std::uint32_t byte_swap32(std::uint32_t value) noexcept {
  return ((value & 0x000000FFU) << 24U) | ((value & 0x0000FF00U) << 8U) |
         ((value & 0x00FF0000U) >> 8U) | ((value & 0xFF000000U) >> 24U);
}

std::uint64_t now_us() noexcept {
  const Uint64 frequency = SDL_GetPerformanceFrequency();
  if (frequency == 0U) {
    return static_cast<std::uint64_t>(SDL_GetTicks()) * 1000U;
  }
  const Uint64 counter = SDL_GetPerformanceCounter();
  return static_cast<std::uint64_t>((counter * 1000000U) / frequency);
}

bool table_boolean(lua_State* state, int index, const char* key, bool fallback) {
  lua_getfield(state, index, key);
  const bool result = lua_isboolean(state, -1) ? lua_toboolean(state, -1) != 0 : fallback;
  lua_pop(state, 1);
  return result;
}

lua_Integer table_integer(lua_State* state, int index, const char* key,
                          lua_Integer fallback) {
  lua_getfield(state, index, key);
  const lua_Integer result = lua_isnumber(state, -1) ? lua_tointeger(state, -1) : fallback;
  lua_pop(state, 1);
  return result;
}

std::string table_string(lua_State* state, int index, const char* key,
                         std::string fallback = {}) {
  lua_getfield(state, index, key);
  if (lua_isstring(state, -1)) {
    const char* value = lua_tostring(state, -1);
    if (value != nullptr) {
      fallback = value;
    }
  }
  lua_pop(state, 1);
  return fallback;
}

std::uint32_t convert_keys(u32 keys) noexcept {
  std::uint32_t result = 0;
  const auto add = [&result, keys](u32 source, Button target) {
    if ((keys & source) != 0U) {
      result |= button_mask(target);
    }
  };
  add(KEY_A, Button::A);
  add(KEY_B, Button::B);
  add(KEY_SELECT, Button::Select);
  add(KEY_START, Button::Start);
  add(KEY_DRIGHT, Button::DRight);
  add(KEY_DLEFT, Button::DLeft);
  add(KEY_DUP, Button::DUp);
  add(KEY_DDOWN, Button::DDown);
  add(KEY_R, Button::R);
  add(KEY_L, Button::L);
  add(KEY_X, Button::X);
  add(KEY_Y, Button::Y);
  return result;
}

void push_action(lua_State* state, const Action& action) {
  lua_newtable(state);
  const std::string_view name = action_name(action.type);
  lua_pushlstring(state, name.data(), name.size());
  lua_setfield(state, -2, "type");

  lua_pushnumber(state, static_cast<lua_Number>(action.vector.x));
  lua_setfield(state, -2, "dx");
  lua_pushnumber(state, static_cast<lua_Number>(action.vector.y));
  lua_setfield(state, -2, "dy");
  lua_pushinteger(state, action.position.x);
  lua_setfield(state, -2, "x");
  lua_pushinteger(state, action.position.y);
  lua_setfield(state, -2, "y");
  lua_pushinteger(state, action.rectangle.x);
  lua_setfield(state, -2, "rect_x");
  lua_pushinteger(state, action.rectangle.y);
  lua_setfield(state, -2, "rect_y");
  lua_pushinteger(state, action.rectangle.w);
  lua_setfield(state, -2, "rect_w");
  lua_pushinteger(state, action.rectangle.h);
  lua_setfield(state, -2, "rect_h");
  lua_pushinteger(state, action.value);
  lua_setfield(state, -2, "value");
  lua_pushboolean(state, action.repeated ? 1 : 0);
  lua_setfield(state, -2, "repeated");
  if (!action.text.empty()) {
    lua_pushlstring(state, action.text.data(), action.text.size());
    lua_setfield(state, -2, "text");
  }
}

struct AdapterCall {
  const char* method{nullptr};
  const Action* action{nullptr};
};

// Everything that touches Lua from the runtime runs inside this function, which
// is always entered through lua_pcall.
//
// The previous version reached into globals directly. CorsixTH installs
// strict.lua, which raises a Lua error from the _G __index metamethod for any
// undeclared global; raising across an unprotected C boundary reaches
// lua_atpanic and aborts the process. On a 3DS an abort is indistinguishable
// from a freeze, with no message anywhere.
int l_protected_adapter_call(lua_State* state) {
  auto* request = static_cast<AdapterCall*>(lua_touserdata(state, 1));
  lua_settop(state, 0);

  lua_getglobal(state, "TheApp");
  if (!lua_istable(state, -1)) {
    return luaL_error(state, "TheApp is not ready");
  }
  lua_getfield(state, -1, "_3ds");
  if (!lua_istable(state, -1)) {
    return luaL_error(state, "3DS adapter is not attached");
  }
  lua_getfield(state, -1, request->method);
  if (!lua_isfunction(state, -1)) {
    return luaL_error(state, "missing adapter method: %s", request->method);
  }
  lua_pushvalue(state, -2);
  int argument_count = 1;
  if (request->action != nullptr) {
    push_action(state, *request->action);
    ++argument_count;
  }
  lua_call(state, argument_count, 0);
  return 0;
}

bool call_platform_method(lua_State* state, const char* method,
                          const Action* action = nullptr,
                          std::string* error = nullptr) {
  const int base = lua_gettop(state);
  AdapterCall request{method, action};
  lua_pushcfunction(state, l_protected_adapter_call);
  lua_pushlightuserdata(state, &request);
  if (lua_pcall(state, 1, 0, 0) != LUA_OK) {
    const char* message = lua_tostring(state, -1);
    const std::string detail = message != nullptr ? message : "unknown error";
    if (error != nullptr) {
      *error = detail;
    }
    boot_log("adapter call %s failed: %s", method, detail.c_str());
    lua_settop(state, base);
    return false;
  }
  lua_settop(state, base);
  return true;
}

// Select code before App mutation. Attachment has one Lua owner after menu.
int ensure_adapter(lua_State* state) {
  boot_log_checkpoint("adapter_attach", "begin");
  lua_getglobal(state,"require");lua_pushstring(state,kAdapterModule);
  if(lua_pcall(state,1,1,0)!=LUA_OK) {
    lua_pop(state,1);
    if(luaL_loadbuffer(state,kEmbeddedPlatformLua,std::strlen(kEmbeddedPlatformLua),"@builtin/3ds/platform.lua")!=LUA_OK)return lua_error(state);
    lua_call(state,0,1);
  }
  if(!lua_istable(state,-1))return luaL_error(state,"adapter module must return a table");
  return 1;
}

class Runtime {
 public:
  Runtime()
      : overlay_canvas_(ScreenLayout::kBottomWidth, kOverlayHeight),
        scheduler_(18000U, 33333U, 33333U, 3), lifecycle_(60000000U),
        telemetry_(240U) {}

  bool initialize(lua_State* state, const char* mode) {
    if (!mode || (std::strcmp(mode,"loose") && std::strcmp(mode,"th3ds"))) return false;
    if (initialized_) return state == lua_state_ && asset_mode_ == mode;
    if (lua_state_ && lua_state_ != state) return false;
    lua_state_ = state;
    asset_mode_ = mode;
    ++epoch_;
    stage("S90", "STARTING RUNTIME");
    if (!ensure_bottom_window()) {
      return false;
    }

    if (resource_start_failed_) {
      return false;
    }
    if (asset_mode_ == "th3ds" && resource_session_ == nullptr) {
      RuntimeSessionConfig resource_config;
      resource_config.telemetry = make_runtime_resource_telemetry_sink();
      resource_config.budget_gate = make_runtime_resource_budget_gate();
      resource_config.quiesce_clients = []() {
        Mix_HaltMusic();
        Mix_HaltChannel(-1);
        return ResourceResult<void>::success();
      };
      boot_log("runtime-core: mount begin bundle=%s", kResourceBundlePath);
      auto started = RuntimeSession::start(kResourceBundlePath,
                                           std::move(resource_config));
      if (!started) {
        resource_start_failed_ = true;
        boot_log("runtime-core: mount rollback code=%s detail=%s",
                 resource_error_name(started.error().code),
                 started.error().message.c_str());
        set_notice("RUNTIME CORE MOUNT FAILED - SEE BOOT.LOG", true);
        show_fatal(resource_error_name(started.error().code));
        return false;
      }
      resource_session_ = std::move(started.value());
      const RuntimeSessionSnapshot snapshot = resource_session_->snapshot();
      boot_log(
          "runtime-core: mount commit bundle_sha256=%s packages=%lu "
          "language=%s ledger_metadata=%llu scratch=%llu",
          sha256_hex(resource_session_->bundle()->bundle_sha256).c_str(),
          static_cast<unsigned long>(snapshot.mounted_packages),
          resource_session_->bundle()->selected_language.c_str(),
          static_cast<unsigned long long>(
              snapshot.resources.metadata_baseline_bytes),
          static_cast<unsigned long long>(snapshot.resources.pool_bytes[
              static_cast<std::size_t>(ResourcePool::Scratch)]));
    }

    const Result ptmu_result = ptmuInit();
    ptmu_ready_ = R_SUCCEEDED(ptmu_result);
    aptHook(&apt_cookie_, &Runtime::apt_callback, this);
    apt_hooked_ = true;
    aptSetSleepAllowed(true);

    const std::uint64_t current = now_us();
    lifecycle_.set_autosave_enabled(asset_mode_ == "th3ds");
    lifecycle_.reset(current);
    last_tick_us_ = current;
    state_refresh_gate_.reset(current, true);
    system_refresh_gate_.reset(current, true);
    battery_refresh_gate_.reset(current, true);
    telemetry_log_gate_.reset(current, false);
    scheduler_.reset(current);
    initialized_ = true;
    dirty_ = true;
    refresh_system_status(true);

    boot_log("runtime: lower screen ready (%dx%d)",
             ScreenLayout::kBottomWidth, ScreenLayout::kBottomHeight);
    boot_log_memory("S90");
    {
      // Report whether the top screen lands on the exact 2:1 reduction. Any
      // other ratio means the game window is not 640x480 and the present path
      // is resampling, which is worth knowing when frame times look wrong.
      const RectI viewport = calculate_letterbox_viewport(
          ScreenLayout::kLegacyWidth, ScreenLayout::kLegacyHeight,
          ScreenLayout::kTopWidth, ScreenLayout::kTopHeight);
      int factor = 0;
      const bool exact =
          is_integer_downscale(ScreenLayout::kLegacyWidth, viewport.w, &factor);
      boot_log("present: top viewport %dx%d at x=%d, exact reduction=%s (1/%d)",
               viewport.w, viewport.h, viewport.x, exact ? "yes" : "no", factor);
    }

    boot_log("runtime: dependencies initialized mode=%s epoch=%llu",asset_mode_.c_str(),static_cast<unsigned long long>(epoch_));
    return true;
  }

  bool mark_ready(lua_State* state) {
    if (!initialized_ || state!=lua_state_) return false;
    if (ready_) return true;
    if (!probe_regular_heap("MAIN MENU",MemoryGate::MenuStable)) return false;
    ready_=true;boot_log_checkpoint("adapter_attach", "ready", "lua-owner");stage("S100", "READY");return true;
  }
  bool assert_ready(lua_State* state) const {return initialized_&&ready_&&state==lua_state_;}
  std::uint64_t epoch() const {return epoch_;}

  void shutdown() noexcept {
    if (!initialized_ && !lua_state_ && !bottom_window_) return;
    boot_log("runtime: shutdown requested");
    // Silence the mixer before Lua tears down its channels; a still-running
    // NDSP callback against freed chunks is a classic 3DS exit hang.
    Mix_HaltMusic();
    Mix_HaltChannel(-1);
    if (resource_session_ != nullptr) {
      const auto closed = resource_session_->shutdown();
      if (!closed) {
        boot_log("runtime-core: shutdown rollback code=%s detail=%s",
                 resource_error_name(closed.error().code),
                 closed.error().message.c_str());
      } else {
        boot_log("runtime-core: shutdown commit ledger=baseline");
        resource_session_.reset();
      }
    }
    if (apt_hooked_) {
      aptSetSleepAllowed(true);
      aptUnhook(&apt_cookie_);
      apt_hooked_ = false;
    }
    if (ptmu_ready_) {
      ptmuExit();
      ptmu_ready_ = false;
    }
    if (bottom_window_ != nullptr) {
      SDL_DestroyWindow(bottom_window_);
      bottom_window_ = nullptr;
      bottom_surface_ = nullptr;
      bottom_window_id_ = 0U;
    }
    input_mapper_.reset();
    initialized_ = false; ready_ = false;
    lua_state_ = nullptr;
    game_window_=nullptr;game_window_id_=0;last_game_pointer_={320,240};
    resource_start_failed_=false;resource_session_.reset();
    pending_lifecycle_.store(0);exit_requested_.store(false);
    lifecycle_.reset(0);last_tick_us_=0;scheduler_.reset(0);
    g_adapter_origin.clear();asset_mode_.clear();
    boot_log("runtime: shutdown complete");
    boot_log_close();
  }

  void tick(lua_State* state) {
    if (exit_requested_.load(std::memory_order_relaxed)) {
      // Nothing below is worth doing while the system is tearing us down, and
      // some of it (Lua, SD-card writes) can block for a long time.
      return;
    }
    if (!assert_ready(state)) return;
    const std::uint64_t frame_started = now_us();
    const float delta_seconds = last_tick_us_ == 0U
                                    ? 0.0F
                                    : static_cast<float>(frame_started - last_tick_us_) /
                                          1000000.0F;
    last_tick_us_ = frame_started;

    process_lifecycle(state, frame_started);
    if (state_refresh_gate_.due(frame_started) &&
        bottom_mode_ == BottomScreenMode::Panel) {
      // In game mode nothing on screen consumes this, and walking the hospital
      // tables in Lua is not free on a 268 MHz CPU.
      std::string sync_error;
      if (!call_platform_method(state, "syncBottomState", nullptr, &sync_error)) {
        set_notice("STATE: " + sync_error, true);
      } else if (bottom_ui_.state().notice_is_error) {
        // The old code never cleared the notice, so a single transient failure
        // at boot stayed on screen for the rest of the session and looked like
        // a permanent fault.
        set_notice(std::string(), false);
      }
    }
    const bool refresh_battery = battery_refresh_gate_.due(frame_started);
    if (system_refresh_gate_.due(frame_started) || refresh_battery) {
      refresh_system_status(refresh_battery);
    }

    // SDL's N3DS event pump already called hidScanInput() before the
    // timer/event reached CorsixTH. Scanning again here would erase the
    // one-frame keysDown/keysUp transitions.
    RawInputSnapshot snapshot;
    snapshot.timestamp_us = frame_started;
    snapshot.down = convert_keys(hidKeysDown());
    snapshot.held = convert_keys(hidKeysHeld());
    snapshot.up = convert_keys(hidKeysUp());

    circlePosition circle{};
    hidCircleRead(&circle);
    snapshot.circle_x = circle.dx;
    snapshot.circle_y = circle.dy;

    const u32 raw_held = hidKeysHeld();
    snapshot.touching = (raw_held & KEY_TOUCH) != 0U;
    if (snapshot.touching) {
      touchPosition touch{};
      hidTouchRead(&touch);
      snapshot.touch = {static_cast<int>(touch.px), static_cast<int>(touch.py)};
    }

    const auto actions = input_mapper_.update(
        snapshot, bottom_ui_.state().input_context,
        delta_seconds > 0.1F ? 0.1F : delta_seconds);
    for (const Action& action : actions) {
      const bool is_pointer = action.type == ActionType::PointerDown ||
                              action.type == ActionType::PointerMove ||
                              action.type == ActionType::PointerUp ||
                              action.type == ActionType::Tap ||
                              action.type == ActionType::DoubleTap ||
                              action.type == ActionType::LongPress;
      if (is_pointer && bottom_mode_ == BottomScreenMode::Game) {
        // The lower screen is the game, so the touch goes straight to it.
        // Tap and DoubleTap are derived from the down/up pair the game has
        // already been given, so forwarding them again would double-click.
        forward_pointer_to_game(action);
      } else if (is_pointer) {
        const auto translated = bottom_ui_.process(action);
        dirty_ = true;
        scheduler_.request_redraw();
        for (const Action& translated_action : translated) {
          dispatch(state, translated_action);
        }
      } else if (bottom_mode_ == BottomScreenMode::Game &&
                 handle_button_as_click(action)) {
        // Already delivered straight to the game.
      } else {
        dispatch(state, action);
      }
    }

    const LifecycleDecision periodic = lifecycle_.tick(frame_started);
    apply_lifecycle_decision(state, periodic, false);

    const FrameScheduler::Decision decision = scheduler_.advance(frame_started);
    if (bottom_mode_ == BottomScreenMode::Panel && decision.render_bottom &&
        (dirty_ || bottom_ui_.is_pressed())) {
      // In game mode the lower screen is repainted by after_frame() instead,
      // in lockstep with the frame it mirrors.
      render_bottom();
    }
    const std::uint64_t frame_finished = now_us();
    telemetry_.record_frame(frame_finished - frame_started, decision.dropped_time);
    if (telemetry_log_gate_.due(frame_finished)) {
      update_lua_memory(state);
      const PerformanceSnapshot sample = telemetry_.snapshot();
      boot_log(
          "telemetry: avg_ms=%.3f p95_ms=%.3f max_ms=%.3f dropped=%llu",
          sample.average_frame_ms, sample.p95_frame_ms, sample.maximum_frame_ms,
          static_cast<unsigned long long>(sample.dropped_frames));
      boot_log_memory("RUNNING");
    }
  }

  bool consumes_event(const SDL_Event& event) const noexcept {
    if (!initialized_ || bottom_window_id_ == 0U) {
      return false;
    }
    switch (event.type) {
      case SDL_MOUSEMOTION: return event.motion.windowID == bottom_window_id_;
      case SDL_MOUSEBUTTONDOWN:
      case SDL_MOUSEBUTTONUP: return event.button.windowID == bottom_window_id_;
      case SDL_MOUSEWHEEL: return event.wheel.windowID == bottom_window_id_;
      case SDL_FINGERDOWN:
      case SDL_FINGERUP:
      case SDL_FINGERMOTION: return event.tfinger.windowID == bottom_window_id_;
      case SDL_WINDOWEVENT: return event.window.windowID == bottom_window_id_;
      default: return false;
    }
  }

  void set_state(BottomUiState state) {
    if (bottom_ui_.state() == state) {
      return;
    }
    const BottomTab previous_tab = bottom_ui_.state().active_tab;
    bottom_ui_.set_state(std::move(state));
    if (previous_tab != bottom_ui_.state().active_tab) {
      scheduler_.request_redraw();
    }
    dirty_ = true;
  }

  BottomUiState state() const { return bottom_ui_.state(); }

  void request_redraw() noexcept {
    dirty_ = true;
    scheduler_.request_redraw();
  }

  void force_render_bottom() {
    dirty_ = true;
    if (bottom_mode_ == BottomScreenMode::Game) {
      mirror_game_to_bottom();
    } else {
      render_bottom();
    }
  }

  //! Told to us by render_target's constructor, because SDL2 has no way to
  //! enumerate windows and the lower screen has to read the frame CorsixTH
  //! just drew.
  void set_game_window(SDL_Window* window) noexcept {
    game_window_ = window;
    game_window_id_ = window != nullptr ? SDL_GetWindowID(window) : 0U;
    boot_log("runtime: game window registered (id %lu)",
             static_cast<unsigned long>(game_window_id_));
    try {
      (void)ensure_bottom_window();
      stage("S30", "GAME WINDOW READY");
    } catch (const std::exception& error) {
      boot_log("runtime: early lower screen failed: %s", error.what());
    } catch (...) {
      boot_log("runtime: early lower screen failed: unknown error");
    }
  }

  void stage(const char* code, const char* label) {
    startup_code_ = code != nullptr ? code : "S??";
    startup_label_ = label != nullptr ? label : "STARTING";
    (void)std::snprintf(g_current_stage, sizeof(g_current_stage), "%s",
                        startup_code_.c_str());
    (void)std::snprintf(g_current_stage_label, sizeof(g_current_stage_label), "%s",
                        startup_label_.c_str());
    const u64 elapsed = boot_elapsed_ms();
    boot_log("stage[%s] +%llums: %s", startup_code_.c_str(),
             static_cast<unsigned long long>(elapsed), startup_label_.c_str());
    boot_log_memory(startup_code_.c_str());
    if (bottom_window_ != nullptr && !initialized_) {
      render_boot_page(false);
    }
  }

  void show_fatal(const char* reason) {
    startup_code_ = "FATAL";
    startup_label_ = reason != nullptr ? reason : "UNKNOWN ERROR";
    (void)ensure_bottom_window();
    render_boot_page(true);
  }

  //! Called straight after CorsixTH presents a frame. In game mode the lower
  //! screen is the same frame at an exact 2:1 reduction, so the player sees
  //! the real interface - toolbar, dialogs and all - and can touch it.
  void after_frame() {
    if (!initialized_ || bottom_mode_ != BottomScreenMode::Game) {
      return;
    }
    mirror_game_to_bottom();
  }

  [[nodiscard]] bool mirrors_game() const noexcept {
    return bottom_mode_ == BottomScreenMode::Game;
  }

  void begin_critical_io() noexcept {
    const bool was_active = lifecycle_.in_critical_io();
    lifecycle_.begin_critical_io();
    if (!was_active) {
      aptSetSleepAllowed(false);
    }
  }

  void end_critical_io() noexcept {
    lifecycle_.end_critical_io();
    if (!lifecycle_.in_critical_io()) {
      aptSetSleepAllowed(true);
    }
  }

  ResourceResult<void> resource_event(std::string_view event,
                                      std::string_view identity,
                                      bool success) {
    if (asset_mode_ == "loose") {
      return ResourceResult<void>::failure({ResourceErrorCode::Internal,"resource_event is invalid in loose mode",{}});
    }
    if (resource_session_ == nullptr) {
      return ResourceResult<void>::failure(
          {ResourceErrorCode::Internal,
           "Runtime Core session is not available", {}});
    }
    ResourceResult<void> result = ResourceResult<void>::success();
    if (event == "menu") {
      result = resource_session_->enter_menu(1U);
    } else if (event == "level") {
      result = resource_session_->enter_level(resource_group_id(identity));
    } else if (event == "save-begin" || event == "load-begin") {
      result = resource_session_->begin_save_load();
    } else if (event == "save-end" || event == "load-end") {
      result = resource_session_->finish_save_load(success);
    } else {
      result = ResourceResult<void>::failure(
          {ResourceErrorCode::Internal,
           "unknown Runtime Core lifecycle event", {}});
    }
    boot_log("runtime-core: event=%.*s identity=%.*s result=%s code=%s",
             static_cast<int>(event.size()), event.data(),
             static_cast<int>(identity.size()), identity.data(),
             result ? "commit" : "rollback",
             result ? "OK" : resource_error_name(result.error().code));
    return result;
  }

  void set_notice(std::string notice, bool is_error) {
    BottomUiState copy = bottom_ui_.state();
    if (copy.notice == notice && copy.notice_is_error == is_error) {
      return;
    }
    copy.notice = std::move(notice);
    copy.notice_is_error = is_error;
    bottom_ui_.set_state(std::move(copy));
    dirty_ = true;
    scheduler_.request_redraw();
  }

  PerformanceSnapshot performance() const { return telemetry_.snapshot(); }

  bool probe_regular_heap(const char* label,
                          MemoryGate gate = MemoryGate::MenuStable) {
    const HeapSnapshot before = heap_snapshot();
    const MemoryGatePolicy gate_policy = memory_gate_policy(gate);
    const MemoryGateResult gate_result = evaluate_memory_gate(
        before.heap_total, before.heap_available_estimate, before.linear_total,
        gate_policy);
    boot_log(
        "memory-gate[%s]: %s heap_total=%llu/%llu linear_total=%llu/%llu "
        "heap_used=%llu/%llu heap_available=%llu/%llu probe=%lu reserve=%lu",
        label != nullptr ? label : "?", gate_result.pass() ? "PASS" : "FAIL",
        static_cast<unsigned long long>(before.heap_total),
        static_cast<unsigned long long>(kMinimumHeapTotal),
        static_cast<unsigned long long>(before.linear_total),
        static_cast<unsigned long long>(kRequiredLinearTotal),
        static_cast<unsigned long long>(gate_result.heap_used),
        static_cast<unsigned long long>(gate_policy.maximum_heap_used),
        static_cast<unsigned long long>(before.heap_available_estimate),
        static_cast<unsigned long long>(gate_policy.minimum_heap_available),
        static_cast<unsigned long>(gate_policy.probe_bytes),
        static_cast<unsigned long>(gate_policy.probe_reserve_bytes));
    if (!gate_result.pass()) {
      boot_log_memory("E-MEMORY-GATE");
      return false;
    }
    ContiguousProbePolicy policy;
    policy.minimum_success_bytes = gate_policy.probe_bytes;
    policy.reserve_bytes = gate_policy.probe_reserve_bytes;
    const ContiguousProbeResult result = probe_largest_contiguous(
        static_cast<std::size_t>(before.heap_available_estimate), policy,
        regular_probe_allocate, regular_probe_release);
    if (!result.met_minimum) {
      boot_log(
          "heap-probe[%s]: FAIL minimum=%lu verified=%lu limit=%lu attempts=%lu "
          "reserve=%lu capped=%s",
          label != nullptr ? label : "?",
          static_cast<unsigned long>(gate_policy.probe_bytes),
          static_cast<unsigned long>(result.verified_bytes),
          static_cast<unsigned long>(result.attempted_limit_bytes),
          static_cast<unsigned long>(result.attempts),
          static_cast<unsigned long>(policy.reserve_bytes),
          result.capped ? "yes" : "no");
      boot_log_memory("E-HEAP-PROBE");
      return false;
    }
    boot_log(
        "heap-probe[%s]: PASS minimum=%lu verified=%lu limit=%lu attempts=%lu "
        "reserve=%lu capped=%s result=verified-lower-bound",
        label != nullptr ? label : "?",
        static_cast<unsigned long>(gate_policy.probe_bytes),
        static_cast<unsigned long>(result.verified_bytes),
        static_cast<unsigned long>(result.attempted_limit_bytes),
        static_cast<unsigned long>(result.attempts),
        static_cast<unsigned long>(policy.reserve_bytes),
        result.capped ? "yes" : "no");
    boot_log_memory(label != nullptr ? label : "PROBE");
    return true;
  }

 private:
  static void apt_callback(APT_HookType hook, void* parameter) {
    auto* runtime = static_cast<Runtime*>(parameter);
    if (runtime == nullptr) {
      return;
    }
    std::uint32_t bit = 0U;
    switch (hook) {
      case APTHOOK_ONSUSPEND: bit = kLifecycleSuspend; break;
      case APTHOOK_ONRESTORE: bit = kLifecycleRestore; break;
      case APTHOOK_ONSLEEP: bit = kLifecycleSleep; break;
      case APTHOOK_ONWAKEUP: bit = kLifecycleWake; break;
      case APTHOOK_ONEXIT: bit = kLifecycleExit; break;
      default: break;
    }
    runtime->pending_lifecycle_.fetch_or(bit, std::memory_order_relaxed);
    if (bit == kLifecycleExit) {
      // APT expects the process to go away promptly. Queue the quit here, on
      // the APT thread, instead of waiting for the next runtime_tick: if the
      // main thread is inside a long frame, or Lua is wedged, waiting is
      // exactly what makes HOME -> Close look like a hang.
      runtime->exit_requested_.store(true, std::memory_order_relaxed);
      SDL_Event quit{};
      quit.type = SDL_QUIT;
      SDL_PushEvent(&quit);
    }
  }

  //! Turn a lower-screen touch into a mouse event on the CorsixTH window.
  //!
  //! The lower screen shows the whole 640x480 frame at exactly half size, so
  //! the mapping is a doubling with no rounding error: whatever the player's
  //! finger is over is the pixel the game sees.
  void forward_pointer_to_game(const Action& action) {
    if (game_window_id_ == 0U) {
      return;
    }
    const Vec2i game_point = ScreenLayout::bottom_touch_to_legacy(action.position);

    const auto push_motion = [&]() {
      SDL_Event event{};
      event.motion.type = SDL_MOUSEMOTION;
      event.motion.windowID = game_window_id_;
      event.motion.x = game_point.x;
      event.motion.y = game_point.y;
      event.motion.xrel = game_point.x - last_game_pointer_.x;
      event.motion.yrel = game_point.y - last_game_pointer_.y;
      SDL_PushEvent(&event);
      last_game_pointer_ = game_point;
    };
    const auto push_button = [&](Uint8 button, bool pressed) {
      SDL_Event event{};
      event.button.type = pressed ? SDL_MOUSEBUTTONDOWN : SDL_MOUSEBUTTONUP;
      event.button.windowID = game_window_id_;
      event.button.button = button;
      event.button.state = pressed ? SDL_PRESSED : SDL_RELEASED;
      event.button.clicks = 1U;
      event.button.x = game_point.x;
      event.button.y = game_point.y;
      SDL_PushEvent(&event);
    };

    switch (action.type) {
      case ActionType::PointerDown:
        push_motion();
        push_button(SDL_BUTTON_LEFT, true);
        break;
      case ActionType::PointerMove:
        push_motion();
        break;
      case ActionType::PointerUp:
        push_motion();
        push_button(SDL_BUTTON_LEFT, false);
        break;
      default:
        // Tap, DoubleTap and LongPress are all derived from the down/up pair
        // the game has already been given. Forwarding them too would turn one
        // touch into several clicks. The right button lives on B and X, which
        // stay reachable with a stylus in hand.
        break;
    }
  }

  //! Inject a click at the last touched point.
  //!
  //! Theme Hospital cancels and rotates with the right button, and the Lua
  //! adapter's own cursor is a separate d-pad cursor, so routing the face
  //! buttons through Lua would click somewhere other than where the player is
  //! looking. Going straight to SDL keeps one cursor.
  void click_at_pointer(Uint8 button) {
    if (game_window_id_ == 0U) {
      return;
    }
    SDL_Event motion{};
    motion.motion.type = SDL_MOUSEMOTION;
    motion.motion.windowID = game_window_id_;
    motion.motion.x = last_game_pointer_.x;
    motion.motion.y = last_game_pointer_.y;
    SDL_PushEvent(&motion);
    for (const bool pressed : {true, false}) {
      SDL_Event event{};
      event.button.type = pressed ? SDL_MOUSEBUTTONDOWN : SDL_MOUSEBUTTONUP;
      event.button.windowID = game_window_id_;
      event.button.button = button;
      event.button.state = pressed ? SDL_PRESSED : SDL_RELEASED;
      event.button.clicks = 1U;
      event.button.x = last_game_pointer_.x;
      event.button.y = last_game_pointer_.y;
      SDL_PushEvent(&event);
    }
  }

  //! True when the action was handled as a direct click on the game.
  [[nodiscard]] bool handle_button_as_click(const Action& action) {
    switch (action.type) {
      case ActionType::Confirm:
      case ActionType::PlaceItem:
        click_at_pointer(SDL_BUTTON_LEFT);
        return true;
      case ActionType::Cancel:
      case ActionType::RotateObject:
        click_at_pointer(SDL_BUTTON_RIGHT);
        return true;
      default:
        return false;
    }
  }

  void dispatch(lua_State* state, const Action& action) {
    if (action.type == ActionType::OpenDashboard) {
      BottomUiState copy = bottom_ui_.state();
      copy.active_tab = BottomTab::Dashboard;
      bottom_ui_.set_state(std::move(copy));
    } else if (action.type == ActionType::OpenBuild) {
      BottomUiState copy = bottom_ui_.state();
      copy.active_tab = BottomTab::Build;
      bottom_ui_.set_state(std::move(copy));
    } else if (action.type == ActionType::OpenStaff) {
      BottomUiState copy = bottom_ui_.state();
      copy.active_tab = BottomTab::Staff;
      bottom_ui_.set_state(std::move(copy));
    } else if (action.type == ActionType::OpenPatients) {
      BottomUiState copy = bottom_ui_.state();
      copy.active_tab = BottomTab::Patients;
      bottom_ui_.set_state(std::move(copy));
    } else if (action.type == ActionType::OpenFinance) {
      BottomUiState copy = bottom_ui_.state();
      copy.active_tab = BottomTab::Finance;
      bottom_ui_.set_state(std::move(copy));
    } else if (action.type == ActionType::OpenMessages) {
      BottomUiState copy = bottom_ui_.state();
      copy.active_tab = BottomTab::Messages;
      bottom_ui_.set_state(std::move(copy));
    }
    dirty_ = true;
    std::string action_error;
    if (!call_platform_method(state, "handleAction", &action, &action_error)) {
      set_notice("ACTION: " + action_error, true);
    }
  }

  void process_lifecycle(lua_State* state, std::uint64_t current) {
    const std::uint32_t flags = pending_lifecycle_.exchange(0U, std::memory_order_relaxed);
    if (flags != 0U) {
      boot_log("lifecycle: flags=0x%08lx", static_cast<unsigned long>(flags));
    }
    if ((flags & kLifecycleSuspend) != 0U) {
      apply_lifecycle_decision(
          state, lifecycle_.signal(LifecycleSignal::Suspend, current), false);
    }
    if ((flags & kLifecycleSleep) != 0U) {
      apply_lifecycle_decision(
          state, lifecycle_.signal(LifecycleSignal::Sleep, current), false);
    }
    if ((flags & kLifecycleRestore) != 0U) {
      apply_lifecycle_decision(
          state, lifecycle_.signal(LifecycleSignal::Restore, current), true);
    }
    if ((flags & kLifecycleWake) != 0U) {
      apply_lifecycle_decision(
          state, lifecycle_.signal(LifecycleSignal::Wake, current), true);
    }
    if ((flags & kLifecycleExit) != 0U) {
      apply_lifecycle_decision(
          state, lifecycle_.signal(LifecycleSignal::Exit, current), false);
    }
  }

  void apply_lifecycle_decision(lua_State* state,
                                const LifecycleDecision& decision,
                                bool is_resume) {
    if (decision.pause_audio) {
      for(int c=0;c<32;++c) { audio_paused_before_[c]=Mix_Paused(c)!=0; if(!audio_paused_before_[c])Mix_Pause(c); }
      music_paused_before_=Mix_PausedMusic()!=0;Mix_PauseMusic();
      input_mapper_.reset();
    }
    if (decision.pause_simulation && resource_session_ != nullptr) {
      const auto suspended = resource_session_->suspend();
      if (!suspended) {
        boot_log("runtime-core: suspend rollback code=%s detail=%s",
                 resource_error_name(suspended.error().code),
                 suspended.error().message.c_str());
      } else {
        boot_log("runtime-core: suspend commit");
      }
    }
    if (decision.resume_audio && resource_session_ != nullptr) {
      const auto resumed = resource_session_->resume();
      if (!resumed) {
        boot_log("runtime-core: resume rollback code=%s detail=%s",
                 resource_error_name(resumed.error().code),
                 resumed.error().message.c_str());
      } else {
        boot_log("runtime-core: resume commit");
      }
    }
    if (decision.resume_audio) {
      for(int c=0;c<32;++c)if(!audio_paused_before_[c])Mix_Resume(c);
      if(!music_paused_before_)Mix_ResumeMusic();
      input_mapper_.reset();scheduler_.reset(now_us());last_tick_us_=now_us();
    }
    if (decision.request_autosave && asset_mode_ == "th3ds") {
      Action save;
      save.type = ActionType::QuickSave;
      save.text = "lifecycle";
      dispatch(state, save);
    }
    if (decision.pause_simulation) {
      Action action;
      action.type = ActionType::LifecycleSuspend;
      dispatch(state, action);
    } else if (is_resume) {
      Action action;
      action.type = ActionType::LifecycleResume;
      dispatch(state, action);
    }
    if (decision.request_exit) {
      Action action;
      action.type = ActionType::LifecycleExit;
      dispatch(state, action);
      if (resource_session_ != nullptr) {
        const auto closed = resource_session_->shutdown();
        if (!closed) {
          boot_log("runtime-core: lifecycle-exit rollback code=%s detail=%s",
                   resource_error_name(closed.error().code),
                   closed.error().message.c_str());
        } else {
          boot_log("runtime-core: lifecycle-exit commit ledger=baseline");
          resource_session_.reset();
        }
      }
      SDL_Event quit{};
      quit.type = SDL_QUIT;
      SDL_PushEvent(&quit);
    }
  }

  void refresh_system_status(bool refresh_battery) {
    BottomUiState copy = bottom_ui_.state();
    bool changed = false;

    if (refresh_battery && ptmu_ready_) {
      u8 level = 0U;
      u8 charging = 0U;
      if (R_SUCCEEDED(PTMU_GetBatteryLevel(&level))) {
        const int new_level = static_cast<int>(level);
        if (copy.battery_level != new_level) {
          copy.battery_level = new_level;
          changed = true;
        }
      }
      if (R_SUCCEEDED(PTMU_GetBatteryChargeState(&charging))) {
        const bool new_charging = charging != 0U;
        if (copy.charging != new_charging) {
          copy.charging = new_charging;
          changed = true;
        }
      }
    }

    u8 volume = 0U;
    if (R_SUCCEEDED(HIDUSER_GetSoundVolume(&volume))) {
      const int new_volume = static_cast<int>(volume);
      if (copy.volume_slider != new_volume) {
        copy.volume_slider = new_volume;
        changed = true;
      }
    }

    const int new_wifi = static_cast<int>(osGetWifiStrength());
    if (copy.wifi_strength != new_wifi) {
      copy.wifi_strength = new_wifi;
      changed = true;
    }

    const std::uint64_t new_free_memory = heap_snapshot().heap_available_estimate;
    if (copy.free_memory_bytes != new_free_memory) {
      copy.free_memory_bytes = new_free_memory;
      changed = true;
    }

    if (changed) {
      bottom_ui_.set_state(std::move(copy));
      dirty_ = true;
      scheduler_.request_redraw();
    }
  }

  //! Copy the 640x480 CorsixTH frame onto the 320x240 lower screen, taking
  //! every second pixel. Both surfaces are RGBA8888, so this is a straight
  //! pixel move with no format conversion.
  void mirror_game_to_bottom() {
    if (bottom_window_ == nullptr || game_window_ == nullptr) {
      return;
    }
    SDL_Surface* source = SDL_GetWindowSurface(game_window_);
    bottom_surface_ = SDL_GetWindowSurface(bottom_window_);
    if (source == nullptr || bottom_surface_ == nullptr) {
      return;
    }
    if (source->format->format != bottom_surface_->format->format ||
        source->w < ScreenLayout::kBottomWidth * 2 ||
        source->h < ScreenLayout::kBottomHeight * 2 ||
        source->pitch % 4 != 0 || bottom_surface_->pitch % 4 != 0) {
      // Keep this as an explicit fault. A silent switch to the legacy panel
      // makes a bad game-surface contract look like a successful UI change.
      boot_log("mirror: unsupported source %dx%d fmt %lu",
               source->w, source->h,
               static_cast<unsigned long>(source->format->format));
      startup_code_ = "E-MIRROR";
      startup_label_ = "UNSUPPORTED GAME SURFACE";
      render_boot_page(true);
      return;
    }

    const bool lock_source = SDL_MUSTLOCK(source) != 0;
    if (lock_source && SDL_LockSurface(source) != 0) {
      return;
    }
    const bool lock_destination = SDL_MUSTLOCK(bottom_surface_) != 0;
    if (lock_destination && SDL_LockSurface(bottom_surface_) != 0) {
      if (lock_source) {
        SDL_UnlockSurface(source);
      }
      return;
    }

    (void)halve_rgba(static_cast<const std::uint32_t*>(source->pixels), source->w,
                     source->h, source->pitch / 4,
                     static_cast<std::uint32_t*>(bottom_surface_->pixels),
                     bottom_surface_->pitch / 4);

    draw_overlay_strip();

    if (lock_destination) {
      SDL_UnlockSurface(bottom_surface_);
    }
    if (lock_source) {
      SDL_UnlockSurface(source);
    }
    (void)SDL_UpdateWindowSurface(bottom_window_);
    dirty_ = false;
  }

  //! A short status strip over the mirrored frame: the build stamp for the
  //! first few seconds after boot, and any error notice for as long as it
  //! stands. Everything else on the lower screen is the game itself.
  void draw_overlay_strip() {
    const BottomUiState& state = bottom_ui_.state();
    const bool has_error = state.notice_is_error && !state.notice.empty();
    const bool show_stamp = last_tick_us_ < overlay_until_us_;
    if (!has_error && !show_stamp) {
      return;
    }
    const std::string text = has_error ? state.notice : state.build_tag;
    if (text.empty()) {
      return;
    }
    overlay_canvas_.clear(has_error ? Rgba{176, 46, 40, 255}
                                    : Rgba{18, 25, 32, 255});
    overlay_canvas_.text(3, 3, text, Rgba{239, 242, 244, 255});

    const auto& bytes = overlay_canvas_.rgba_bytes();
    const auto* source = reinterpret_cast<const std::uint32_t*>(bytes.data());
    auto* destination = static_cast<std::uint8_t*>(bottom_surface_->pixels);
    for (int y = 0; y < kOverlayHeight; ++y) {
      auto* row = reinterpret_cast<std::uint32_t*>(
          destination + static_cast<std::ptrdiff_t>(y) * bottom_surface_->pitch);
      const auto* source_row =
          source + static_cast<std::ptrdiff_t>(y) * ScreenLayout::kBottomWidth;
      for (int x = 0; x < ScreenLayout::kBottomWidth; ++x) {
        row[x] = byte_swap32(source_row[x]);
      }
    }
  }

  void render_bottom() {
    if (bottom_window_ == nullptr) {
      return;
    }
    bottom_surface_ = SDL_GetWindowSurface(bottom_window_);
    if (bottom_surface_ == nullptr) {
      return;
    }
    if (!bottom_canvas_) {
      bottom_canvas_ = std::make_unique<SoftwareCanvas>(
          ScreenLayout::kBottomWidth, ScreenLayout::kBottomHeight);
      boot_log("runtime: legacy panel canvas allocated on demand");
    }
    render_bottom_ui(*bottom_canvas_, bottom_ui_);
    present_bottom_canvas();
  }

  bool ensure_bottom_window() {
    if (bottom_window_ != nullptr && bottom_surface_ != nullptr) {
      return true;
    }
    bottom_window_ = SDL_CreateWindow(
        "CorsixTH status", SDL_WINDOWPOS_CENTERED_DISPLAY(1),
        SDL_WINDOWPOS_CENTERED_DISPLAY(1), ScreenLayout::kBottomWidth,
        ScreenLayout::kBottomHeight, SDL_WINDOW_SHOWN | SDL_WINDOW_FULLSCREEN);
    if (bottom_window_ == nullptr) {
      boot_log("runtime: cannot create bottom screen: %s", SDL_GetError());
      return false;
    }
    bottom_window_id_ = SDL_GetWindowID(bottom_window_);
    bottom_surface_ = SDL_GetWindowSurface(bottom_window_);
    if (bottom_surface_ == nullptr) {
      boot_log("runtime: cannot get bottom framebuffer: %s", SDL_GetError());
      SDL_DestroyWindow(bottom_window_);
      bottom_window_ = nullptr;
      bottom_window_id_ = 0U;
      return false;
    }
    SDL_SetHint(SDL_HINT_TOUCH_MOUSE_EVENTS, "0");
    SDL_SetHint("CTH3DS_SCREEN_MODE", "crop");
    bottom_mode_ = BottomScreenMode::Game;
    if (std::FILE* marker = std::fopen(kPanelModeMarker, "r")) {
      std::fclose(marker);
      bottom_mode_ = BottomScreenMode::Panel;
    }
    boot_log("runtime: lower screen mode = %s",
             bottom_mode_ == BottomScreenMode::Game ? "game mirror" : "panel");
    render_boot_page(false);
    return true;
  }

  void render_boot_page(bool error) {
    if (bottom_surface_ == nullptr) {
      return;
    }
    const Rgba background = error ? Rgba{66, 20, 22, 255}
                                  : Rgba{18, 25, 32, 255};
    const Uint32 mapped = SDL_MapRGBA(bottom_surface_->format, background.r,
                                      background.g, background.b, background.a);
    (void)SDL_FillRect(bottom_surface_, nullptr, mapped);
    const HeapSnapshot memory = heap_snapshot();
    const bool must_lock = SDL_MUSTLOCK(bottom_surface_) != 0;
    if (must_lock && SDL_LockSurface(bottom_surface_) != 0) {
      return;
    }
    draw_boot_line(8, std::string("CORSIXTH 3DS ") + kOverlayVersion,
                   Rgba{239, 242, 244, 255},
                   error ? Rgba{176, 46, 40, 255} : Rgba{37, 49, 61, 255});
    draw_boot_line(56, startup_code_,
                   error ? Rgba{255, 206, 200, 255} : Rgba{233, 180, 63, 255},
                   background);
    draw_boot_line(78, startup_label_, Rgba{239, 242, 244, 255}, background);
    draw_boot_line(116, "HEAP EST " +
                            std::to_string(memory.heap_available_estimate / 1024U) +
                            " KB",
                   Rgba{164, 177, 188, 255}, background);
    draw_boot_line(136, "LUA " + std::to_string(memory.lua_bytes / 1024U) + " KB",
                   Rgba{164, 177, 188, 255}, background);
    draw_boot_line(156, "LINEAR " + std::to_string(memory.linear_free / 1024U) + " KB",
                   Rgba{164, 177, 188, 255}, background);
    draw_boot_line(204, error ? "PRESS B TO EXIT" : "LOADING - PLEASE WAIT",
                   Rgba{239, 242, 244, 255}, background);
    if (must_lock) {
      SDL_UnlockSurface(bottom_surface_);
    }
    (void)SDL_UpdateWindowSurface(bottom_window_);
  }

  void draw_boot_line(int y, const std::string& text, Rgba foreground,
                      Rgba background) {
    if (bottom_surface_->format->format != SDL_PIXELFORMAT_RGBA8888 ||
        bottom_surface_->pitch % 4 != 0 || y < 0 || y + kOverlayHeight > bottom_surface_->h) {
      return;
    }
    overlay_canvas_.clear(background);
    overlay_canvas_.text(10, 3, text, foreground);
    const auto* source = reinterpret_cast<const std::uint32_t*>(
        overlay_canvas_.rgba_bytes().data());
    auto* destination = static_cast<std::uint8_t*>(bottom_surface_->pixels);
    for (int line = 0; line < kOverlayHeight; ++line) {
      auto* row = reinterpret_cast<std::uint32_t*>(
          destination + static_cast<std::ptrdiff_t>(y + line) * bottom_surface_->pitch);
      const auto* source_row =
          source + static_cast<std::ptrdiff_t>(line) * ScreenLayout::kBottomWidth;
      for (int x = 0; x < ScreenLayout::kBottomWidth; ++x) {
        row[x] = byte_swap32(source_row[x]);
      }
    }
  }

  void present_bottom_canvas() {
    if (bottom_window_ == nullptr) {
      return;
    }
    const bool must_lock = SDL_MUSTLOCK(bottom_surface_) != 0;
    if (must_lock && SDL_LockSurface(bottom_surface_) != 0) {
      return;
    }
    int conversion = 0;
    if (bottom_surface_->format->format == SDL_PIXELFORMAT_RGBA8888 &&
        bottom_surface_->w == ScreenLayout::kBottomWidth &&
        bottom_surface_->h == ScreenLayout::kBottomHeight &&
        bottom_surface_->pitch % 4 == 0) {
      // The N3DS display mode is RGBA8888, which is our RGBA byte order with
      // the word reversed. A byte swap is a single ARM `rev` instruction per
      // pixel; SDL_ConvertPixels would run the generic per-pixel blit
      // converter over the whole 320x240 surface every repaint instead.
      const auto& bytes = bottom_canvas_->rgba_bytes();
      const auto* source = reinterpret_cast<const std::uint32_t*>(bytes.data());
      auto* destination = static_cast<std::uint8_t*>(bottom_surface_->pixels);
      for (int y = 0; y < ScreenLayout::kBottomHeight; ++y) {
        auto* row = reinterpret_cast<std::uint32_t*>(
            destination + static_cast<std::ptrdiff_t>(y) * bottom_surface_->pitch);
        const auto* source_row =
            source + static_cast<std::ptrdiff_t>(y) * ScreenLayout::kBottomWidth;
        for (int x = 0; x < ScreenLayout::kBottomWidth; ++x) {
          row[x] = byte_swap32(source_row[x]);
        }
      }
    } else {
      conversion = SDL_ConvertPixels(
          ScreenLayout::kBottomWidth, ScreenLayout::kBottomHeight,
          SDL_PIXELFORMAT_RGBA32, bottom_canvas_->rgba_bytes().data(),
          ScreenLayout::kBottomWidth * 4, bottom_surface_->format->format,
          bottom_surface_->pixels, bottom_surface_->pitch);
    }
    if (must_lock) {
      SDL_UnlockSurface(bottom_surface_);
    }
    if (conversion == 0) {
      (void)SDL_UpdateWindowSurface(bottom_window_);
      dirty_ = false;
    }
  }

  lua_State* lua_state_{nullptr};
  SDL_Window* game_window_{nullptr};
  Uint32 game_window_id_{0U};
  BottomScreenMode bottom_mode_{BottomScreenMode::Game};
  std::uint64_t overlay_until_us_{0U};
  Vec2i last_game_pointer_{320, 240};
  SDL_Window* bottom_window_{nullptr};
  SDL_Surface* bottom_surface_{nullptr};
  Uint32 bottom_window_id_{0U};
  BottomUiController bottom_ui_{};
  std::unique_ptr<SoftwareCanvas> bottom_canvas_{};
  SoftwareCanvas overlay_canvas_;
  InputMapper input_mapper_{};
  FrameScheduler scheduler_;
  LifecycleController lifecycle_;
  Telemetry telemetry_;
  aptHookCookie apt_cookie_{};
  std::atomic<std::uint32_t> pending_lifecycle_{0U};
  std::atomic<bool> exit_requested_{false};
  std::unique_ptr<RuntimeSession> resource_session_{};
  std::uint64_t last_tick_us_{0U};
  IntervalGate state_refresh_gate_{kStateRefreshUs};
  IntervalGate system_refresh_gate_{kSystemRefreshUs};
  IntervalGate battery_refresh_gate_{kBatteryRefreshUs};
  IntervalGate telemetry_log_gate_{kTelemetryLogUs};
  bool initialized_{false};
  bool ready_{false};
  std::string asset_mode_;
  std::uint64_t epoch_{0};
  bool audio_paused_before_[32]{};
  bool music_paused_before_{false};
  bool apt_hooked_{false};
  bool ptmu_ready_{false};
  bool resource_start_failed_{false};
  bool dirty_{true};
  std::string startup_code_{"S10"};
  std::string startup_label_{"NATIVE BOOTSTRAP"};
};

Runtime& runtime() {
  static Runtime instance;
  return instance;
}

BottomTab parse_tab(std::string_view value, BottomTab fallback) noexcept {
  if (value == "dashboard") return BottomTab::Dashboard;
  if (value == "build") return BottomTab::Build;
  if (value == "staff") return BottomTab::Staff;
  if (value == "patients") return BottomTab::Patients;
  if (value == "finance") return BottomTab::Finance;
  if (value == "messages") return BottomTab::Messages;
  return fallback;
}

BuildTool parse_build_tool(std::string_view value, BuildTool fallback) noexcept {
  if (value == "rooms") return BuildTool::Rooms;
  if (value == "corridor") return BuildTool::CorridorItems;
  if (value == "edit_room") return BuildTool::EditRoom;
  if (value == "hire_staff") return BuildTool::HireStaff;
  return fallback;
}

int l_initialize(lua_State* state) {
  const char* mode=luaL_checkstring(state,1);
  if(!runtime_initialize(state,mode)) {
    lua_pushboolean(state,0);lua_pushstring(state,"native initialize rejected mode/state/dependencies");return 2;
  }
  lua_pushboolean(state,1);lua_newtable(state);
  lua_pushstring(state,mode);lua_setfield(state,-2,"asset_mode");
  lua_pushboolean(state,std::strcmp(mode,"th3ds")==0);lua_setfield(state,-2,"resource_events");
  lua_pushinteger(state,static_cast<lua_Integer>(runtime().epoch()));lua_setfield(state,-2,"epoch");return 2;
}
int l_mark_ready(lua_State* state) {
  lua_getglobal(state,"TheApp");
  if(!lua_istable(state,-1))return luaL_error(state,"mark_ready requires TheApp");
  lua_getfield(state,-1,"_3ds");
  if(!lua_istable(state,-1))return luaL_error(state,"mark_ready requires completed adapter");
  lua_getfield(state,-1,"completed");bool attached=lua_toboolean(state,-1)!=0;lua_pop(state,3);
  if(!attached || !runtime().mark_ready(state))return luaL_error(state,"mark_ready rejected incomplete attachment or memory gate");
  lua_pushboolean(state,1);return 1;
}
int l_shutdown(lua_State*) {runtime().shutdown();return 0;}

int l_is_platform(lua_State* state) {
  lua_pushboolean(state, 1);
  return 1;
}

int l_version(lua_State* state) {
  lua_pushstring(state, "0.6.1");
  return 1;
}

int l_stage(lua_State* state) {
  update_lua_memory(state);
  runtime().stage(luaL_optstring(state, 1, "S??"),
                  luaL_optstring(state, 2, "STARTING"));
  return 0;
}

int l_probe(lua_State* state) {
  update_lua_memory(state);
  const char* label = luaL_optstring(state, 1, "LUA");
  const char* name=luaL_optstring(state,2,"menu");
  const MemoryGate gate=std::strcmp(name,"level")==0?MemoryGate::LevelStable:std::strcmp(name,"operation")==0?MemoryGate::Operation:MemoryGate::MenuStable;
  const bool ok = runtime().probe_regular_heap(label,gate);
  lua_pushboolean(state, ok ? 1 : 0);
  return 1;
}

int l_memory(lua_State* state) {
  update_lua_memory(state);
  const HeapSnapshot memory = heap_snapshot();
  lua_newtable(state);
  lua_pushinteger(state, static_cast<lua_Integer>(memory.heap_total));
  lua_setfield(state, -2, "env_heap_total");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.arena));
  lua_setfield(state, -2, "arena");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.uordblks));
  lua_setfield(state, -2, "uordblks");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.fordblks));
  lua_setfield(state, -2, "fordblks");
  lua_pushinteger(state,
                  static_cast<lua_Integer>(memory.heap_available_estimate));
  lua_setfield(state, -2, "heap_available_estimate");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.heap_used_estimate));
  lua_setfield(state, -2, "heap_used_estimate");
  lua_pushstring(state,
                 "allocator estimate; fragmentation, alignment and metadata can "
                 "reduce one allocation");
  lua_setfield(state, -2, "heap_available_caveat");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.linear_total));
  lua_setfield(state, -2, "linear_total");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.linear_free));
  lua_setfield(state, -2, "linear_free");
  lua_pushinteger(state,
                  static_cast<lua_Integer>(memory.heap_available_low_water));
  lua_setfield(state, -2, "heap_available_low_water");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.linear_low_water));
  lua_setfield(state, -2, "linear_low_water");
  lua_pushboolean(state, memory.low_water_valid ? 1 : 0);
  lua_setfield(state, -2, "low_water_valid");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.lua_bytes));
  lua_setfield(state, -2, "lua_current");
  lua_pushinteger(state, static_cast<lua_Integer>(memory.lua_peak_bytes));
  lua_setfield(state, -2, "lua_peak");
  lua_pushinteger(state, static_cast<lua_Integer>(boot_elapsed_ms()));
  lua_setfield(state, -2, "elapsed_ms");
  lua_pushstring(state, g_current_stage);
  lua_setfield(state, -2, "stage");
  lua_pushstring(state, g_current_stage_label);
  lua_setfield(state, -2, "stage_label");
  lua_newtable(state);
  for (std::size_t index = 0U; index < g_resource_pool_bytes.size(); ++index) {
    lua_pushinteger(state,
                    static_cast<lua_Integer>(g_resource_pool_bytes[index]));
    const std::string_view name = kResourcePoolNames[index];
    lua_setfield(state, -2, name.data());
  }
  lua_setfield(state, -2, "pools");
  lua_newtable(state);
  lua_pushinteger(state, static_cast<lua_Integer>(g_resource_cache_entries));
  lua_setfield(state, -2, "entries");
  lua_pushinteger(state, static_cast<lua_Integer>(g_resource_cache_leases));
  lua_setfield(state, -2, "leases");
  lua_pushinteger(state, static_cast<lua_Integer>(g_resource_cache_evictions));
  lua_setfield(state, -2, "evictions");
  lua_pushinteger(state, static_cast<lua_Integer>(g_resource_cache_rejects));
  lua_setfield(state, -2, "rejects");
  lua_setfield(state, -2, "cache");
  lua_newtable(state);
  for (std::size_t index = 0U; index < g_resource_bytes.size(); ++index) {
    const std::uint32_t bit = 1U << static_cast<std::uint32_t>(index);
    if ((g_resource_categories_supplied & bit) == 0U) {
      continue;
    }
    lua_pushinteger(state, static_cast<lua_Integer>(g_resource_bytes[index]));
    const std::string_view name = kResourceMemoryCategoryNames[index];
    lua_setfield(state, -2, name.data());
  }
  lua_setfield(state, -2, "diagnostic_resources");
  return 1;
}

std::uint64_t checked_non_negative_integer(lua_State* state, int index) {
  const lua_Integer value = luaL_checkinteger(state, index);
  if (value < 0) {
    (void)luaL_error(state, "byte count must be non-negative");
    return 0U;
  }
  return static_cast<std::uint64_t>(value);
}

int l_resource_memory(lua_State* state) {
  const char* category = luaL_checkstring(state, 1);
  const std::uint64_t bytes = checked_non_negative_integer(state, 2);
  const char* identity = luaL_optstring(state, 3, "-");
  record_resource_memory(category, bytes, identity);
  return 0;
}

int l_checkpoint(lua_State* state) {
  update_lua_memory(state);
  const char* checkpoint = luaL_checkstring(state, 1);
  const char* phase = luaL_optstring(state, 2, "event");
  const char* identity = luaL_optstring(state, 3, "-");
  const std::uint64_t bytes = lua_isnoneornil(state, 4)
                                  ? 0U
                                  : checked_non_negative_integer(state, 4);
  const std::uint64_t requested = lua_isnoneornil(state, 5)
                                      ? 0U
                                      : checked_non_negative_integer(state, 5);
  boot_log_checkpoint(checkpoint, phase, identity, bytes, requested);
  return 0;
}

int l_allocation_failure(lua_State* state) {
  update_lua_memory(state);
  const char* category = luaL_optstring(state, 1, "other");
  const char* identity = luaL_optstring(state, 2, "unknown");
  const std::uint64_t requested = checked_non_negative_integer(state, 3);
  const char* allocator = luaL_optstring(state, 4, "app");
  const char* detail = luaL_optstring(state, 5, "allocation returned null");
  log_allocation_failure(category, identity, requested, allocator, detail);
  return 0;
}

int l_set_state(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  BottomUiState value = runtime().state();
  value.cash = static_cast<std::int64_t>(table_integer(state, 1, "cash", value.cash));
  value.reputation = static_cast<int>(table_integer(state, 1, "reputation", value.reputation));
  value.day = static_cast<int>(table_integer(state, 1, "day", value.day));
  value.month = static_cast<int>(table_integer(state, 1, "month", value.month));
  value.year = static_cast<int>(table_integer(state, 1, "year", value.year));
  value.patient_count = static_cast<int>(table_integer(state, 1, "patient_count", value.patient_count));
  value.staff_count = static_cast<int>(table_integer(state, 1, "staff_count", value.staff_count));
  value.queue_count = static_cast<int>(table_integer(state, 1, "queue_count", value.queue_count));
  value.message_count = static_cast<int>(table_integer(state, 1, "message_count", value.message_count));
  value.game_speed = static_cast<int>(table_integer(state, 1, "game_speed", value.game_speed));
  value.paused = table_boolean(state, 1, "paused", value.paused);
  value.selected_name = table_string(state, 1, "selected_name", value.selected_name);
  value.selected_status = table_string(state, 1, "selected_status", value.selected_status);
  value.input_context = parse_context(table_string(state, 1, "input_context", context_name(value.input_context).data()));
  value.active_tab = parse_tab(table_string(state, 1, "active_tab", bottom_tab_name(value.active_tab).data()), value.active_tab);
  value.build_tool = parse_build_tool(table_string(state, 1, "build_tool", "rooms"), value.build_tool);
  runtime().set_state(std::move(value));
  return 0;
}

int l_request_redraw(lua_State*) {
  runtime().request_redraw();
  return 0;
}

int l_atomic_commit(lua_State* state) {
  const char* temporary = luaL_checkstring(state, 1);
  const char* final_path = luaL_checkstring(state, 2);
  const bool keep_backup = lua_isnoneornil(state, 3) || lua_toboolean(state, 3) != 0;
  const AtomicSaveResult result = atomic_commit_existing(temporary, final_path, keep_backup);
  lua_pushboolean(state, result.ok ? 1 : 0);
  if (result.ok) {
    lua_pushnil(state);
  } else {
    lua_pushlstring(state, result.error.data(), result.error.size());
  }
  return 2;
}

int l_recover_atomic(lua_State* state) {
  const char* final_path = luaL_checkstring(state, 1);
  const AtomicSaveResult result = recover_atomic_file(final_path);
  lua_pushboolean(state, result.ok ? 1 : 0);
  if (result.ok) {
    lua_pushnil(state);
  } else {
    lua_pushlstring(state, result.error.data(), result.error.size());
  }
  return 2;
}

int l_begin_critical_io(lua_State*) {
  runtime().begin_critical_io();
  return 0;
}

int l_end_critical_io(lua_State*) {
  runtime().end_critical_io();
  return 0;
}

int l_resource_event(lua_State* state) {
  const char* event = luaL_checkstring(state, 1);
  const char* identity = luaL_optstring(state, 2, "-");
  const bool success = lua_isnoneornil(state, 3) ||
                       lua_toboolean(state, 3) != 0;
  const auto result = runtime().resource_event(event != nullptr ? event : "",
                                               identity != nullptr ? identity : "-",
                                               success);
  lua_pushboolean(state, result ? 1 : 0);
  if (result) {
    lua_pushnil(state);
  } else {
    lua_pushlstring(state, result.error().message.data(),
                    result.error().message.size());
  }
  return 2;
}

int l_set_notice(lua_State* state) {
  const char* text = luaL_optstring(state, 1, "");
  const bool is_error = lua_toboolean(state, 2) != 0;
  runtime().set_notice(text != nullptr ? text : "", is_error);
  return 0;
}

int l_performance(lua_State* state) {
  const PerformanceSnapshot snapshot = runtime().performance();
  lua_newtable(state);
  lua_pushnumber(state, snapshot.average_frame_ms);
  lua_setfield(state, -2, "average_frame_ms");
  lua_pushnumber(state, snapshot.p95_frame_ms);
  lua_setfield(state, -2, "p95_frame_ms");
  lua_pushnumber(state, snapshot.maximum_frame_ms);
  lua_setfield(state, -2, "maximum_frame_ms");
  lua_pushinteger(state, static_cast<lua_Integer>(snapshot.dropped_frames));
  lua_setfield(state, -2, "dropped_frames");
  return 1;
}

void set_function(lua_State* state, const char* name, lua_CFunction function) {
  lua_pushcfunction(state, function);
  lua_setfield(state, -2, name);
}

}  // namespace

int luaopen_th3ds(lua_State* state) {
  lua_newtable(state);
  set_function(state, "is_platform", l_is_platform);
  set_function(state, "initialize", l_initialize);
  set_function(state, "mark_ready", l_mark_ready);
  set_function(state, "adapter_module", ensure_adapter);
  set_function(state, "shutdown", l_shutdown);
  set_function(state, "version", l_version);
  set_function(state, "stage", l_stage);
  set_function(state, "memory", l_memory);
  set_function(state, "probe_regular_heap", l_probe);
  set_function(state, "resource_memory", l_resource_memory);
  set_function(state, "checkpoint", l_checkpoint);
  set_function(state, "allocation_failure", l_allocation_failure);
  set_function(state, "set_state", l_set_state);
  set_function(state, "request_redraw", l_request_redraw);
  set_function(state, "atomic_commit", l_atomic_commit);
  set_function(state, "recover_atomic", l_recover_atomic);
  set_function(state, "begin_critical_io", l_begin_critical_io);
  set_function(state, "end_critical_io", l_end_critical_io);
  set_function(state, "resource_event", l_resource_event);
  set_function(state, "set_notice", l_set_notice);
  set_function(state, "performance", l_performance);
  return 1;
}

void register_lua_module(lua_State* state) {
  boot_log_open();
  initialize_heap_watermarks();
  g_adapter_crc = crc32(kEmbeddedPlatformLua, std::strlen(kEmbeddedPlatformLua));
  boot_log("CorsixTH 3DS overlay %s, embedded adapter crc %08lx",
           kOverlayVersion, static_cast<unsigned long>(g_adapter_crc));
  boot_log("allocator: explicit linear heap = %lu bytes",
           static_cast<unsigned long>(__ctru_linear_heap_size));
  boot_log(
      "allocator caveat: heap_available_estimate=min(env_heap_total, "
      "max(env_heap_total-arena,0)+fordblks); it is not a largest-allocation "
      "guarantee");
  boot_log_memory("S10");
  const int base = lua_gettop(state);
  lua_getglobal(state, "package");
  if (!lua_istable(state, -1)) {
    lua_settop(state, base);
    return;
  }
  lua_getfield(state, -1, "preload");
  if (!lua_istable(state, -1)) {
    lua_settop(state, base);
    return;
  }
  const auto preload = [state](const char* name, lua_CFunction open_function) {
    lua_pushcfunction(state, open_function);
    lua_setfield(state, -2, name);
  };
  preload("th3ds", luaopen_th3ds);
  preload("lfs", luaopen_lfs);
  preload("lpeg", luaopen_lpeg);
  lua_settop(state, base);
  runtime().stage("S10", "NATIVE BOOTSTRAP");
}

void report_fatal(const char* reason) noexcept {
  const char* text = reason != nullptr ? reason : "unknown fatal error";
  boot_log("FATAL: %s", text);
  boot_log_memory("FATAL");
  runtime().show_fatal(text);
  // Give the player time to read the lower screen before the process leaves.
  for (int i = 0; i < 600 && aptMainLoop(); ++i) {
    hidScanInput();
    if ((hidKeysDown() & (KEY_B | KEY_START)) != 0U) {
      break;
    }
    gspWaitForVBlank();
  }
  boot_log_close();
}

void report_resource_memory(const char* category, std::uint64_t bytes,
                            const char* identity) noexcept {
  record_resource_memory(category, bytes, identity);
}

void report_memory_checkpoint(const char* checkpoint, const char* phase,
                              const char* identity, std::uint64_t bytes,
                              std::uint64_t requested_bytes) noexcept {
  boot_log_checkpoint(checkpoint, phase, identity, bytes, requested_bytes);
}

void report_allocation_failure(const char* category, const char* identity,
                               std::uint64_t requested_bytes,
                               const char* allocator,
                               const char* detail) noexcept {
  log_allocation_failure(category, identity, requested_bytes, allocator, detail);
}

std::shared_ptr<ResourceTelemetrySink>
make_runtime_resource_telemetry_sink() {
  return std::make_shared<RuntimeResourceTelemetry>();
}

std::shared_ptr<ResourceBudgetGate> make_runtime_resource_budget_gate() {
  return std::make_shared<RuntimeResourceBudgetGate>();
}

void runtime_set_game_window(SDL_Window* window) noexcept {
  runtime().set_game_window(window);
}

void runtime_after_frame() noexcept { runtime().after_frame(); }

[[gnu::noinline]] bool runtime_initialize(lua_State* state, const char* mode) { return runtime().initialize(state,mode); }
[[gnu::noinline]] bool runtime_assert_ready(lua_State* state) {return runtime().assert_ready(state);}
bool runtime_audio_reserve(std::size_t bytes,const char* identity) noexcept {
  const auto h=heap_snapshot();const auto policy=memory_gate_policy(MemoryGate::Operation);
  if(!evaluate_memory_gate(h.heap_total,h.heap_available_estimate,h.linear_total,policy).pass() || bytes>h.heap_available_estimate || policy.probe_reserve_bytes>h.heap_available_estimate-bytes) {
    report_allocation_failure("sound",identity,bytes,"regular","operation reserve gate");return false;
  }
  void* probe=std::malloc(bytes);if(!probe){report_allocation_failure("sound",identity,bytes,"regular","contiguous preflight");return false;}
  std::free(probe);return true;
}
void runtime_tick(lua_State* state) { runtime().tick(state); }
void runtime_shutdown(lua_State*) noexcept { runtime().shutdown(); }
bool runtime_consume_sdl_event(const SDL_Event& event) noexcept {
  return runtime().consumes_event(event);
}

}  // namespace cth3ds
