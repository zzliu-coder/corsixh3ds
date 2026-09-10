// newlib hides the BSD FILE callback API in strict C++17 unless requested
// before any system header. Keep the feature opt-in local to this 3DS TU.
#if defined(__3DS__) && !defined(CTH3DS_STUB_BUILD) && !defined(_DEFAULT_SOURCE)
#define _DEFAULT_SOURCE 1
#endif
#include "runtime_3ds.hpp"
#include "runtime/game_view.hpp"
#include "runtime/observation.hpp"

#include <3ds.h>
#include <SDL.h>
#include <SDL_mixer.h>

#include <atomic>
#include <algorithm>
#include <array>
#include <cstdarg>
#include <cmath>
#include <stdexcept>
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
#include "cth3ds/boot_presentation.hpp"
#include "cth3ds/notice_hints.hpp"
#include "cth3ds/bounded_log.hpp"
#include "cth3ds/crc32.hpp"
#include "cth3ds/events.hpp"
#include "cth3ds/panel_refresh.hpp"
#include "cth3ds/simulation_clock.hpp"
#include "cth3ds/presentation_clock.hpp"
#include "cth3ds/cpu_work.hpp"
#include "cth3ds/allocation_watch.hpp"
#include "cth3ds/memory_pressure.hpp"
#include "cth3ds/text_cache.hpp"
#include "cth3ds/gpu_api.hpp"
#include "cth3ds/framebuffer_scaler.hpp"
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/input_collector_3ds.hpp"
#include "cth3ds/render_work.hpp"
#include "cth3ds/interval_gate.hpp"
#include "cth3ds/lifecycle.hpp"
#include "cth3ds/memory_telemetry.hpp"
#if CTH3DS_RESOURCE_EXPERIMENT
#include "cth3ds/resource_manager.hpp"
#include "cth3ds/runtime_session.hpp"
#endif
#include "cth3ds/screen_layout.hpp"
#include "cth3ds/software_canvas.hpp"
#include "cth3ds/telemetry.hpp"
#include "embedded_platform_lua.hpp"

extern "C" int luaopen_lfs(lua_State* state);
extern "C" int luaopen_lpeg(lua_State* state);
#ifndef CTH3DS_STUB_BUILD
// Generated game binding; invoked on the main thread, never in an APT hook.
void cth3ds_suspend_sound_callbacks(bool suspend, Uint32 now);
#endif

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
constexpr std::uint64_t kTelemetryLogUs = 10000000U;

constexpr const char* kOverlayVersion = "0.6.1";
constexpr const char* kLogPath = "sdmc:/3ds/corsixth/boot.log";
#if CTH3DS_RESOURCE_EXPERIMENT
constexpr const char* kResourceBundlePath =
    "sdmc:/3ds/corsixth/resources/bundle.th3ds.json";
#endif
constexpr const char* kAdapterModule = "3ds.platform";

#if CTH3DS_RESOURCE_EXPERIMENT
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

#endif
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
lua_State* g_observation_state = nullptr;
bool g_top_present_seen = false;
bool g_top_present_ok = false;
RuntimeObservations g_observations;
BoundedLog g_log;
#if defined(__3DS__) && !defined(CTH3DS_STUB_BUILD)
std::FILE* g_saved_stderr = nullptr;
std::FILE* g_stderr_sink = nullptr;
#endif
std::uint64_t g_log_time_us = 0, g_workload_time_us = 0;
// Snapshot of App.ui's authoritative pointer, refreshed at each input boundary.
// The upstream renderer cursor fields are legacy zeros on the 3DS path.
int g_input_cursor_x = 0, g_input_cursor_y = 0;
SimulationClock g_simulation_clock;
PresentationClock g_presentation_clock;
bool g_benchmark_active=false;
bool g_operation_blocked = false;
void reset_benchmark_activation() noexcept {g_benchmark_active=false;}
std::uint64_t g_input_owner_epoch = 0;
std::uint64_t now_us() noexcept;
bool g_log_attempted = false;
u64 g_boot_started_ms = 0U;
bool g_heap_watermarks_initialized = false;
std::uint64_t g_min_heap_available = 0U;
std::uint64_t g_min_linear_free = std::numeric_limits<std::uint64_t>::max();
bool g_linear_watermark_valid = false;
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
  bool linear_low_valid{false};
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
    // linearSpaceFree can be zero before the lazily initialized allocator.
    // After the first valid sample, a real zero remains a valid low-water mark.
    if (result.linear_free > 0 || g_linear_watermark_valid) {
      g_min_linear_free = std::min(g_min_linear_free, result.linear_free);
      g_linear_watermark_valid = true;
    }
  }
  result.low_water_valid = g_heap_watermarks_initialized;
  result.linear_low_valid = g_linear_watermark_valid;
  if (result.low_water_valid) {
    result.heap_available_low_water = g_min_heap_available;
    result.linear_low_water = g_linear_watermark_valid ? g_min_linear_free : 0;
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
  if (initial.linear_free > 0) { g_min_linear_free = initial.linear_free; g_linear_watermark_valid = true; }
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

void boot_log(const char* format, ...);
MemoryPressure g_memory_pressure;
void recover_main_thread_memory(lua_State* state) noexcept {
  const auto now=now_us();
  if(!state || !g_memory_pressure.due(now))return;
  const auto before=heap_snapshot();
  if(!g_memory_pressure.begin(now,before.heap_available_estimate,
      lua_gc(state,LUA_GCISRUNNING,0)!=0))return;
  // Safe loop point: no sound decoding, mixer lock, allocator hook or suspended
  // save writer can enter here. A finalizer error is contained by lua_pcall.
  bool ok=false;
  if(lua_checkstack(state,2)) {
    lua_pushcfunction(state,[](lua_State* L)->int {
      // At this safe point Lua owns the optional raw-picture warm references.
      // Release those before collection; live windows retain their own images.
      // This entire lookup/call remains within the existing protected boundary.
      lua_getglobal(L,"TheApp");
      if(lua_istable(L,-1)) {
        lua_getfield(L,-1,"gfx");
        if(lua_istable(L,-1)) {
          lua_getfield(L,-1,"trimRawWarm");
          if(lua_isfunction(L,-1)) {lua_pushvalue(L,-2);lua_call(L,1,0);}
        }
      }
      lua_settop(L,0);
      lua_gc(L,LUA_GCCOLLECT,0);return 0;
    });
    const auto token=runtime_span_begin(TimingStage::GC);
    ok=lua_pcall(state,0,0,0)==LUA_OK;
    if(!ok){const char* error=lua_tostring(state,-1);boot_log("memory-pressure: gc_error=%.160s",error?error:"non-string finalizer error");lua_pop(state,1);}
    runtime_span_end(token,ok);
  }
  g_memory_pressure.collecting=false;
  update_lua_memory(state);
  const auto after=heap_snapshot();
  boot_log("memory-pressure: before=%llu after=%llu elapsed_us=%llu collected=%d main_thread=1",
    (unsigned long long)before.heap_available_estimate,
    (unsigned long long)after.heap_available_estimate,
    (unsigned long long)(now_us()-now),ok);
}

void boot_log_open() {
  if (g_log_attempted) {
    return;
  }
  g_log_attempted = true;
  g_log.set_clock(now_us);
  g_boot_started_ms = osGetTime();
  if(runner_active()){
    const auto dir=runner_directory()+"/artifacts/";
    if(!g_log.open((dir+"boot.log").c_str(),(dir+"boot.previous.log").c_str(),
                   (dir+"boot.older.log").c_str()))return;
  }else
  if (!g_log.open(kLogPath, "sdmc:/3ds/corsixth/boot.previous.log",
                  "sdmc:/3ds/corsixth/boot.older.log")) return;
#if defined(__3DS__) && !defined(CTH3DS_STUB_BUILD)
  // libctru/newlib FILE adapter funnels upstream stderr into the same bounded
  // sink. A separate append descriptor would bypass the cap and write owner.
  g_stderr_sink = funopen(nullptr, nullptr,
    [](void*, const char* data, std::size_t count) -> int {
      const auto accepted = std::min(count, static_cast<std::size_t>(std::numeric_limits<int>::max()));
      if (accepted > 0) g_log.write(data, accepted);
      return static_cast<int>(accepted);
    }, nullptr, nullptr);
  if (g_stderr_sink) {
    std::setvbuf(g_stderr_sink, nullptr, _IONBF, 0);
    g_saved_stderr = stderr; stderr = g_stderr_sink;
  }
#endif
}

void boot_log(const char* format, ...) {
  if (!g_log.available()) return;
  const auto started = now_us();
  std::va_list arguments;
  va_start(arguments, format);
  g_log.vline(format, arguments);
  va_end(arguments);
  g_log_time_us += now_us() - started;
}

void boot_log_flush() noexcept {
  const auto started = now_us();
  g_log.flush();
  g_log_time_us += now_us() - started;
}

void seal_observation_tail(const char* event) noexcept {
  const ObservationOutput output{boot_log,boot_log_flush,[](){}};
  g_observations.seal_tail(now_us(),output,event);
}

void boot_log_close() {
#if defined(__3DS__) && !defined(CTH3DS_STUB_BUILD)
  if (g_stderr_sink) {
    stderr = g_saved_stderr; std::fclose(g_stderr_sink);
    g_stderr_sink = g_saved_stderr = nullptr;
  }
#endif
  g_log.close();
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
      "low_water_valid=%s linear_low_valid=%s lua_current=%llu lua_peak=%llu",
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
      memory.linear_low_valid ? "yes" : "no",
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
  boot_log_flush();
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

#if CTH3DS_RESOURCE_EXPERIMENT
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

#endif
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

// Runs while the failed Lua frames still exist. Preserve non-string error
// object identity; retain its stack in the log rather than replacing it.
int preserve_lua_error(lua_State* state) {
  const bool string_error=lua_type(state,1)==LUA_TSTRING;
  const char* message=string_error?lua_tostring(state,1):"non-string Lua error";
  luaL_traceback(state,state,message,1);
  if(!string_error) {
    boot_log("lua-error-stack: %s",lua_tostring(state,-1));
    lua_pushvalue(state,1);
  }
  return 1;
}

struct AdapterCall {
  const char* method{nullptr};
  const Action* action{nullptr};
  InputContext* context{nullptr};
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
  lua_call(state, argument_count, 2);
  if (request->context) {
    if (!lua_istable(state,-2)) return luaL_error(state,"inputState must return a table");
    for (const char* field : {"cursor_x","cursor_y"}) {
      lua_getfield(state,-2,field);
      const auto value = lua_tonumber(state,-1);
      const bool valid=lua_type(state,-1)==LUA_TNUMBER && std::isfinite(value) &&
        value == std::floor(value) && value >= 0 && value <= (field[7] == 'x' ? 639 : 479);
      lua_pop(state,1);
      if(!valid)return luaL_error(state,"inputState invalid cursor: %s",field);
      if (field[7] == 'x') g_input_cursor_x = static_cast<int>(value);
      else g_input_cursor_y = static_cast<int>(value);
    }
    lua_getfield(state,-2,"input_context");
    if(lua_type(state,-1)!=LUA_TSTRING)return luaL_error(state,"inputState context must be a string");
    const char* name=lua_tostring(state,-1);
    if(!std::strcmp(name,"world"))*request->context=InputContext::World;
    else if(!std::strcmp(name,"build_room"))*request->context=InputContext::BuildRoom;
    else if(!std::strcmp(name,"place_object"))*request->context=InputContext::PlaceObject;
    else if(!std::strcmp(name,"menu"))*request->context=InputContext::Menu;
    else if(!std::strcmp(name,"dialog"))*request->context=InputContext::Dialog;
    else if(!std::strcmp(name,"text_input"))*request->context=InputContext::TextInput;
    else return luaL_error(state,"inputState unknown context: %s",name);
    lua_pop(state, 1);
    g_input_owner_epoch = static_cast<std::uint64_t>(table_integer(state, -2, "input_epoch", 0));
  } else if (!std::strcmp(request->method,"handleAction")) {
    if(!lua_isboolean(state,-2)||!lua_toboolean(state,-2))
      return luaL_error(state,"%s rejected: %s",request->method,lua_tostring(state,-1)?lua_tostring(state,-1):"expected true");
    // true means handled, not necessarily that game state changed. No-op and
    // unsupported are successful transport outcomes and never abort a batch.
    std::size_t length=0;
    const char* outcome=lua_type(state,-1)==LUA_TSTRING?lua_tolstring(state,-1,&length):nullptr;
    const bool valid=outcome && length<=96 &&
      ((length==7 && !std::memcmp(outcome,"applied",7)) ||
       (length>5 && !std::memcmp(outcome,"noop:",5)) ||
       (length>12 && !std::memcmp(outcome,"unsupported:",12)));
    if(!valid)return luaL_error(state,"handleAction invalid outcome contract");
  } else if (!std::strcmp(request->method,"handlePointer") || !std::strcmp(request->method,"cancelPointer") || !std::strcmp(request->method,"prepareInput") || !std::strcmp(request->method,"samplePerformanceContext")) {
    if(!lua_isboolean(state,-2)||!lua_toboolean(state,-2))
      return luaL_error(state,"%s rejected: %s",request->method,lua_tostring(state,-1)?lua_tostring(state,-1):"expected true");
  }
  return 0;
}

bool call_platform_method(lua_State* state, const char* method,
                          const Action* action = nullptr,
                          std::string* error = nullptr, InputContext* context = nullptr) {
  CpuWorkScope profile(context ? CpuWork::InputState : CpuWork::InputAction);
  // Only the actual benchmark callback gets this nested residency label.
  // Ordinary actions keep their caller's phase without an extra clock read.
  const bool benchmark_call=!std::strcmp(method,"benchmarkTick") || !std::strcmp(method,"benchmarkCancel");
  struct PhaseRestore {
    bool enabled;
    FrameTail::Token token;
    ~PhaseRestore(){if(enabled)runtime_phase_end(token);}
  } phase_restore{benchmark_call,benchmark_call?runtime_phase_begin(FramePhase::Benchmark):FrameTail::Token{}};
  const auto began = now_us();
  const int base = lua_gettop(state);
  AdapterCall request{method, action, context};
  lua_pushcfunction(state, preserve_lua_error);
  lua_pushcfunction(state, l_protected_adapter_call);
  lua_pushlightuserdata(state, &request);
  if (lua_pcall(state, 1, 0, base + 1) != LUA_OK) {
    const char* message = lua_type(state, -1) == LUA_TSTRING ? lua_tostring(state, -1) : nullptr;
    const std::string detail = message != nullptr ? message :
      std::string("non-string Lua error (") + luaL_typename(state,-1) + ")";
    if (error != nullptr) {
      *error = detail;
    }
    boot_log("adapter call %s failed: %s", method, detail.c_str());
    g_observations.slow.record(began, now_us(), "input", method, false);
    lua_settop(state, base);
    return false;
  }
  lua_settop(state, base);
  g_observations.slow.record(began, now_us(), "input", method);
  return true;
}

// Select code before App mutation. Attachment has one Lua owner after menu.
int load_embedded_operations(lua_State* state) {
  if(luaL_loadbuffer(state,kEmbeddedOperationsLua,std::strlen(kEmbeddedOperationsLua),"@builtin/3ds/operations.lua")!=LUA_OK)return lua_error(state);
  lua_call(state,0,1);
  return 1;
}
int load_embedded_media(lua_State* state) {
  if(luaL_loadbuffer(state,kEmbeddedMediaLua,std::strlen(kEmbeddedMediaLua),"@builtin/3ds/media.lua")!=LUA_OK)return lua_error(state);
  lua_call(state,0,1);
  return 1;
}
int ensure_adapter(lua_State* state) {
  boot_log_checkpoint("adapter_attach", "begin");
  lua_getglobal(state,"require");lua_pushstring(state,kAdapterModule);
  if(lua_pcall(state,1,1,0)!=LUA_OK) {
    lua_pop(state,1);
    lua_getglobal(state,"package");
    lua_getfield(state,-1,"preload");
    lua_pushcfunction(state,load_embedded_operations);lua_setfield(state,-2,"3ds.operations");
    lua_pushcfunction(state,load_embedded_media);lua_setfield(state,-2,"3ds.media");lua_pop(state,1);
    lua_getfield(state,-1,"loaded");lua_pushnil(state);lua_setfield(state,-2,"3ds.operations");
    lua_pushnil(state);lua_setfield(state,-2,"3ds.media");lua_pop(state,2);
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
        panel_refresh_(33333U), lifecycle_(60000000U) {}

  bool initialize(lua_State* state, const char* mode) {
    // Reject unsupported resources before acquiring a window, Lua owner or epoch.
#if CTH3DS_RESOURCE_EXPERIMENT
    if (!mode || (std::strcmp(mode,"loose") && std::strcmp(mode,"th3ds"))) return false;
#else
    if (!mode || std::strcmp(mode, "loose")) return false;
#endif
    if (initialized_) return state == lua_state_ && asset_mode_ == mode;
    if (lua_state_ && lua_state_ != state) return false;
    lua_state_ = state;
    asset_mode_ = mode;
    ++epoch_;
    reset_benchmark_activation();
    stage("S90", "STARTING RUNTIME");
    if (!ensure_bottom_window()) {
      return false;
    }

#if CTH3DS_RESOURCE_EXPERIMENT
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

#endif
    const Result ptmu_result = ptmuInit();
    ptmu_ready_ = R_SUCCEEDED(ptmu_result);
    aptHook(&apt_cookie_, &Runtime::apt_callback, this);
    apt_hooked_ = true;
    aptSetSleepAllowed(true);

    const std::uint64_t current = now_us();
    lifecycle_.set_autosave_enabled(asset_mode_ == "th3ds");
    lifecycle_.reset(current);
    lifecycle_audio_suspended_ = false;
#ifndef CTH3DS_STUB_BUILD
    cth3ds_suspend_sound_callbacks(false, SDL_GetTicks());
#endif
    last_tick_us_ = current;
    state_refresh_gate_.reset(current, true);
    system_refresh_gate_.reset(current, true);
    battery_refresh_gate_.reset(current, true);
    telemetry_log_gate_.reset(current, false);
    panel_refresh_.reset();
    initialized_ = true;
    dirty_ = true;
    refresh_system_status(true);

    boot_log("runtime: lower screen ready (%dx%d)",
             ScreenLayout::kBottomWidth, ScreenLayout::kBottomHeight);
    boot_log_memory("S90");
    {
      const char* renderer="software";
#ifdef CORSIXTH_3DS_GPU
      if(gpu_active())renderer="citro2d-ordered-canvas";
#endif
      boot_log("present: logical=640x480 top=400x240 native-crop bottom=320x240 half renderer=%s gpu_utilization=unknown cpu_utilization=unknown",renderer);
    }

    boot_log("runtime: dependencies initialized mode=%s epoch=%llu",asset_mode_.c_str(),static_cast<unsigned long long>(epoch_));
    return true;
  }

  bool mark_ready(lua_State* state) {
    if (!initialized_ || state!=lua_state_) return false;
    if (ready_) return true;
    if (!probe_regular_heap("MAIN MENU",MemoryGate::MenuStable)) return false;
    if (!input_collector_.start(now_us)) {
      boot_log("input: sampler start failed"); return false;
    }
    input_collector_.discard();
    ready_=true;boot_log_checkpoint("adapter_attach", "ready", "lua-owner");stage("S100", "READY");
    boot_log("input: sampler=hid-shared-memory period_us=8000 capacity=256 controls=overview-r48");
    return true;
  }
  bool assert_ready(lua_State* state) const {return initialized_&&ready_&&!input_failed_&&state==lua_state_;}
  std::uint64_t epoch() const {return epoch_;}

  void shutdown() noexcept {
    seal_observation_tail("SHUTDOWN");
    reset_benchmark_activation();
#ifdef CORSIXTH_3DS_GPU
    gpu_quiesce();
#endif
    if (!initialized_ && !lua_state_ && !bottom_window_) return;
    boot_log("runtime: shutdown requested");
    if (!input_collector_.stop()) boot_log("input: sampler join failed; retained until process exit");
    // Silence the mixer before Lua tears down its channels; a still-running
    // NDSP callback against freed chunks is a classic 3DS exit hang.
    Mix_HaltMusic();
    Mix_HaltChannel(-1);
#if CTH3DS_RESOURCE_EXPERIMENT
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
#endif
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
    input_mapper_.reset();input_failed_=false;
    initialized_ = false; ready_ = false;
    presentation_.reset();
    lua_state_ = nullptr;
    game_window_=nullptr;game_window_id_=0;game_surface_=nullptr;
#if CTH3DS_RESOURCE_EXPERIMENT
    resource_start_failed_=false;resource_session_.reset();
#endif
    pending_lifecycle_.store(0);exit_requested_.store(false);
    lifecycle_.reset(0);last_tick_us_=0;panel_refresh_.reset();
    g_adapter_origin.clear();asset_mode_.clear();
    boot_log("runtime: shutdown complete");
    boot_log_close();
  }

  void tick(lua_State* state) {
    if (!assert_ready(state)) return;
    process_lifecycle(state, now_us());
    const std::uint64_t frame_started = now_us();
    const float delta_seconds = last_tick_us_ == 0U
                                    ? 0.0F
                                    : static_cast<float>(frame_started - last_tick_us_) /
                                          1000000.0F;
    last_tick_us_ = frame_started;

    if(input_failed_ || lifecycle_.state()!=LifecycleState::Running)return;
    recover_main_thread_memory(state);
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

    // Host seam / legacy panel. Production game mode uses the independent
    // bounded HID queue below, including edges received during a slow draw.
    // SDL's N3DS event pump already called hidScanInput() before the
    // timer/event reached CorsixTH. Scanning again here would erase the
    // one-frame keysDown/keysUp transitions.
    RawInputSnapshot snapshot;
    snapshot.timestamp_us = frame_started;
    snapshot.down = convert_keys(hidKeysDown());
    const u32 raw_held = hidKeysHeld();
    snapshot.held = convert_keys(raw_held);
    snapshot.up = convert_keys(hidKeysUp());

    circlePosition circle{};
    hidCircleRead(&circle);
    snapshot.circle_x = circle.dx;
    snapshot.circle_y = circle.dy;

    snapshot.touching = (raw_held & KEY_TOUCH) != 0U;
    if (snapshot.touching) {
      touchPosition touch{};
      hidTouchRead(&touch);
      snapshot.touch = {static_cast<int>(touch.px), static_cast<int>(touch.py)};
    }

    if(g_benchmark_active){
      std::string benchmark_error;
      bool interrupted=benchmark_user_input(snapshot);
      RawInputSnapshot queued;
      for(std::size_t i=0;i<InputQueue::capacity && input_collector_.pop(queued,frame_started);++i)
        interrupted=benchmark_user_input(queued)||interrupted;
      const char* method=interrupted?"benchmarkCancel":"benchmarkTick";
      if(!call_platform_method(state,method,nullptr,&benchmark_error)){
        g_benchmark_active=false;report_fatal(benchmark_error.c_str());input_failed_=true;return;
      }
      input_collector_.discard();
      if(interrupted)return; // Cancelling input never doubles as a game click.
    }
    if (g_benchmark_active) {
      // Benchmark runs have no user input. Input cancels above; lifecycle stays
      // active below. The stylus never gets synthetic mouse commands.
    } else if (bottom_mode_ == BottomScreenMode::Game) {
#ifdef CTH3DS_STUB_BUILD
      input_collector_.push_for_host(snapshot);
#endif
      std::string error;
      InputContext last_context = InputContext::World;
      try {
        if (input_collector_.take_cancellation()) cancel_input(state);
        if (!call_platform_method(state,"prepareInput",nullptr,&error)) throw std::runtime_error(error);
        InputRefreshGate input_state;
        auto refresh_input = [&] {
          input_state.refresh([&] {
            if(!call_platform_method(state,"inputState",nullptr,&error,&last_context))throw std::runtime_error(error);
            set_view_context(last_context);
          });
        };
        for (unsigned drained = 0; drained < 64 && input_collector_.pop(snapshot, now_us()); ++drained) {
        if (input_collector_.take_cancellation()) {
          input_collector_.discard(); cancel_input(state); break;
        }
        if (now_us() > snapshot.timestamp_us + 2000000U) {
          input_collector_.discard(); cancel_input(state);
          set_hint("input_reset"); break;
        }
        refresh_input();
        const auto owner_epoch = g_input_owner_epoch;
        set_view_context(last_context);
        const auto edges = snapshot.held ^ traced_held_;
        if (edges & (button_mask(Button::L) | button_mask(Button::Select))) {
          boot_log("control-edge: at_us=%llu sample_us=%llu held=%lu changed=%lu context=%u cursor=%d,%d",
            (unsigned long long)now_us(),(unsigned long long)snapshot.timestamp_us,
            (unsigned long)snapshot.held,(unsigned long)edges,(unsigned)last_context,
            g_input_cursor_x,g_input_cursor_y);
        }
        traced_held_ = snapshot.held;
        const float sample_delta = last_input_us_ && snapshot.timestamp_us >= last_input_us_ ?
          static_cast<float>(snapshot.timestamp_us - last_input_us_) / 1000000.0F : 0.008F;
        last_input_us_ = snapshot.timestamp_us;
        const bool accepted=input_mapper_.dispatch_mixed(snapshot,std::min(sample_delta,0.1F),
          [&] { refresh_input(); return last_context; },
          [&](const Action& action){
            bool ok = true;
            if (action.type == ActionType::MoveViewport) {
              const auto residual = move_view(action.vector);
              if (residual.x != 0 || residual.y != 0) {
                Action pan; pan.type = ActionType::PanCamera; pan.vector = residual;
                input_state.invalidate();
                ok = call_platform_method(state,"handleAction",&pan,&error);
              }
            }
            else if (action.type == ActionType::ToggleView) {
              toggle_view();
              boot_log("view-toggle: context=%u source=%dx%d origin=%d,%d cursor=%d,%d",
                (unsigned)view_.context(),view_.bounds().w,view_.bounds().h,view_.bounds().x,view_.bounds().y,
                g_input_cursor_x,g_input_cursor_y);
              trace_next_present_ = true;
            }
            else if (activation_needs_focus(action)) {
              focus_view(g_input_cursor_x, g_input_cursor_y);
              set_hint("target");
            } else {
              input_state.invalidate();
              ok = call_platform_method(state,"handleAction",&action,&error);
            }
            if (!ok) {
              g_log.emergency();
              const auto name = action_name(action.type);
              boot_log("input-failed: action=%.*s context=%u x=%d y=%d dx=%.6f dy=%.6f held=%lu circle_x=%d circle_y=%d cursor_x=%d cursor_y=%d",
                static_cast<int>(name.size()),name.data(),static_cast<unsigned>(last_context),
                action.position.x,action.position.y,static_cast<double>(action.vector.x),static_cast<double>(action.vector.y),
                static_cast<unsigned long>(snapshot.held),snapshot.circle_x,snapshot.circle_y,g_input_cursor_x,g_input_cursor_y);
            }
            return ok;
          });
        if(!accepted)throw std::runtime_error(error.empty()?"input batch rejected":error);
        refresh_input();
        set_view_context(last_context);
        if (input_collector_.take_cancellation() || owner_epoch != g_input_owner_epoch) {
          input_collector_.discard(); (void)input_collector_.take_cancellation();
          cancel_input(state); break;
        }
        }
      } catch(const std::exception& e) {
        cancel_input(state); report_fatal(e.what()); input_failed_=true; return;
      }
    } else {
      const auto actions=input_mapper_.update(snapshot,bottom_ui_.state().input_context,std::min(delta_seconds,0.1F));
      for(const auto& action:actions) {
        const bool pointer=action.type==ActionType::PointerDown||action.type==ActionType::PointerMove||action.type==ActionType::PointerUp||action.type==ActionType::Tap||action.type==ActionType::DoubleTap||action.type==ActionType::LongPress;
        if(pointer){for(const auto& translated:bottom_ui_.process(action))dispatch(state,translated);}
        else dispatch(state,action);
      }
    }

    const LifecycleDecision periodic = lifecycle_.tick(frame_started);
    apply_lifecycle_decision(state, periodic, false);

    if (telemetry_log_gate_.due(frame_started)) {
      const auto sample_started = now_us();
      (void)call_platform_method(state,"samplePerformanceContext");
      g_workload_time_us += now_us() - sample_started;
    }

    if (bottom_mode_ == BottomScreenMode::Panel &&
        panel_refresh_.due(frame_started) &&
        (dirty_ || bottom_ui_.is_pressed())) {
      // In game mode the lower screen is repainted by after_frame() instead,
      // in lockstep with the frame it mirrors.
      render_bottom();
    }

  }

  bool consumes_event(const SDL_Event& event) const noexcept {
    if (!initialized_ || bottom_window_id_ == 0U) {
      return false;
    }
    if(bottom_mode_==BottomScreenMode::Game) {
      // SDL N3DS touch emulation is the only pointer owner. HID is dispatched
      // synchronously; consume all derived pointers regardless of window ID.
      switch(event.type) {
        case SDL_MOUSEMOTION: case SDL_MOUSEBUTTONDOWN: case SDL_MOUSEBUTTONUP:
        case SDL_FINGERDOWN: case SDL_FINGERUP: case SDL_FINGERMOTION:return true;
        default:return false;
      }
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
      if (bottom_mode_ == BottomScreenMode::Panel) panel_refresh_.request_redraw();
    }
    dirty_ = true;
  }

  BottomUiState state() const { return bottom_ui_.state(); }

  void request_redraw() noexcept {
    dirty_ = true;
    if (bottom_mode_ == BottomScreenMode::Panel) panel_refresh_.request_redraw();
  }

  void force_render_bottom() {
    dirty_ = true;
    // Game pixels are published only by after_frame, after SDL_RenderFlush.
    // A UI/lifecycle notification may arrive while draw commands are queued.
    if (bottom_mode_ == BottomScreenMode::Panel) render_bottom();
  }

  //! Told to us by render_target's constructor, because SDL2 has no way to
  //! enumerate windows and the lower screen has to read the frame CorsixTH
  //! just drew.
  void set_game_window(SDL_Window* window) noexcept {
    game_window_ = window;
    game_window_id_ = window != nullptr ? SDL_GetWindowID(window) : 0U;
    if (!window) { game_surface_ = nullptr; return; }
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

  void set_game_canvas(SDL_Surface* surface) noexcept {
    game_surface_ = surface;
    view_.reset_canvas(surface ? surface->w : 0, surface ? surface->h : 0);
    if (surface) {
      std::FILE* reference = std::fopen("sdmc:/3ds/corsixth/render-reference.txt", "rb");
      render_work.fast_flip_enabled = reference == nullptr;
#ifdef CORSIXTH_3DS_GPU
      if(gpu_active())render_work.fast_flip_enabled=false; // UV flips share one decoded source
#endif
      std::FILE* blit_reference = std::fopen("sdmc:/3ds/corsixth/blit-reference.txt", "rb");
      blit_counters.enabled = blit_reference == nullptr;
#ifdef CORSIXTH_3DS_GPU
      if(gpu_active())blit_counters.enabled=false;
#endif
      blit_counters.reference_forced = blit_reference != nullptr;
      if (blit_reference) std::fclose(blit_reference);
      if (reference) std::fclose(reference);
      boot_log("canvas: owned %dx%d format=%lu pitch=%d top=400x240 native bottom=320x240 half",
               surface->w, surface->h, static_cast<unsigned long>(surface->format->format), surface->pitch);
    }
  }

  void focus_view(int x, int y) noexcept {
    view_.inspect(x, y, {g_input_cursor_x, g_input_cursor_y});
    request_redraw();
  }

  void set_view_context(InputContext context) {
    const bool entered = context != view_.context();
    if (view_.set_context(context)) request_redraw();
    if (entered) {
      if (context == InputContext::PlaceObject)
        set_hint("place");
      else if (context == InputContext::BuildRoom)
        set_hint("room");
      else if (context == InputContext::TextInput)
        set_hint("keyboard");
    }
  }
  void toggle_view() {
    if (view_.toggle()) request_redraw();
    set_hint(view_.bounds().w == 480 ? "wide" : "clear");
  }
  Vec2f move_view(Vec2f delta) noexcept {
    const auto residual = view_.move(delta, {g_input_cursor_x, g_input_cursor_y});
    request_redraw();
    return residual;
  }
  bool activation_needs_focus(const Action& action) const noexcept {
    return view_.activation_needs_focus(action.type, {g_input_cursor_x, g_input_cursor_y});
  }

  bool display_failure(const char* code, const char* detail) {
    ++display_error_count_;
    if (display_error_ != detail) {
      display_error_ = detail;
      startup_code_ = code;
      startup_label_ = detail;
      boot_log("display: %s %s", code, detail);
      render_boot_page(true);
    }
    return false;
  }

  bool valid_output_surface(const SDL_Surface* surface, int width, int height) const {
    return GameView::valid_output(game_surface_, surface, width, height);
  }

  bool present_game(int /*legacy_cursor_x*/, int /*legacy_cursor_y*/) {
    cpu_bottom_presented_=false;
    if(presentation_.mode()==PresentationMode::Error) return false;
    const bool artwork=presentation_.mode()==PresentationMode::BootArtwork;
#ifdef CORSIXTH_3DS_GPU
    if(gpu_active()){
      if(artwork){++top_attempts_;++bottom_attempts_;return gpu_boot_artwork();}
      view_.follow({g_input_cursor_x,g_input_cursor_y});
      ++top_attempts_;
      const bool top_ok=gpu_top(view_.bounds());
      // Loading screens also end frames before the main loop is running.
      // Publish the two outputs as one GPU job on every engine end_frame.
      RuntimeTimingScope bottom(TimingStage::Bottom);
      const bool bottom_ok=mirror_game_to_bottom();
      bottom.finish(bottom_ok);
      if(top_ok&&bottom_ok&&trace_next_present_){
        boot_log("view-present: source=%dx%d origin=%d,%d cursor=%d,%d submitted=1 renderer=gpu",
          view_.bounds().w,view_.bounds().h,view_.bounds().x,view_.bounds().y,
          g_input_cursor_x,g_input_cursor_y);
        trace_next_present_=false;
      }
      return top_ok&&bottom_ok;
    }
#endif
    if (!game_window_ || !game_surface_) return false;
    SDL_Surface* output = SDL_GetWindowSurface(game_window_);
    if (!valid_output_surface(output, 400, 240))
      return display_failure("E-DISPLAY", "INVALID TOP CANVAS");
    const Vec2i pointer{g_input_cursor_x, g_input_cursor_y};
    if(!artwork) view_.follow(pointer);
    const bool lock = SDL_MUSTLOCK(output) != 0;
    if (lock && SDL_LockSurface(output) != 0)
      return display_failure("E-DISPLAY", "TOP LOCK FAILED");
    const auto before = now_us();
    const bool copied = artwork ? copy_artwork(output,true) : view_.copy_top(game_surface_, output);
    top_copy_us_ += now_us() - before;
    if (lock) SDL_UnlockSurface(output);
    const auto submitted_at = now_us();
    const bool submitted = copied && SDL_UpdateWindowSurface(game_window_) == 0;
    top_submit_us_ += now_us() - submitted_at;
    ++top_attempts_;
    if (!submitted) return display_failure("E-DISPLAY", "TOP PRESENT FAILED");
    // App loading end_frame runs before the main-loop after_frame callback.
    // Publish the CPU startup pair here, just as the GPU path does; a later
    // tail callback observes this completion without submitting bottom twice.
    if(artwork){
      RuntimeTimingScope bottom(TimingStage::Bottom);
      cpu_bottom_presented_=mirror_game_to_bottom();
      bottom.finish(cpu_bottom_presented_);
      return cpu_bottom_presented_;
    }
    if (trace_next_present_) {
      boot_log("view-present: source=%dx%d origin=%d,%d cursor=%d,%d submitted=1",
        view_.bounds().w,view_.bounds().h,view_.bounds().x,view_.bounds().y,pointer.x,pointer.y);
      trace_next_present_ = false;
    }
    return true;
  }

  void log_display_stats() noexcept {
#ifdef CORSIXTH_3DS_GPU
    gpu_log_statistics();
#endif
    if (!top_attempts_ && !display_error_count_) return;
    boot_log("display-stats: attempts=%llu copy_us=%llu submit_us=%llu errors=%llu view_x=%d view_y=%d view_w=%d view_h=%d context=%u",
        static_cast<unsigned long long>(top_attempts_),
        static_cast<unsigned long long>(top_copy_us_),
        static_cast<unsigned long long>(top_submit_us_),
        static_cast<unsigned long long>(display_error_count_), view_.bounds().x, view_.bounds().y,
        view_.bounds().w,view_.bounds().h,(unsigned)view_.context());
    top_attempts_ = top_copy_us_ = top_submit_us_ = display_error_count_ = 0;
    boot_log("bottom-stats: attempts=%llu copy_us=%llu submit_us=%llu",
      static_cast<unsigned long long>(bottom_attempts_),static_cast<unsigned long long>(bottom_copy_us_),
      static_cast<unsigned long long>(bottom_submit_us_));
    bottom_attempts_ = bottom_copy_us_ = bottom_submit_us_ = 0;
    const auto q = input_collector_.statistics();
    boot_log("input-queue: sampled=%llu popped=%llu coalesced=%llu touch_down=%llu touch_up=%llu overflows=%llu discarded=%llu max_age_us=%llu max_sample_gap_us=%llu peak=%lu pending=%lu",
      (unsigned long long)q.sampled,(unsigned long long)q.popped,(unsigned long long)q.coalesced,
      (unsigned long long)q.touch_down,(unsigned long long)q.touch_up,(unsigned long long)q.overflows,
      (unsigned long long)q.discarded,(unsigned long long)q.max_age_us,(unsigned long long)q.max_sample_gap_us,
      (unsigned long)q.peak_depth,(unsigned long)input_collector_.size());
    boot_log("input-latency: cumulative_samples=%llu age_p95_upper_us=%llu visible_latency_not_measured=1",
      (unsigned long long)q.popped,(unsigned long long)q.age_p95_upper_us());
    boot_log("render-work: fast_flip=%d draws=%llu fallback_flip=%llu creates=%llu decoded_pixels=%llu flip_hits=%llu flip_misses=%llu avoided_flip_pixels=%llu evictions=%llu cache_bytes=%llu cache_peak=%llu cache_budget=6291456",
      render_work.fast_flip_enabled,(unsigned long long)render_work.draws,(unsigned long long)render_work.flipped_fallback,
      (unsigned long long)render_work.texture_creates,(unsigned long long)render_work.decoded_pixels,
      (unsigned long long)render_work.flip_hits,(unsigned long long)render_work.flip_misses,(unsigned long long)render_work.flip_pixels_saved,
      (unsigned long long)render_work.cache_evictions,(unsigned long long)render_work.cache_bytes,(unsigned long long)render_work.cache_peak_bytes);
    render_work.reset_counts();
    boot_log("blit-work: enabled=%d direct=%llu opaque=%llu fallback=%llu promotions=%llu clipped=%llu pixels=%llu live_bytes=%llu peak_bytes=%llu images=%llu",
      blit_counters.enabled,(unsigned long long)blit_counters.direct,(unsigned long long)blit_counters.opaque,
      (unsigned long long)blit_counters.fallback,(unsigned long long)blit_counters.promoted,
      (unsigned long long)blit_counters.clipped,(unsigned long long)blit_counters.pixels,
      (unsigned long long)blit_counters.live_bytes,(unsigned long long)blit_counters.peak_bytes,
      (unsigned long long)blit_counters.live_images);
    boot_log("blit-probe: ran=%d checksum_match=%d reference_forced=%d opaque_reference_us=%llu opaque_fast_us=%llu sparse_reference_us=%llu sparse_fast_us=%llu selected=%s span_bytes=%llu span_budget=262144",
      blit_counters.probe_ran,blit_counters.probe_pixels,blit_counters.reference_forced,
      (unsigned long long)blit_counters.probe_reference_us[0],(unsigned long long)blit_counters.probe_fast_us[0],
      (unsigned long long)blit_counters.probe_reference_us[1],(unsigned long long)blit_counters.probe_fast_us[1],
      blit_counters.enabled?"binary-span":"sdl-reference",(unsigned long long)blit_counters.span_bytes);
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
    boot_log_flush();
    if (bottom_window_ != nullptr && presentation_.mode()==PresentationMode::BootText) {
      render_boot_page(false);
    }
  }

  void show_fatal(const char* reason) {
    presentation_.error();
    startup_code_ = "FATAL";
    startup_label_ = reason != nullptr ? reason : "UNKNOWN ERROR";
    (void)ensure_bottom_window();
    render_boot_page(true);
  }

  void set_presentation(bool artwork) {
    if(artwork) presentation_.artwork(); else presentation_.game();
    boot_log("presentation: mode=%s",presentation_.mode()==PresentationMode::BootArtwork?"boot-artwork":
             presentation_.mode()==PresentationMode::Error?"error":"game");
  }

  //! Called straight after CorsixTH presents a frame. In game mode the lower
  //! screen is the same frame at an exact 2:1 reduction, so the player sees
  //! the real interface - toolbar, dialogs and all - and can touch it.
  void after_frame(bool draw_success) {
    PresentResult result = PresentResult::Skipped;
    if (presentation_.mode()==PresentationMode::Error || !draw_success || (g_top_present_seen && !g_top_present_ok)) {
      result = PresentResult::Failed;
    } else if (initialized_ && bottom_mode_ == BottomScreenMode::Game && g_top_present_seen) {
#ifdef CORSIXTH_3DS_GPU
      if(gpu_active())result=PresentResult::Success;
      else
#endif
      {
      RuntimeTimingScope bottom(TimingStage::Bottom);
      const bool ok = cpu_bottom_presented_ || mirror_game_to_bottom();
      bottom.finish(ok);
      result = ok ? PresentResult::Success : PresentResult::Failed;
      }
    }
    const auto presented=now_us();
    g_observations.timing.present_complete(presented, result);
    g_observations.sample_present(presented, result);
    runner_present(result==PresentResult::Success);
    g_top_present_seen = g_top_present_ok = false;
    cpu_bottom_presented_=false;
  }

  [[nodiscard]] bool mirrors_game() const noexcept {
    return bottom_mode_ == BottomScreenMode::Game;
  }

  void begin_critical_io() noexcept {
    const bool was_active = lifecycle_.in_critical_io();
    lifecycle_.begin_critical_io();
    if (!was_active) {
      input_collector_.pause(true);
      aptSetSleepAllowed(false);
    }
  }

  bool text_keyboard(const char* initial, int limit, const char* policy, char* output, std::size_t capacity) {
#ifdef CORSIXTH_3DS_GPU
    gpu_quiesce();
#endif
#ifndef CTH3DS_STUB_BUILD
    input_collector_.pause(true);
    runtime_operation_boundary(); // Applet wait is outside simulation time.
    bool channel_paused[32]{};
    for (int i=0;i<32;++i) { channel_paused[i]=Mix_Paused(i)!=0; Mix_Pause(i); }
    const bool music_paused=Mix_PausedMusic()!=0; Mix_PauseMusic();
    cth3ds_suspend_sound_callbacks(true, SDL_GetTicks());
    SwkbdState keyboard;
    const bool numeric = !std::strcmp(policy, "numbers");
    swkbdInit(&keyboard, numeric ? SWKBD_TYPE_NUMPAD : SWKBD_TYPE_NORMAL, 2, limit);
    swkbdSetInitialText(&keyboard, initial);
    swkbdSetHintText(&keyboard, numeric ? "Digits only; Apply keeps the field's range rules" :
      (!std::strcmp(policy, "player") ? "English letters / numbers / space / + / -" :
      "English letters / numbers / space / - / _"));
    swkbdSetButton(&keyboard, SWKBD_BUTTON_LEFT, "Cancel", false);
    swkbdSetButton(&keyboard, SWKBD_BUTTON_RIGHT, "OK", true);
    boot_log("keyboard: begin policy=%s limit=%d",policy,limit); boot_log_memory("KEYBOARD-BEGIN");
    const auto button=swkbdInputText(&keyboard, output, capacity);
    runtime_operation_boundary();
    boot_log("keyboard: end button=%d result=%d",static_cast<int>(button),static_cast<int>(swkbdGetResult(&keyboard)));
    boot_log_memory("KEYBOARD-END");
    cth3ds_suspend_sound_callbacks(false, SDL_GetTicks());
    for (int i=0;i<32;++i) if(!channel_paused[i]) Mix_Resume(i);
    if(!music_paused) Mix_ResumeMusic();
    input_collector_.pause(false); last_input_us_=0;
    if (button == SWKBD_BUTTON_NONE) set_hint("keyboard_unavailable");
    return button==SWKBD_BUTTON_RIGHT && !(pending_lifecycle_.load() & kLifecycleExit);
#else
    (void)initial; (void)limit; (void)policy; (void)output; (void)capacity;
    set_notice("KEYBOARD NOT PROVIDED BY HOST STUB", false); return false;
#endif
  }

  void end_critical_io() noexcept {
    lifecycle_.end_critical_io();
    if (!lifecycle_.in_critical_io()) {
      input_collector_.pause(false);
      aptSetSleepAllowed(true);
    }
  }

#if CTH3DS_RESOURCE_EXPERIMENT
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

#endif
  bool set_hint(std::string_view id) {
    const auto* hint = notice_hint(id);
    if (!hint) return false;
    set_notice(hint->english, false, std::string(hint->id));
    return true;
  }
  void set_notice(std::string notice, bool is_error, std::string hint = "") {
    BottomUiState copy = bottom_ui_.state();
    if (copy.notice == notice && copy.notice_is_error == is_error && copy.notice_hint == hint) {
      return;
    }
    copy.notice = std::move(notice);
    copy.notice_hint = std::move(hint);
    notice_until_us_ = now_us() + 4000000U;
    copy.notice_is_error = is_error;
    bottom_ui_.set_state(std::move(copy));
    dirty_ = true;
    if (bottom_mode_ == BottomScreenMode::Panel) panel_refresh_.request_redraw();
  }

  PerformanceSnapshot performance() const { return g_observations.timing.snapshot(now_us()); }

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
    const ContiguousProbePolicy policy = memory_gate_probe_policy(gate);
    const ContiguousProbeResult result = probe_largest_contiguous(
        static_cast<std::size_t>(before.heap_available_estimate), policy,
        regular_probe_allocate, regular_probe_release);
    char probe_message[256];format_memory_gate_probe(probe_message,sizeof(probe_message),gate,result);
    boot_log("memory-probe-policy: %s",probe_message);
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

  }

  void cancel_input(lua_State* state) {
    if(g_benchmark_active)(void)call_platform_method(state,"benchmarkCancel");
    std::string error;
    const bool released=input_mapper_.cancel_mixed([&](const Action& action){return call_platform_method(state,"handleAction",&action,&error);});
    const bool cleared=call_platform_method(state,"cancelPointer",nullptr,&error);
    if(!released||!cleared){input_failed_=true;report_fatal(error.c_str());}
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
      g_simulation_clock.interrupt();
      boot_log("lifecycle: flags=0x%08lx", static_cast<unsigned long>(flags));
    }
    if(flags && bottom_mode_==BottomScreenMode::Game) { input_collector_.discard(); cancel_input(state); }
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
    const auto restore_token=is_resume?runtime_span_begin(TimingStage::Restore):0;
    if (decision.pause_audio && !lifecycle_audio_suspended_) {
#ifdef CORSIXTH_3DS_GPU
      gpu_quiesce();
#endif
      input_collector_.pause(true);
      lifecycle_audio_suspended_ = true;
#ifndef CTH3DS_STUB_BUILD
      cth3ds_suspend_sound_callbacks(true, SDL_GetTicks());
#endif
      for(int c=0;c<32;++c) { audio_paused_before_[c]=Mix_Paused(c)!=0; if(!audio_paused_before_[c])Mix_Pause(c); }
      music_paused_before_=Mix_PausedMusic()!=0;Mix_PauseMusic();
    }
#if CTH3DS_RESOURCE_EXPERIMENT
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
#endif
    if (decision.resume_audio && lifecycle_audio_suspended_) {
      input_collector_.pause(false);
#ifndef CTH3DS_STUB_BUILD
      cth3ds_suspend_sound_callbacks(false, SDL_GetTicks());
#endif
      lifecycle_audio_suspended_ = false;
      for(int c=0;c<32;++c)if(!audio_paused_before_[c])Mix_Resume(c);
      if(!music_paused_before_)Mix_ResumeMusic();
      panel_refresh_.reset();last_tick_us_=now_us();
    }
    if(restore_token){runtime_observe_memory("restore","reconciled","simulation",MemoryGate::Operation);runtime_span_end(restore_token,!input_failed_);}
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
#if CTH3DS_RESOURCE_EXPERIMENT
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
#endif
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
      if (bottom_mode_ == BottomScreenMode::Panel) panel_refresh_.request_redraw();
    }
  }

  //! Copy the 640x480 CorsixTH frame onto the 320x240 lower screen, taking
  //! every second pixel. Both surfaces are RGBA8888, so this is a straight
  //! pixel move with no format conversion.
  bool mirror_game_to_bottom() {
#ifdef CORSIXTH_3DS_GPU
    if(gpu_active()){
      ++bottom_attempts_;
      const auto* pixels=overlay_pixels();
      const bool ok=gpu_bottom(view_.bounds(),pixels,pixels?kOverlayHeight:0);
      if(ok){dirty_=false;display_error_=nullptr;}
      return ok;
    }
#endif
    if (bottom_window_ == nullptr || game_window_ == nullptr) {
      return false;
    }
    SDL_Surface* source = game_surface_;
    bottom_surface_ = SDL_GetWindowSurface(bottom_window_);
    if (!valid_output_surface(bottom_surface_, 320, 240))
      return display_failure("E-MIRROR", "INVALID MIRROR CANVAS");

    const bool lock_source = SDL_MUSTLOCK(source) != 0;
    if (lock_source && SDL_LockSurface(source) != 0) {
      return false;
    }
    const bool lock_destination = SDL_MUSTLOCK(bottom_surface_) != 0;
    if (lock_destination && SDL_LockSurface(bottom_surface_) != 0) {
      if (lock_source) {
        SDL_UnlockSurface(source);
      }
      return false;
    }

    const auto copy_started = now_us();
    const bool artwork=presentation_.mode()==PresentationMode::BootArtwork;
    const bool scaled = artwork ? copy_artwork(bottom_surface_,false) : view_.copy_bottom(source, bottom_surface_);
    if (scaled && !artwork) draw_overlay_strip();

    if (lock_destination) {
      SDL_UnlockSurface(bottom_surface_);
    }
    if (lock_source) {
      SDL_UnlockSurface(source);
    }
    bottom_copy_us_ += now_us() - copy_started;
    const auto submit_started = now_us();
    const bool submitted = scaled && SDL_UpdateWindowSurface(bottom_window_) == 0;
    bottom_submit_us_ += now_us() - submit_started;
    ++bottom_attempts_;
    if (submitted) { dirty_ = false; display_error_ = nullptr; }
    return submitted;
  }

  //! A short status strip over the mirrored frame: the build stamp for the
  //! first few seconds after boot, and any error notice for as long as it
  //! stands. Everything else on the lower screen is the game itself.
  const std::uint32_t* overlay_pixels() {
    const BottomUiState& state = bottom_ui_.state();
    const bool has_error = state.notice_is_error && !state.notice.empty();
    const bool show_stamp = last_tick_us_ < overlay_until_us_;
    const bool show_notice = !state.notice.empty() && now_us() < notice_until_us_;
    const bool paused=state.paused && !state.must_pause;
    if (!has_error && !paused && !show_stamp && !show_notice) {
      return nullptr;
    }
    const std::string text = has_error ? state.notice : paused ?
      (state.user_actions_allowed ? "pause-build" : "pause") : show_notice ? state.notice : "R75 " + state.build_tag;
    if (text.empty()) {
      return nullptr;
    }
    const auto* hint = !has_error && !paused && state.chinese_ui && show_notice ? notice_hint(state.notice_hint) : nullptr;
    const presentation_masks::Mask* mask = !has_error && state.chinese_ui ?
      (paused ? (state.user_actions_allowed ? &presentation_masks::paused_build : &presentation_masks::paused) :
       hint ? hint->chinese : nullptr) : nullptr;
    if(text==overlay_text_ && has_error==overlay_error_ && mask==overlay_mask_)
      return reinterpret_cast<const std::uint32_t*>(overlay_canvas_.rgba_bytes().data());
    overlay_text_=text;overlay_error_=has_error;overlay_mask_=mask;
    overlay_canvas_.clear(has_error ? Rgba{176, 46, 40, 255}
                                    : Rgba{18, 25, 32, 255});
    if(mask){
      paint_fixed_mask(*mask,(320-mask->width)/2,(kOverlayHeight-mask->height)/2,
        [this](int x,int y,unsigned alpha){
          overlay_canvas_.pixel(x,y,{static_cast<std::uint8_t>(18+(239-18)*alpha/255),
            static_cast<std::uint8_t>(25+(242-25)*alpha/255),
            static_cast<std::uint8_t>(32+(244-32)*alpha/255),255});
        });
    } else overlay_canvas_.text(3, 3, paused && !has_error ?
      (state.user_actions_allowed ? "PAUSED - BUILD OK - START: RESUME" : "PAUSED - START: RESUME") : text,
      Rgba{239, 242, 244, 255});

    const auto& bytes = overlay_canvas_.rgba_bytes();
    return reinterpret_cast<const std::uint32_t*>(bytes.data());
  }
  void draw_overlay_strip() {
    const auto* source=overlay_pixels();
    if(!source)return;
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
    if(error) presentation_.error();
    else if(presentation_.mode()!=PresentationMode::BootText) return;
    overlay_text_.clear(); // the boot page borrows the same strip storage
#ifdef CORSIXTH_3DS_GPU
    gpu_quiesce();
#endif
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
    if(!error){
      draw_boot_mask(presentation_masks::loading,87);
      draw_boot_mask(presentation_masks::credit,123);
      draw_boot_mask(presentation_masks::based,146);
      if(must_lock)SDL_UnlockSurface(bottom_surface_);
      (void)SDL_UpdateWindowSurface(bottom_window_);
      return;
    }
    draw_boot_line(8, std::string("CORSIXTH R75 ") + kOverlayVersion,
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

  void draw_boot_mask(const presentation_masks::Mask& mask,int y) {
    if(bottom_surface_->format->format!=SDL_PIXELFORMAT_RGBA8888 || bottom_surface_->pitch%4) return;
    paint_fixed_mask(mask,(320-mask.width)/2,y,[this](int x,int line,unsigned alpha){
      if(x<0||x>=bottom_surface_->w||line<0||line>=bottom_surface_->h)return;
      auto* row=reinterpret_cast<std::uint32_t*>(static_cast<std::uint8_t*>(bottom_surface_->pixels)+line*bottom_surface_->pitch);
      row[x]=SDL_MapRGBA(bottom_surface_->format,static_cast<Uint8>(18+(239-18)*alpha/255),
                        static_cast<Uint8>(25+(242-25)*alpha/255),static_cast<Uint8>(32+(244-32)*alpha/255),255);
    });
  }

  bool copy_artwork(SDL_Surface* output,bool top) {
    return copy_boot_artwork(static_cast<const std::uint32_t*>(game_surface_->pixels),game_surface_->pitch/4,
      static_cast<std::uint32_t*>(output->pixels),output->w,output->pitch/4,top,
      SDL_MapRGBA(output->format,0,0,0,255),game_surface_->format->format!=output->format->format);
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
  SDL_Surface* game_surface_{nullptr}; // borrowed; render_target owns the pixels
  GameView view_{};
  BootPresentation presentation_{};
  bool cpu_bottom_presented_{false}; // completion of current engine end_frame only
  std::string overlay_text_{};
  bool overlay_error_{false};
  const presentation_masks::Mask* overlay_mask_{nullptr};
  bool trace_next_present_{false};
  std::uint32_t traced_held_{0};
  const char* display_error_{nullptr};
  std::uint64_t display_error_count_{0}, top_attempts_{0}, top_copy_us_{0}, top_submit_us_{0};
  std::uint64_t bottom_attempts_{0}, bottom_copy_us_{0}, bottom_submit_us_{0};
  Uint32 game_window_id_{0U};
  BottomScreenMode bottom_mode_{BottomScreenMode::Game};
  std::uint64_t overlay_until_us_{0U};
  std::uint64_t notice_until_us_{0U}, last_input_us_{0U};
  bool input_failed_{false};
  SDL_Window* bottom_window_{nullptr};
  SDL_Surface* bottom_surface_{nullptr};
  Uint32 bottom_window_id_{0U};
  BottomUiController bottom_ui_{};
  std::unique_ptr<SoftwareCanvas> bottom_canvas_{};
  SoftwareCanvas overlay_canvas_;
  InputMapper input_mapper_{[] { InputMapperConfig c; c.overview_controls = true; return c; }()};
  InputCollector3ds input_collector_{};
  PanelRefreshGate panel_refresh_;
  LifecycleController lifecycle_;

  aptHookCookie apt_cookie_{};
  std::atomic<std::uint32_t> pending_lifecycle_{0U};
  std::atomic<bool> exit_requested_{false};
#if CTH3DS_RESOURCE_EXPERIMENT
  std::unique_ptr<RuntimeSession> resource_session_{};
#endif
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
  bool lifecycle_audio_suspended_{false};
  bool apt_hooked_{false};
  bool ptmu_ready_{false};
#if CTH3DS_RESOURCE_EXPERIMENT
  bool resource_start_failed_{false};
#endif
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
  lua_pushliteral(state,"_3ds");lua_rawget(state,-2);
  if(!lua_istable(state,-1))return luaL_error(state,"mark_ready requires completed adapter");
  lua_pushliteral(state,"app");lua_rawget(state,-2);
  bool attached=lua_rawequal(state,-1,-3)!=0;lua_pop(state,1);
  lua_pushliteral(state,"completed");lua_rawget(state,-2);
  attached=attached && lua_isboolean(state,-1) && lua_toboolean(state,-1);lua_pop(state,1);
  lua_pushliteral(state,"capabilities");lua_rawget(state,-2);
  if(lua_istable(state,-1)){
    lua_pushliteral(state,"epoch");lua_rawget(state,-2);
    attached=attached && lua_isinteger(state,-1) &&
      lua_tointeger(state,-1)==static_cast<lua_Integer>(runtime().epoch());lua_pop(state,1);
  }else attached=false;
  lua_pop(state,3);
  attached=attached && !g_operation_blocked;
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

int l_presentation(lua_State* state) {
  const char* mode=luaL_checkstring(state,1);
  if(std::strcmp(mode,"boot-artwork")!=0 && std::strcmp(mode,"game")!=0)
    return luaL_error(state,"invalid presentation mode");
  runtime().set_presentation(std::strcmp(mode,"boot-artwork")==0);
  return 0;
}

int l_probe(lua_State* state) {
  update_lua_memory(state);
  const char* label = luaL_optstring(state, 1, "LUA");
  const char* requested_gate = luaL_checkstring(state, 2);
  MemoryGate gate = MemoryGate::Operation;
  if (std::strcmp(requested_gate, "MenuStable") == 0) gate = MemoryGate::MenuStable;
  else if (std::strcmp(requested_gate, "LevelStable") == 0) gate = MemoryGate::LevelStable;
  else if (std::strcmp(requested_gate, "Operation") != 0)
    return luaL_error(state, "unknown memory gate");
  const bool ok = runtime().probe_regular_heap(label, gate);
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
  lua_pushboolean(state, memory.linear_low_valid ? 1 : 0);
  lua_setfield(state, -2, "linear_low_valid");
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

int l_request_observation_flush(lua_State*) {
  g_observations.flush_requested = true;
  return 0;
}
int protected_lua_call(lua_State* state) {
  const int arguments=lua_gettop(state)-1;
  lua_pushcfunction(state,preserve_lua_error);
  lua_insert(state,1);
  const int status=lua_pcall(state,arguments,LUA_MULTRET,1);
  lua_remove(state,1);
  return status;
}
int l_cpu_profile(lua_State* state) {
  const char* name=luaL_checkstring(state,1);
  const auto kind=std::strcmp(name,"world")==0?CpuWork::World:CpuWork::UI;
  if(std::strcmp(name,"world")&&std::strcmp(name,"ui"))return luaL_error(state,"unknown CPU profile");
  luaL_checktype(state,2,LUA_TFUNCTION);lua_remove(state,1);
  int status;
  {CpuWorkScope scope(kind);status=protected_lua_call(state);}
  if(status!=LUA_OK)return lua_error(state);
  return lua_gettop(state);
}
int l_clock_ms(lua_State* state){lua_pushinteger(state,static_cast<lua_Integer>(now_us()/1000));return 1;}
int l_simulation_clock(lua_State* state){
  // Low-frequency acceptance boundaries only; this reads the existing owner.
  const auto clock=g_simulation_clock.statistics();
  lua_createtable(state,0,9);
  const auto field=[state](const char* key,std::uint64_t value){
    lua_pushinteger(state,static_cast<lua_Integer>(value));lua_setfield(state,-2,key);
  };
  field("at_us",now_us());field("nominal_timer_us",SimulationClock::step_us);
  field("completed_steps",clock.completed_steps);field("failed_steps",clock.failed_steps);
  field("dropped_us",clock.dropped_us);field("debt_us",clock.debt_us);
  field("rebases",clock.rebases);field("budget_exits",clock.budget_exits);
  return 1;
}
int l_music_state(lua_State* state) {
  lua_pushboolean(state,Mix_PlayingMusic()!=0);
  lua_pushboolean(state,Mix_PausedMusic()!=0);
  return 2;
}
int l_cpu_phase(lua_State* state) {
  if(!cpu_work.enabled){lua_pushnil(state);return 1;}
  const auto now=now_us();
  if(lua_gettop(state)>0) {
    const char* name=luaL_checkstring(state,1);
    const auto began=checked_non_negative_integer(state,2);
    std::size_t index=static_cast<std::size_t>(CpuWork::WorldCalendar);
    for(;index<kCpuWorkNames.size();++index)
      if(!std::strcmp(kCpuWorkNames[index],name)) break;
    if(index==kCpuWorkNames.size()) return luaL_error(state,"unknown World phase");
    if(cpu_work.enabled && began && now>=began) {
      cpu_work.record(index,began,now);
      g_observations.slow.record(began,now,"world",name);
    }
  }
  lua_pushinteger(state,static_cast<lua_Integer>(cpu_work.enabled?now:0));
  return 1;
}
int l_trace_call(lua_State* state) {
  char kind[24]{},identity[96]{};
  std::snprintf(kind,sizeof(kind),"%s",luaL_checkstring(state,1));
  std::snprintf(identity,sizeof(identity),"%s",luaL_checkstring(state,2));
  luaL_checktype(state,3,LUA_TFUNCTION);
  lua_remove(state,1);lua_remove(state,1);
  const auto began=now_us();
  const int status=protected_lua_call(state);
  g_observations.slow.record(began,now_us(),kind,identity,status==LUA_OK);
  if(status!=LUA_OK) return lua_error(state);
  return lua_gettop(state);
}
int l_window_identity(lua_State* state) {
  g_observations.slow.owner(now_us(),luaL_checkstring(state,1));
  return 0;
}
int l_benchmark_state(lua_State* state){g_benchmark_active=lua_toboolean(state,1)!=0;return 0;}
int l_benchmark_active(lua_State* state){lua_pushboolean(state,g_benchmark_active);return 1;}
int l_benchmark_enabled(lua_State* state){
  if(runner_active()){lua_pushboolean(state,!runner_interactive());return 1;}
  constexpr const char* marker="sdmc:/3ds/corsixth/benchmark-run.txt";
  bool enabled=false;
  if(auto* file=std::fopen(marker,"rb")){
    char magic[6]{};const auto length=std::fread(magic,1,5,file);std::fclose(file);
    if(length==4&&!std::memcmp(magic,"R63\n",4)){
      if(auto* input=std::fopen("sdmc:/3ds/corsixth/Benchmark/input.sav","rb")){
        std::fclose(input);
        enabled=!lua_toboolean(state,1) ||
          std::rename(marker,"sdmc:/3ds/corsixth/benchmark-used-r63.txt")==0;
      }
    }
    boot_log("benchmark: request=%s accepted=%d input=Benchmark/input.sav",
      lua_toboolean(state,1)?"claim":"peek",enabled);
  }
  lua_pushboolean(state,enabled);return 1;
}
int l_benchmark_mark(lua_State* state){
  const char* event=luaL_checkstring(state,1);const char* speed=luaL_checkstring(state,2);
  const char* date=luaL_checkstring(state,3);
  const bool begin=!std::strcmp(event,"SAMPLE-BEGIN");
  const bool end=!std::strcmp(event,"SAMPLE-END");
  if((begin && g_observations.sample_open()) || (end && !g_observations.sample_open())) {
    const auto invalid_boundary=now_us();
    const auto clock=g_simulation_clock.statistics();
    const bool was_open=g_observations.sample_open();
#ifdef CORSIXTH_3DS_GPU
    gpu_submit_sample_end(invalid_boundary,false);
#endif
    g_observations.sample_mark("INVALID-ORDER",invalid_boundary,{boot_log,boot_log_flush,nullptr},&clock);
#ifdef CORSIXTH_3DS_GPU
    if(was_open)gpu_submit_sample_log(false);
#endif
    if(was_open)boot_log_flush();
    return luaL_error(state,"benchmark sample marks out of order");
  }
  // Begin logging belongs to warmup. End logging belongs to the closed window's
  // report. Both consumers receive the same monotonic boundary, even on fsync.
  if(begin)boot_log("benchmark: at_us=%llu event=%.48s speed=\"%.32s\" date=%.48s",
    (unsigned long long)now_us(),event,speed,date);
  const auto boundary=now_us();
  const auto frames=runner_frames();
  const auto clock=g_simulation_clock.statistics();
  if(end && !g_observations.sample_can_close(boundary)) {
#ifdef CORSIXTH_3DS_GPU
    gpu_submit_sample_end(boundary,false);
#endif
    g_observations.sample_mark("INVALID-TIME",boundary,{boot_log,boot_log_flush,nullptr},&clock);
#ifdef CORSIXTH_3DS_GPU
    gpu_submit_sample_log(false);
#endif
    boot_log_flush();
    return luaL_error(state,"benchmark sample clock moved backwards");
  }
  const bool closing=g_observations.sample_open();
#ifdef CORSIXTH_3DS_GPU
  if(begin)gpu_submit_sample_begin(boundary);
  else if(closing)gpu_submit_sample_end(boundary,end&&g_observations.sample_eligible(boundary));
#endif
  g_observations.sample_mark(event,boundary,{boot_log,boot_log_flush,nullptr},&clock);
#ifdef CORSIXTH_3DS_GPU
  if(closing)gpu_submit_sample_log(false);
#endif
  if(!begin)
  boot_log("benchmark: at_us=%llu event=%.48s speed=\"%.32s\" date=%.48s",
    (unsigned long long)boundary,event,speed,date);
  if(closing)boot_log_flush();
  lua_pushnumber(state,static_cast<lua_Number>(boundary));
  lua_pushinteger(state,static_cast<lua_Integer>(frames));
  return 2;
}
int l_runner_context(lua_State* state){
  if(!runner_active()){lua_pushnil(state);return 1;}
  lua_newtable(state);
  for(const auto& item:runner_config()){lua_pushstring(state,item.second.c_str());lua_setfield(state,-2,item.first.c_str());}
  lua_pushstring(state,(runner_directory()+"/").c_str());lua_setfield(state,-2,"root");return 1;
}
int l_runner_frames(lua_State* state){lua_pushinteger(state,static_cast<lua_Integer>(runner_frames()));return 1;}
// Validate without C++ owners. The second traversal uses only nonallocating
// Lua accessors on a table whose string keys cannot change during this call.
void runner_validate_fields(lua_State* state,int index){
  luaL_checktype(state,index,LUA_TTABLE);lua_pushnil(state);unsigned count=0;size_t total=0;
  while(lua_next(state,index)){
    size_t key_size=0,value_size=0;
    if(lua_type(state,-2)!=LUA_TSTRING||lua_type(state,-1)!=LUA_TSTRING)
      luaL_error(state,"runner fields must be strings");
    const char* key=lua_tolstring(state,-2,&key_size);const char* value=lua_tolstring(state,-1,&value_size);
    total+=key_size+value_size+2;
    if(std::strspn(key,"abcdefghijklmnopqrstuvwxyz_0123456789")!=key_size||
       std::strlen(value)!=value_size||std::strpbrk(value,"\r\n")||total>12000)
      luaL_error(state,"runner fields have invalid bytes or total size");
    if(++count>128||key_size>64||value_size>1024)luaL_error(state,"runner fields exceed bounds");
    lua_pop(state,1);
  }
}
void runner_read_fields(lua_State* state,int index,runner::Fields& fields){
  lua_pushnil(state);
  while(lua_next(state,index)){fields[lua_tostring(state,-2)]=lua_tostring(state,-1);lua_pop(state,1);}
}
int l_runner_checkpoint(lua_State* state){
  if(!runner_active())return 0;
  runner_validate_fields(state,1);char error[256]{};
  try{runner::Fields fields;runner_read_fields(state,1,fields);
    runner_checkpoint(fields);}
  catch(const std::exception& e){std::snprintf(error,sizeof(error),"progress persistence failed: %.200s",e.what());}
  if(error[0])return luaL_error(state,"%s",error);
  return 0;
}
int l_runner_error(lua_State* state){
  size_t size=0;const char* error=luaL_checklstring(state,1,&size);
  if(!runner_active())return 0;
  bool ok=false;
  try{
    const auto path=runner_directory()+"/artifacts/error.txt";
    if(FILE* file=std::fopen(path.c_str(),"wb")){
      const auto count=std::min(size,size_t(8192));ok=std::fwrite(error,1,count,file)==count;
      if(std::fclose(file))ok=false;
    }
  }catch(...){}
  lua_pushboolean(state,ok);return 1;
}
int l_runner_finish(lua_State* state){
  const auto* outcome=luaL_checkstring(state,1);const auto* reason=luaL_checkstring(state,2);
  runner_validate_fields(state,3);char error[256]{};
  try{runner::Fields fields;runner_read_fields(state,3,fields);
  const auto memory=heap_snapshot();
  fields["heap_available_low"]=std::to_string(memory.heap_available_low_water);
  fields["heap_available_end"]=std::to_string(memory.heap_available_estimate);
  fields["linear_free_end"]=std::to_string(memory.linear_free);
  fields["lua_bytes_end"]=std::to_string(memory.lua_bytes);
  fields["log_truncated"]=g_log.truncated()?"1":"0";
  fields["log_failed"]=g_log.failed()?"1":"0";
  runner_finish(outcome,reason,fields);}
  catch(const std::exception& e){std::snprintf(error,sizeof(error),"result persistence failed: %.200s",e.what());}
  if(error[0])return luaL_error(state,"%s",error);
  return 0;
}
int l_operation_block(lua_State*) { g_operation_blocked=true; return 0; }
int l_span_abandon(lua_State* state) {
  const auto token=static_cast<std::uint64_t>(luaL_checkinteger(state,1));
  lua_pushboolean(state,g_observations.timing.abandon_span(token));
  return 1;
}
int l_span_begin(lua_State* state) {
  const char* name = luaL_checkstring(state, 1);
  for (std::size_t i = 0; i < kTimingStageNames.size(); ++i) {
    if (std::strcmp(name, kTimingStageNames[i]) == 0) {
      const auto token = runtime_span_begin(static_cast<TimingStage>(i));
      if (!token) return luaL_error(state, "timing span rejected");
      lua_pushinteger(state, static_cast<lua_Integer>(token)); return 1;
    }
  }
  return luaL_error(state, "unknown timing stage");
}
int l_span_end(lua_State* state) {
  const auto token = static_cast<std::uint64_t>(luaL_checkinteger(state, 1));
  if (!runtime_span_end(token, lua_toboolean(state, 2) != 0))
    return luaL_error(state, "timing span end rejected");
  return 0;
}
int l_operation_boundary(lua_State*) {
  runtime_operation_boundary();
  return 0;
}
AllocationWatch g_lua_allocations;
MemoryObservationGate g_memory_sampling;
int l_prepare_save(lua_State*) {
  const auto before=text_cache.bytes;
  text_cache.clear(); // reconstructible text only; no game, voice or save data.
  boot_log("save-cache: released_charge=%llu remaining=%llu",
      static_cast<unsigned long long>(before),static_cast<unsigned long long>(text_cache.bytes));
  return 0;
}
int l_diagnostic_line(lua_State* state) {
  std::size_t size=0;
  const char* message=luaL_checklstring(state,1,&size);
  // Bounded normal-thread log; never allocate a full traceback texture.
  for(std::size_t offset=0;offset<size && offset<4096;offset+=240)
    boot_log("lua-diagnostic: %.*s",static_cast<int>(std::min<std::size_t>(240,size-offset)),message+offset);
  boot_log_flush();return 0;
}
int l_observe_memory(lua_State* state) {
  const char* checkpoint = luaL_checkstring(state, 1);
  const char* phase = luaL_checkstring(state, 2);
  const char* identity = luaL_checkstring(state, 3);
  const char* gate_name = luaL_checkstring(state, 4);
  MemoryGate gate = MemoryGate::Operation;
  if (std::strcmp(gate_name, "MenuStable") == 0) gate = MemoryGate::MenuStable;
  else if (std::strcmp(gate_name, "LevelStable") == 0) gate = MemoryGate::LevelStable;
  else if (std::strcmp(gate_name, "SelectedLanguage") == 0) gate = MemoryGate::SelectedLanguage;
  else if (std::strcmp(gate_name, "Boot") == 0) gate = MemoryGate::Boot;
  else if (std::strcmp(gate_name, "Operation") != 0) return luaL_error(state, "unknown memory gate");
  if (!is_memory_checkpoint(checkpoint)) return luaL_error(state, "unknown memory checkpoint");
  const bool request_known = !lua_isnoneornil(state, 5);
  const bool held_known = !lua_isnoneornil(state, 6);
  const auto request = request_known ? checked_non_negative_integer(state, 5) : 0;
  const auto held = held_known ? checked_non_negative_integer(state, 6) : 0;
  runtime_observe_memory(checkpoint, phase, identity, gate, request, request_known,
      held, held_known, lua_toboolean(state, 7) != 0, true);
  return 0;
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
  value.chinese_ui = table_boolean(state, 1, "chinese_ui", value.chinese_ui);
  value.must_pause = table_boolean(state, 1, "must_pause", value.must_pause);
  value.user_actions_allowed = table_boolean(state, 1, "user_actions_allowed", value.user_actions_allowed);
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

int l_focus_view(lua_State* state) {
  const auto x = luaL_checkinteger(state, 1), y = luaL_checkinteger(state, 2);
  if (x < 0 || x > 639 || y < 0 || y > 479) return luaL_error(state, "focus outside canvas");
  runtime().focus_view(static_cast<int>(x), static_cast<int>(y));
  return 0;
}

int l_scene(lua_State* state) {
  const auto* identity=luaL_checkstring(state,1);
  if(std::strncmp(identity,"level:",6)!=0 && std::strcmp(identity,"menu")!=0)
    return luaL_error(state,"invalid game scene identity");
  if(std::strlen(identity)>=g_observations.scene.size())return luaL_error(state,"scene identity too long");
  if(std::strcmp(g_observations.scene.data(),identity))g_observations.window_scene_changed=true;
  std::snprintf(g_observations.scene.data(),g_observations.scene.size(),"%s",identity);
  return 0;
}
int l_workload(lua_State* state) {
  luaL_checktype(state,1,LUA_TTABLE);
  const auto language = table_string(state,1,"language","unknown");
  const auto date = table_string(state,1,"game_date","unknown");
  const auto speed = table_string(state,1,"speed","unknown");
  const auto voice = table_string(state,1,"voice","unknown");
  boot_log("workload: at_us=%llu scene=%s patients=%lld staff=%lld rooms=%lld speed=\"%s\" hours_per_tick=%lld tick_rate=%lld date=%s camera_x=%lld camera_y=%lld language=%s music_enabled=%d voice=%s",
    static_cast<unsigned long long>(now_us()),g_observations.scene.data(),
    static_cast<long long>(table_integer(state,1,"patients",-1)),
    static_cast<long long>(table_integer(state,1,"staff",-1)),
    static_cast<long long>(table_integer(state,1,"rooms",-1)),
    speed.c_str(),static_cast<long long>(table_integer(state,1,"hours_per_tick",-1)),
    static_cast<long long>(table_integer(state,1,"tick_rate",-1)),date.c_str(),
    static_cast<long long>(table_integer(state,1,"camera_x",0)),
    static_cast<long long>(table_integer(state,1,"camera_y",0)),language.c_str(),
    table_boolean(state,1,"music",false),voice.c_str());
  return 0;
}

int l_text_keyboard(lua_State* state) {
  const char* initial=luaL_checkstring(state,1);
  const auto limit=luaL_checkinteger(state,2);
  if (limit<1 || limit>40) return luaL_error(state,"keyboard limit outside 1..40");
  const char* policy=luaL_optstring(state,3,"filename");
  if (std::strcmp(policy,"filename") && std::strcmp(policy,"player") && std::strcmp(policy,"numbers"))
    return luaL_error(state,"unsupported keyboard field policy");
  char result[164]{}; // 40 Unicode characters plus terminator, bounded stack.
  const bool accepted=runtime().text_keyboard(initial,static_cast<int>(limit),policy,result,sizeof(result));
  lua_pushboolean(state,accepted);
  if(accepted)lua_pushstring(state,result);else lua_pushnil(state);
  return 2;
}

int l_save_io_timing(lua_State* state) {
  const auto dump = luaL_optinteger(state, 1, -1);
  const auto write = luaL_optinteger(state, 2, -1);
  const auto maximum = luaL_optinteger(state, 3, -1);
  const auto flush = luaL_optinteger(state, 4, -1);
  const auto close = luaL_optinteger(state, 5, -1);
  const bool known = dump >= 0 && write >= 0 && maximum >= 0 && flush >= 0 && close >= 0;
  boot_log("save-io: known=%d dump_us=%lld write_us=%lld write_max_us=%lld flush_us=%lld close_ms=%lld io_in_dump=1 close_in_dump=0",
      known ? 1 : 0, static_cast<long long>(dump), static_cast<long long>(write),
      static_cast<long long>(maximum), static_cast<long long>(flush), static_cast<long long>(close));
  return 0; // enclosing closed-file report owns the flush; no extra SD boundary
}

int l_atomic_commit(lua_State* state) {
  const char* temporary = luaL_checkstring(state, 1);
  const char* final_path = luaL_checkstring(state, 2);
  const bool keep_backup = lua_isnoneornil(state, 3) || lua_toboolean(state, 3) != 0;
  const auto started = now_us();
  const AtomicSaveResult result = atomic_commit_existing(temporary, final_path, keep_backup);
  const auto elapsed = now_us() - started;
  // One buffered observation; the enclosing save owner flushes its completion.
  boot_log("save-commit: elapsed_us=%llu ok=%d backup=%d scope=atomic_rename_transaction",
      static_cast<unsigned long long>(elapsed), result.ok ? 1 : 0, keep_backup ? 1 : 0);
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
#if CTH3DS_RESOURCE_EXPERIMENT
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
#else
  (void)event;
  (void)identity;
  (void)success;
  lua_pushboolean(state, 0);
  lua_pushstring(state, "resource_event is invalid in loose mode");
#endif
  return 2;
}

int l_set_notice(lua_State* state) {
  const char* text = luaL_optstring(state, 1, "");
  const bool is_error = lua_toboolean(state, 2) != 0;
  runtime().set_notice(text != nullptr ? text : "", is_error);
  return 0;
}

int l_notice_hint(lua_State* state) {
  lua_pushboolean(state, runtime().set_hint(luaL_checkstring(state, 1)));
  return 1;
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
  set_function(state, "presentation", l_presentation);
  set_function(state, "memory", l_memory);
  set_function(state, "probe_regular_heap", l_probe);
  set_function(state, "resource_memory", l_resource_memory);
  set_function(state, "checkpoint", l_checkpoint);
  set_function(state,"span_begin",l_span_begin);
  set_function(state,"span_end",l_span_end);
  set_function(state,"span_abandon",l_span_abandon);
  set_function(state,"operation_block",l_operation_block);
  set_function(state,"observe_memory",l_observe_memory);
  set_function(state,"diagnostic_line",l_diagnostic_line);
  set_function(state,"prepare_save",l_prepare_save);
  set_function(state,"operation_boundary",l_operation_boundary);
  set_function(state,"flush_observations",l_request_observation_flush);
  set_function(state, "allocation_failure", l_allocation_failure);
  set_function(state, "set_state", l_set_state);
  set_function(state, "request_redraw", l_request_redraw);
  set_function(state, "focus_view", l_focus_view);
  set_function(state, "text_keyboard", l_text_keyboard);
  set_function(state, "workload", l_workload);
  set_function(state, "atomic_commit", l_atomic_commit);
  set_function(state, "save_io_timing", l_save_io_timing);
  set_function(state, "recover_atomic", l_recover_atomic);
  set_function(state, "begin_critical_io", l_begin_critical_io);
  set_function(state, "end_critical_io", l_end_critical_io);
  set_function(state, "resource_event", l_resource_event);
  set_function(state, "scene", l_scene);
  set_function(state, "set_notice", l_set_notice);
  set_function(state, "notice_hint", l_notice_hint);
  set_function(state, "performance", l_performance);
  set_function(state, "cpu_profile", l_cpu_profile);
  set_function(state, "music_state", l_music_state);
  set_function(state, "clock_ms", l_clock_ms);
  set_function(state, "simulation_clock", l_simulation_clock);
  set_function(state, "cpu_phase", l_cpu_phase);
  lua_pushboolean(state,cpu_work.enabled);
  lua_setfield(state,-2,"profiling_enabled");
  set_function(state, "trace_call", l_trace_call);
  set_function(state, "window_identity", l_window_identity);
  set_function(state, "benchmark_enabled", l_benchmark_enabled);
  set_function(state, "runner_context", l_runner_context);
  set_function(state, "runner_frames", l_runner_frames);
  set_function(state, "runner_checkpoint", l_runner_checkpoint);
  set_function(state, "runner_error", l_runner_error);
  set_function(state, "runner_finish", l_runner_finish);
  set_function(state, "benchmark_state", l_benchmark_state);
  set_function(state, "benchmark_active", l_benchmark_active);
  set_function(state, "benchmark_mark", l_benchmark_mark);
  return 1;
}

void reset_runtime_observations() noexcept {
  seal_observation_tail("RESET");
  g_observations.reset(now_us());
}
void register_lua_module(lua_State* state) {
#ifdef CORSIXTH_3DS_GPU
  gpu_submit_sample_end(now_us(),false);
#endif
  reset_runtime_observations();
  g_log_time_us=g_workload_time_us=0;
  g_simulation_clock.reset();
  g_operation_blocked=false;
  reset_benchmark_activation();
  g_presentation_clock.reset();
  cpu_work = {}; cpu_work.clock_us = now_us;
  g_observation_state=state;
  g_memory_pressure={};
  g_memory_sampling={};
  void* allocator_context=nullptr;
  const auto allocator=lua_getallocf(state,&allocator_context);
  if(allocator!=AllocationWatch::allocate) {
    g_lua_allocations.reset(allocator,allocator_context,
        static_cast<std::uint64_t>(lua_gc(state,LUA_GCCOUNT,0))*1024U+
        static_cast<std::uint64_t>(lua_gc(state,LUA_GCCOUNTB,0)));
    lua_setallocf(state,AllocationWatch::allocate,&g_lua_allocations);
  }
  boot_log_open();
  // Diagnostic switches are sampled only at native startup.
  if (auto* marker = std::fopen("sdmc:/3ds/corsixth/profile-off.txt", "rb")) {
    std::fclose(marker);cpu_work.enabled=false;
  }
  // Reference mode retains the full weighted thermal arithmetic for A/B runs.
  if (auto* marker = std::fopen("sdmc:/3ds/corsixth/thermal-profile.txt", "rb")) {
    std::fclose(marker); cpu_work.thermal_phase_profile = true;
  }
  if (auto* marker = std::fopen("sdmc:/3ds/corsixth/thermal-reference.txt", "rb")) {
    std::fclose(marker); cpu_work.thermal_uniform_fast = false; cpu_work.thermal_structure_fast = false;
  }
  boot_log("thermal-mode: uniform_fast=%u phase_profile=%u structure_fast=%u mutation_owners=10 dense_reuse=audited_only publish_each_tick=1 step_frequency=unchanged",
    cpu_work.thermal_uniform_fast ? 1U : 0U, cpu_work.thermal_phase_profile ? 1U : 0U,
    cpu_work.thermal_structure_fast ? 1U : 0U);
  initialize_heap_watermarks();
  g_adapter_crc = crc32(kEmbeddedPlatformLua, std::strlen(kEmbeddedPlatformLua));
  boot_log("CorsixTH 3DS overlay %s, embedded adapter crc %08lx",
           kOverlayVersion, static_cast<unsigned long>(g_adapter_crc));
  boot_log("diagnostics: revision=R75 boundary_schema=1 max_log_bytes=2097152 retained_runs=3 summary_seconds=10 gpu_queue_timing=completed_jobs display_scanout_not_measured=1 gpu_utilization=unknown cpu_utilization=unknown lua_is_heap_subset=1 slow_event_capacity=32 slow_threshold_us=50000 observation_reset=in_place ordinary_observation_us=250000 entity_sample_period=16 staff_parts_sample_period=16 text_cache_limit=2097152 text_cache_ways=2 music=file_wav save_index_buckets=256 save_output=stream16k varint_scratch=stack lua_allocator_watch=1 recovery_reception=bound_callback raw=indexed128 warm_source_bytes=1572864 warm_max_entries=8 warm_trim=save_and_pressure atlas=skyline_lru benchmark_cpu=contained_scopes benchmark_health=humanoids_timer_errors benchmark_boundary=native_us clock_sample=same_window gpu_submit_stride=64 recovery_activity=two_natural_windows thermal_cooling=exact_uint16 sound_read_observation=known_paced warmup_comparability=recorded_work_scene save_io_timing=bounded_native_us capacity_busy=r74-v1 save_io_ab=r75-v1 staff_handoff=room_acceptance");
  boot_log("performance-policy: sparse_entity_index=1 litter_visitor=1 sound_pressure=skip_then_main_thread_gc gc_cooldown_us=2000000 strict_benchmark=1 save_phases=1 screen_layout=unchanged");
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
  g_log.emergency();
  const char* text = reason != nullptr ? reason : "unknown fatal error";
  boot_log("FATAL: %s", text);
  boot_log_memory("FATAL");
  g_observations.terminal = true;
  runtime_flush_observations(true);
  runtime().show_fatal(text);
  if(runner_active()){
    try{runner_finish("FAIL","native_fatal");}catch(...){}
    SDL_Event quit{};quit.type=SDL_QUIT;SDL_PushEvent(&quit);return;
  }
  // Give the player time to read the lower screen before the process leaves.
  for (int i = 0; i < 600 && aptMainLoop(); ++i) {
    hidScanInput();
    if ((hidKeysDown() & (KEY_B | KEY_START)) != 0U) {
      break;
    }
    gspWaitForVBlank();
  }
  SDL_Event quit{};quit.type=SDL_QUIT;SDL_PushEvent(&quit);
  // Main-loop teardown stops audio before closing the shared diagnostic sink.
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

#if CTH3DS_RESOURCE_EXPERIMENT
std::shared_ptr<ResourceTelemetrySink>
make_runtime_resource_telemetry_sink() {
  return std::make_shared<RuntimeResourceTelemetry>();
}

std::shared_ptr<ResourceBudgetGate> make_runtime_resource_budget_gate() {
  return std::make_shared<RuntimeResourceBudgetGate>();
}

#endif
void runtime_set_game_window(SDL_Window* window) noexcept {
  runtime().set_game_window(window);
}
void runtime_diagnostic_line(const char* line, bool flush) noexcept {
  if (g_log.available()) {
    const auto started = now_us();
    g_log.line(line);
    g_log_time_us += now_us() - started;
  }
  // Startup/fallback writes are immediate. Report producers explicitly share
  // their existing final flush; emergency mode still flushes every write.
  if (flush) boot_log_flush();
}
void runtime_diagnostic_flush() noexcept {
  boot_log_flush();
}

void runtime_set_game_canvas(SDL_Surface* surface) noexcept {
  runtime().set_game_canvas(surface);
}

bool runtime_present_game(int cursor_x, int cursor_y) noexcept {
  RuntimeTimingScope top(TimingStage::Top);
  bool success = false;
  try { success = runtime().present_game(cursor_x, cursor_y); }
  catch (...) { boot_log("display: native present exception"); }
  top.finish(success);
  runtime_top_present_complete(success);
  return success;
}

std::uint64_t runtime_span_begin(TimingStage stage) noexcept {
  // Observation only: a sprite/sound Load span is not a game-load operation.
  // Authoritative save/load/lifecycle boundaries own clock interruption.
  return g_observations.timing.begin_span(stage, now_us());
}
bool runtime_span_end(std::uint64_t token, bool success) noexcept {
  return g_observations.timing.end_span(token, now_us(), success);
}
void runtime_begin_frame() noexcept { g_top_present_seen = g_top_present_ok = false; }
void runtime_top_present_complete(bool success) noexcept {
  g_top_present_ok = g_top_present_seen ? g_top_present_ok && success : success;
  g_top_present_seen = true;
}
void runtime_frame_skipped() noexcept {
  const auto now=now_us();
  g_observations.timing.present_complete(now, PresentResult::Skipped);
  g_observations.frame_tail.present(now, PresentResult::Skipped);
}
void runtime_operation_boundary() noexcept {
  g_simulation_clock.interrupt();
  g_observations.window_has_operation=true;
}
void runtime_observe_memory(const char* checkpoint, const char* phase, const char* resource,
    MemoryGate gate, std::uint64_t requested, bool requested_known,
    std::uint64_t held, bool held_known, bool failed, bool opaque) noexcept {
  // Detailed high-frequency sprite/texture/GC/playback and known slice reads
  // are paced. Other sound phases and unknown slice requests stay immediate.
  // Operation, language and sound loading boundaries, large requests and every
  // reported failure remain unconditional. Admission uses fresh snapshots and
  // Lua allocation peaks/failures are counted by AllocationWatch independently.
  const bool frequent=checkpoint && (std::strcmp(checkpoint,"vspr_decode")==0 ||
      std::strcmp(checkpoint,"textures")==0 || std::strcmp(checkpoint,"release")==0 ||
      std::strcmp(checkpoint,"gc")==0 || std::strcmp(checkpoint,"sound_play")==0 ||
      std::strcmp(checkpoint,"sound_release")==0 ||
      (std::strcmp(checkpoint,"sound_read")==0 && requested_known && phase &&
       (std::strcmp(phase,"before")==0 || std::strcmp(phase,"after")==0)));
  if(!g_memory_sampling.take(now_us(),!frequent || failed || (requested_known && requested>=262144)))return;
  CpuWorkScope observation_cost(CpuWork::MemoryObserve);
  update_lua_memory(g_observation_state);
  const auto h = heap_snapshot();
  MemorySample sample{now_us(), h.heap_total, h.arena, h.uordblks, h.fordblks,
      h.linear_total, h.linear_free, h.lua_bytes, g_observation_state != nullptr};
  const auto o = memory_observation(sample, gate, g_current_stage,
      phase ? phase : "unknown", resource ? resource : "unknown",
      requested, requested_known, held, held_known, failed, opaque);
  g_observations.observe(checkpoint,o);
  if(checkpoint && (std::strcmp(checkpoint,"save")==0 || std::strcmp(checkpoint,"reload")==0))
    boot_log("lua-allocation: phase=%s live=%llu peak=%llu failures=%llu failed_request=%llu largest_request=%llu",
      phase?phase:"unknown",static_cast<unsigned long long>(g_lua_allocations.live),
      static_cast<unsigned long long>(g_lua_allocations.peak),static_cast<unsigned long long>(g_lua_allocations.failures),
      static_cast<unsigned long long>(g_lua_allocations.failed_request),static_cast<unsigned long long>(g_lua_allocations.largest_request));
  if (failed) {
    boot_log("allocation-failure: checkpoint=%s phase=%s resource=%s requested=%llu known=%d",
      checkpoint ? checkpoint : "unknown", o.phase.data(), o.resource.data(),
      static_cast<unsigned long long>(requested), requested_known);
    boot_log_memory(g_current_stage);
  }
}
void runtime_note_timer_event() noexcept { ++g_observations.timer_events; }
void runtime_simulation_begin() noexcept { g_simulation_clock.begin(now_us()); }
bool runtime_simulation_step() noexcept { return !g_operation_blocked && g_simulation_clock.take_step(now_us()); }
bool runtime_frame_due(bool changed) noexcept {
  return g_presentation_clock.take(now_us(),changed,
    std::strncmp(g_observations.scene.data(),"level:",6)==0);
}
void runtime_note_logic_callback(bool success) noexcept {
  ++g_observations.logic_callbacks;
  g_simulation_clock.complete_step(success);
  if (!success) { ++g_observations.logic_failures; g_simulation_clock.interrupt(); }
}
void runtime_flush_observations(bool force) noexcept {
  const auto now=now_us();
  if(!g_observations.due(now,force))return;
  const auto phase=g_observations.frame_tail.enter(FramePhase::Flush,now);
  const std::uint32_t reason=(g_observations.flush_requested?1U:0U) |
    (now-g_observations.full_us>=60000000U?2U:0U) |
    (now-g_observations.compact_us>=10000000U?4U:0U) |
    (force?8U:0U) | (g_observations.terminal?16U:0U);
  g_observations.frame_tail.flush_begin(now,reason);
  // Fatal output can be slow or reentrant. Freeze only the D2 record now;
  // the existing frame/clock owner still closes with this same inputs.now.
  if(g_observations.terminal && g_observations.frame_tail.active()) {
    g_observations.frame_tail.flush_action(FrameTail::FlushAction::Terminal);
    g_observations.frame_tail.close(now);
  }
  if(reason & (1U|2U|8U|16U)) {
  const auto cost=g_log.costs();
  boot_log("log-cost: format_calls=%llu format_us=%llu format_max_us=%llu fast=%llu fallback=%llu write_calls=%llu write_us=%llu write_max_us=%llu flush_calls=%llu flush_us=%llu flush_max_us=%llu valid=%d scope=logger_software_calls cumulative=1 preformatted_producer_excluded=1 stdio_write_includes_implicit_flush=1",
    (unsigned long long)cost.format.calls,(unsigned long long)cost.format.total_us,(unsigned long long)cost.format.max_us,
    (unsigned long long)cost.fast,(unsigned long long)cost.fallback,
    (unsigned long long)cost.write.calls,(unsigned long long)cost.write.total_us,(unsigned long long)cost.write.max_us,
    (unsigned long long)cost.flush.calls,(unsigned long long)cost.flush.total_us,(unsigned long long)cost.flush.max_us,cost.valid);
  }
  boot_log("memory-sampling: interval_us=%llu sampled=%llu skipped=%llu forced=%llu failure_and_operation=always large_request_min=262144 peaks=sampled lua_allocator_peak=every_allocation admission=fresh",
      static_cast<unsigned long long>(MemoryObservationGate::interval_us),
      static_cast<unsigned long long>(g_memory_sampling.sampled),static_cast<unsigned long long>(g_memory_sampling.skipped),
      static_cast<unsigned long long>(g_memory_sampling.forced));
  update_lua_memory(g_observation_state);
  const auto m=heap_snapshot();
  const ObservationInputs inputs{now,m.heap_available_estimate,m.heap_available_low_water,
    m.lua_bytes,m.linear_free,g_log_time_us,g_workload_time_us,g_log.flushes(),g_log.bytes(),
    g_log.failed(),g_log.truncated(),g_simulation_clock.statistics()};
  ObservationOutput output{boot_log,boot_log_flush,[](){runtime().log_display_stats();}};
#ifdef CORSIXTH_3DS_GPU
  const bool terminal_sample=g_observations.terminal&&g_observations.sample_open();
  if(terminal_sample) {
    gpu_submit_sample_end(now,false);
    output.flush=[]() noexcept {}; // This synchronous owner flushes both reports below.
  }
#endif
  g_observations.flush(inputs,output,force);
#ifdef CORSIXTH_3DS_GPU
  if(terminal_sample) {gpu_submit_sample_log(false);boot_log_flush();}
#endif
  const auto ended=now_us();
  g_observations.frame_tail.flush_end(ended);
  g_observations.frame_tail.leave(phase,ended);
}

void runtime_after_frame(bool draw_success) noexcept { runtime().after_frame(draw_success); }

[[gnu::noinline]] bool runtime_initialize(lua_State* state, const char* mode) { return runtime().initialize(state,mode); }
[[gnu::noinline]] bool runtime_assert_ready(lua_State* state) {return runtime().assert_ready(state);}
bool runtime_audio_reserve(std::size_t bytes,const char* identity) noexcept {
  const auto h=heap_snapshot();const auto policy=memory_gate_policy(MemoryGate::Operation);
  if(!evaluate_memory_gate(h.heap_total,h.heap_available_estimate,h.linear_total,policy).pass() || bytes>h.heap_available_estimate || !evaluate_memory_gate(h.heap_total,h.heap_available_estimate-bytes,h.linear_total,policy).pass() || policy.probe_reserve_bytes>h.heap_available_estimate-bytes) {
    // Admission check, not an allocation or a held reservation. The actual
    // decoder must still handle allocation failure. Retry after owner eviction;
    // Lua collection is deferred to the next safe main-loop point.
    g_memory_pressure.request(bytes);
    SDL_SetError("audio memory pressure: operation headroom unavailable");
    return false;
  }
  (void)identity;
  return true;
}
FrameTail::Token runtime_phase_begin(FramePhase phase) noexcept {
  return g_observations.frame_tail.enter(phase,g_observations.frame_tail.active()?now_us():0);
}
void runtime_phase_end(FrameTail::Token token) noexcept {
  g_observations.frame_tail.leave(token,g_observations.frame_tail.active()?now_us():0);
}
void runtime_tick(lua_State* state) { RuntimePhaseScope phase(FramePhase::Runtime); RuntimeTimingScope timing(TimingStage::Runtime); runtime().tick(state); timing.finish(runtime().assert_ready(state)); }
void runtime_shutdown(lua_State*) noexcept {
  // Only the new residency ledger seals a partial window here. Existing sample
  // marks, forced-flush rules and shutdown order retain their original owner.
  seal_observation_tail("SHUTDOWN");
  runtime_flush_observations(true); runtime().shutdown(); g_observation_state=nullptr;
}
bool runtime_consume_sdl_event(const SDL_Event& event) noexcept {
  return runtime().consumes_event(event);
}

}  // namespace cth3ds
