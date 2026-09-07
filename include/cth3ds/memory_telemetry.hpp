#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <string_view>

#if !defined(__3DS__)
#include <unistd.h>
#endif

namespace cth3ds {

//! mallinfo::fordblks only counts free bytes inside arenas already obtained by
//! malloc. The environment heap can still contain bytes that malloc has not
//! added to an arena, so fordblks alone is not application headroom.
constexpr std::uint64_t estimate_heap_available(
    std::uint64_t environment_heap_total, std::uint64_t arena_bytes,
    std::uint64_t free_arena_bytes) noexcept {
  const std::uint64_t unclaimed = environment_heap_total > arena_bytes
                                      ? environment_heap_total - arena_bytes
                                      : 0U;
  const std::uint64_t sum =
      free_arena_bytes > std::numeric_limits<std::uint64_t>::max() - unclaimed
          ? std::numeric_limits<std::uint64_t>::max()
          : unclaimed + free_arena_bytes;
  return std::min(environment_heap_total, sum);
}

inline constexpr std::uint64_t kMiB = 1024U * 1024U;
inline constexpr std::uint64_t kMinimumHeapTotal = 52U * kMiB;
inline constexpr std::uint64_t kRequiredLinearTotal = 8U * kMiB;

enum class MemoryGate : std::uint8_t {
  Boot,
  SelectedLanguage,
  MenuStable,
  LevelStable,
  Operation,
};

struct MemoryGatePolicy {
  std::uint64_t maximum_heap_used;
  std::uint64_t minimum_heap_available;
  std::size_t probe_bytes;
  std::size_t probe_reserve_bytes;
};

constexpr MemoryGatePolicy memory_gate_policy(MemoryGate gate) noexcept {
  switch (gate) {
    case MemoryGate::Boot:
      return {12U * kMiB, 40U * kMiB, 8U * kMiB, 4U * kMiB};
    case MemoryGate::SelectedLanguage:
      return {18U * kMiB, 34U * kMiB, 8U * kMiB, 4U * kMiB};
    case MemoryGate::MenuStable:
      return {36U * kMiB, 16U * kMiB, 8U * kMiB, 4U * kMiB};
    case MemoryGate::LevelStable:
      return {44U * kMiB, 8U * kMiB, 4U * kMiB, 4U * kMiB};
    case MemoryGate::Operation:
      return {48U * kMiB, 4U * kMiB, 2U * kMiB, 4U * kMiB};
  }
  return {0U, 0U, 0U, 0U};
}

struct MemoryGateResult {
  std::uint64_t heap_used{0U};
  bool heap_total_ok{false};
  bool linear_total_ok{false};
  bool heap_used_ok{false};
  bool heap_available_ok{false};

  [[nodiscard]] constexpr bool pass() const noexcept {
    return heap_total_ok && linear_total_ok && heap_used_ok && heap_available_ok;
  }
};

constexpr MemoryGateResult evaluate_memory_gate(
    std::uint64_t heap_total, std::uint64_t heap_available,
    std::uint64_t linear_total, const MemoryGatePolicy& policy) noexcept {
  const std::uint64_t clamped_available =
      std::min(heap_total, heap_available);
  const std::uint64_t heap_used = heap_total - clamped_available;
  return {
      heap_used,
      heap_total >= kMinimumHeapTotal,
      linear_total == kRequiredLinearTotal,
      heap_used <= policy.maximum_heap_used,
      clamped_available >= policy.minimum_heap_available,
  };
}

enum class ResourcePool : std::uint8_t {
  Audio,
  Sprite,
  Texture,
  LanguageFont,
  Metadata,
  Scratch,
  Unclassified,
  Count,
};

inline constexpr std::array<std::string_view,
                            static_cast<std::size_t>(ResourcePool::Count)>
    kResourcePoolNames{{"audio", "sprite", "texture", "language_font",
                        "metadata", "scratch", "unclassified"}};

constexpr std::uint64_t resource_pool_limit(ResourcePool pool) noexcept {
  switch (pool) {
    case ResourcePool::Audio: return 3U * kMiB;
    case ResourcePool::Sprite: return 8U * kMiB;
    case ResourcePool::Texture: return 6U * kMiB;
    case ResourcePool::LanguageFont: return 3U * kMiB;
    case ResourcePool::Metadata: return 1U * kMiB;
    case ResourcePool::Scratch: return 1U * kMiB;
    case ResourcePool::Unclassified: return 1U * kMiB;
    case ResourcePool::Count: return 0U;
  }
  return 0U;
}

constexpr bool allocation_fits_pool_budget(std::uint64_t current_bytes,
                                           std::uint64_t requested_bytes,
                                           std::uint64_t cap_bytes) noexcept {
  return current_bytes <= cap_bytes &&
         requested_bytes <= cap_bytes - current_bytes;
}

enum class ResourceMemoryCategory : std::uint8_t {
  Language,
  SoundArchive,
  SoundDecoded,
  VsprTable,
  VsprData,
  VsprDecoded,
  Adapter,
  Menu,
  Level,
  SaveLoad,
  Transition,
  Other,
  Texture,
  Map,
  World,
  Count,
};

inline constexpr std::array<std::string_view,
                            static_cast<std::size_t>(ResourceMemoryCategory::Count)>
    kResourceMemoryCategoryNames{{
        "language",       "sound_archive", "sound_decoded", "vspr_table",
        "vspr_data",      "vspr_decoded",  "adapter",       "menu",
        "level",          "save_load",     "transition",    "other", "texture", "map", "world",
    }};

constexpr ResourceMemoryCategory resource_memory_category(
    std::string_view name) noexcept {
  for (std::size_t index = 0U; index < kResourceMemoryCategoryNames.size(); ++index) {
    if (kResourceMemoryCategoryNames[index] == name) {
      return static_cast<ResourceMemoryCategory>(index);
    }
  }
  return ResourceMemoryCategory::Other;
}

inline constexpr std::array<std::string_view, 27U> kMemoryCheckpointNames{{
    "language_discovery", "language_selected", "sound_archive_read",
    "sound_archive_copy", "sound_decode",      "vspr_table",
    "vspr_data",          "vspr_decode",       "adapter_attach",
    "menu",               "first_level",       "save_load",
    "transition", "sound_index", "sound_read", "sound_play", "sound_evict",
    "sound_release", "textures", "map", "world", "save", "reload", "restore",
    "release", "gc", "allocation_failure",
}};

constexpr bool is_memory_checkpoint(std::string_view name) noexcept {
  for (const std::string_view known : kMemoryCheckpointNames) {
    if (known == name) {
      return true;
    }
  }
  return false;
}

constexpr ResourceMemoryCategory checkpoint_resource_category(
    std::string_view checkpoint) noexcept {
  if (checkpoint == "language_discovery" || checkpoint == "language_selected") {
    return ResourceMemoryCategory::Language;
  }
  if (checkpoint == "sound_archive_read" || checkpoint == "sound_archive_copy") {
    return ResourceMemoryCategory::SoundArchive;
  }
  if (checkpoint == "sound_index" || checkpoint == "sound_read") return ResourceMemoryCategory::SoundArchive;
  if (checkpoint == "sound_play" || checkpoint == "sound_evict" || checkpoint == "sound_release") return ResourceMemoryCategory::SoundDecoded;
  if (checkpoint == "textures") return ResourceMemoryCategory::Texture;
  if (checkpoint == "map") return ResourceMemoryCategory::Map;
  if (checkpoint == "world") return ResourceMemoryCategory::World;
  if (checkpoint == "save" || checkpoint == "reload" || checkpoint == "restore") return ResourceMemoryCategory::SaveLoad;
  if (checkpoint == "sound_decode") return ResourceMemoryCategory::SoundDecoded;
  if (checkpoint == "vspr_table") return ResourceMemoryCategory::VsprTable;
  if (checkpoint == "vspr_data") return ResourceMemoryCategory::VsprData;
  if (checkpoint == "vspr_decode") return ResourceMemoryCategory::VsprDecoded;
  if (checkpoint == "adapter_attach") return ResourceMemoryCategory::Adapter;
  if (checkpoint == "menu") return ResourceMemoryCategory::Menu;
  if (checkpoint == "first_level") return ResourceMemoryCategory::Level;
  if (checkpoint == "save_load") return ResourceMemoryCategory::SaveLoad;
  if (checkpoint == "transition") return ResourceMemoryCategory::Transition;
  return ResourceMemoryCategory::Other;
}

struct ContiguousProbePolicy {
  std::size_t granularity_bytes{64U * 1024U};
  std::size_t minimum_success_bytes{2U * 1024U * 1024U};
  std::size_t reserve_bytes{2U * 1024U * 1024U};
  std::size_t maximum_probe_bytes{8U * 1024U * 1024U};
};

struct ContiguousProbeResult {
  std::size_t verified_bytes{0U};
  std::size_t attempted_limit_bytes{0U};
  std::size_t attempts{0U};
  bool met_minimum{false};
  bool capped{false};
};

using ProbeAllocate = void* (*)(std::size_t bytes, void* context) noexcept;
using ProbeRelease = void (*)(void* allocation, void* context) noexcept;

inline std::size_t runtime_memory_page_size() noexcept {
#if defined(__3DS__)
  return 4096U;
#else
  const long observed = ::sysconf(_SC_PAGESIZE);
  return observed > 0 ? static_cast<std::size_t>(observed) : 4096U;
#endif
}

//! Commit and verify each virtual-memory page in a successful probe. This is
//! intentionally separate from malloc success: lazy page commitment can make
//! an untouched large allocation look usable when it is not.
inline bool touch_probe_pages(
    void* allocation, std::size_t bytes,
    std::size_t page_size = runtime_memory_page_size()) noexcept {
  if (allocation == nullptr || page_size == 0U) return false;
  auto* data = static_cast<volatile std::uint8_t*>(allocation);
  std::uint8_t observed = 0U;
  for (std::size_t offset = 0U; offset < bytes;) {
    const auto pattern = static_cast<std::uint8_t>(
        0xA5U ^ static_cast<std::uint8_t>(offset / page_size));
    data[offset] = pattern;
    observed = static_cast<std::uint8_t>(observed ^ data[offset]);
    if (data[offset] != pattern) return false;
    if (page_size > bytes - offset) break;
    offset += page_size;
  }
  if (bytes != 0U) {
    const auto pattern = static_cast<std::uint8_t>(observed ^ 0x5AU);
    data[bytes - 1U] = pattern;
    if (data[bytes - 1U] != pattern) return false;
  }
  return true;
}

//! Find a verified contiguous-allocation lower bound without consuming the
//! caller's safety reserve. At most one probe allocation is live at a time.
//! The result is deliberately a lower bound: allocator metadata, alignment and
//! later fragmentation can still make a real allocation fail.
inline ContiguousProbeResult probe_largest_contiguous(
    std::size_t reported_headroom_bytes, const ContiguousProbePolicy& policy,
    ProbeAllocate allocate, ProbeRelease release, void* context = nullptr) noexcept {
  ContiguousProbeResult result;
  if (allocate == nullptr || release == nullptr || policy.granularity_bytes == 0U ||
      reported_headroom_bytes <= policy.reserve_bytes) {
    return result;
  }

  const std::size_t safe_available = reported_headroom_bytes - policy.reserve_bytes;
  const std::size_t limit = std::min(safe_available, policy.maximum_probe_bytes);
  const std::size_t units = limit / policy.granularity_bytes;
  result.attempted_limit_bytes = units * policy.granularity_bytes;
  result.capped = safe_available > policy.maximum_probe_bytes;
  if (units == 0U) {
    return result;
  }

  std::size_t low = 0U;
  std::size_t high = units;
  while (low < high) {
    const std::size_t candidate_units = low + (high - low + 1U) / 2U;
    const std::size_t candidate_bytes = candidate_units * policy.granularity_bytes;
    ++result.attempts;
    void* allocation = allocate(candidate_bytes, context);
    if (allocation != nullptr) {
      release(allocation, context);
      low = candidate_units;
    } else {
      high = candidate_units - 1U;
    }
  }

  result.verified_bytes = low * policy.granularity_bytes;
  result.met_minimum = result.verified_bytes >= policy.minimum_success_bytes;
  return result;
}


// Allocation observations are diagnostic subsets. Neither Lua nor held resource
// bytes are added to the allocator total. Opaque temporary bytes stay unknown.
struct MemorySample {
  std::uint64_t timestamp_us{0}, env_heap_total{0}, arena{0}, uordblks{0}, fordblks{0};
  std::uint64_t linear_total{0}, linear_free{0}, lua_bytes{0};
  bool lua_known{false};
  [[nodiscard]] constexpr std::uint64_t heap_available_estimate() const noexcept {
    return estimate_heap_available(env_heap_total, arena, fordblks);
  }
  [[nodiscard]] constexpr std::uint64_t heap_used_estimate() const noexcept {
    return env_heap_total - heap_available_estimate();
  }
};
struct MemoryObservation {
  MemorySample sample{};
  MemoryGate gate{MemoryGate::Operation};
  std::array<char, 32> stage{}, phase{};
  std::array<char, 96> resource{};
  std::uint64_t requested_bytes{0}, held_bytes{0};
  bool requested_known{false}, held_known{false}, allocation_failed{false};
  bool opaque_temporary_unknown{true}, identity_truncated{false};
};
inline MemoryObservation memory_observation(
    const MemorySample& sample, MemoryGate gate, std::string_view stage,
    std::string_view phase, std::string_view resource,
    std::uint64_t requested_bytes = 0, bool requested_known = false,
    std::uint64_t held_bytes = 0, bool held_known = false,
    bool allocation_failed = false, bool opaque_temporary_unknown = true) noexcept {
  MemoryObservation o;
  o.sample = sample; o.gate = gate;
  const auto copy = [&](auto& buffer, std::string_view value) {
    const auto length = std::min(value.size(), buffer.size() - 1U);
    std::copy_n(value.begin(), length, buffer.begin());
    if (length != value.size()) o.identity_truncated = true;
  };
  copy(o.stage, stage); copy(o.phase, phase); copy(o.resource, resource);
  o.requested_bytes = requested_bytes; o.requested_known = requested_known;
  o.held_bytes = held_bytes; o.held_known = held_known;
  o.allocation_failed = allocation_failed;
  o.opaque_temporary_unknown = opaque_temporary_unknown;
  return o;
}
struct MemoryCheckpointSummary {
  std::uint64_t samples{0}, first_us{0}, last_us{0};
  std::uint64_t minimum_heap_available{0}, maximum_heap_used{0};
  std::uint64_t maximum_arena_used{0}, minimum_linear_free{0}, maximum_lua_bytes{0};
  std::uint64_t maximum_requested_bytes{0}, maximum_known_held_bytes{0};
  std::uint64_t allocation_failures{0}, unknown_temporary_samples{0}, lua_known_samples{0};
  // Last observation gives phase/resource/current holdings including release=0.
  // Peaks are sampled lower bounds, with no promise about unobserved allocators.
  MemoryObservation latest{};
};
class MemoryTelemetry {
 public:
  bool observe(std::string_view checkpoint, const MemoryObservation& o) noexcept {
    std::size_t index = 0;
    while (index < kMemoryCheckpointNames.size() && kMemoryCheckpointNames[index] != checkpoint) ++index;
    if (index == kMemoryCheckpointNames.size() || (started_ && o.sample.timestamp_us < last_us_)) {
      ++invalid_events_; return false;
    }
    started_ = true; last_us_ = o.sample.timestamp_us;
    auto& s = checkpoints_[index];
    const auto available = o.sample.heap_available_estimate();
    if (s.samples == 0) {
      s.first_us = o.sample.timestamp_us;
      s.minimum_heap_available = available;
      s.minimum_linear_free = o.sample.linear_free;
    }
    ++s.samples; s.last_us = o.sample.timestamp_us;
    s.minimum_heap_available = std::min(s.minimum_heap_available, available);
    s.minimum_linear_free = std::min(s.minimum_linear_free, o.sample.linear_free);
    s.maximum_heap_used = std::max(s.maximum_heap_used, o.sample.heap_used_estimate());
    s.maximum_arena_used = std::max(s.maximum_arena_used, o.sample.uordblks);
    if (o.sample.lua_known) {
      ++s.lua_known_samples; s.maximum_lua_bytes = std::max(s.maximum_lua_bytes, o.sample.lua_bytes);
    }
    if (o.requested_known) s.maximum_requested_bytes = std::max(s.maximum_requested_bytes, o.requested_bytes);
    if (o.held_known) s.maximum_known_held_bytes = std::max(s.maximum_known_held_bytes, o.held_bytes);
    if (o.allocation_failed) { ++s.allocation_failures; last_failure_ = o; has_failure_ = true; }
    if (o.opaque_temporary_unknown) ++s.unknown_temporary_samples;
    s.latest = o; return true;
  }
  [[nodiscard]] const auto& checkpoints() const noexcept { return checkpoints_; }
  [[nodiscard]] const MemoryObservation& last_failure() const noexcept { return last_failure_; }
  [[nodiscard]] bool has_failure() const noexcept { return has_failure_; }
  [[nodiscard]] std::uint64_t invalid_events() const noexcept { return invalid_events_; }
  void clear() noexcept {
    checkpoints_.fill({}); last_failure_ = {}; invalid_events_ = last_us_ = 0;
    started_ = has_failure_ = false;
  }
 private:
  std::array<MemoryCheckpointSummary, kMemoryCheckpointNames.size()> checkpoints_{};
  MemoryObservation last_failure_{};
  std::uint64_t invalid_events_{0}, last_us_{0};
  bool started_{false}, has_failure_{false};
};

constexpr std::string_view memory_gate_name(MemoryGate gate) noexcept {
  switch (gate) {
    case MemoryGate::Boot: return "Boot";
    case MemoryGate::SelectedLanguage: return "SelectedLanguage";
    case MemoryGate::MenuStable: return "MenuStable";
    case MemoryGate::LevelStable: return "LevelStable";
    case MemoryGate::Operation: return "Operation";
  }
  return "Invalid";
}
// The same explicit gate supplies both the actual probe and its diagnostic.
constexpr ContiguousProbePolicy memory_gate_probe_policy(MemoryGate gate) noexcept {
  const auto p = memory_gate_policy(gate);
  return {64U * 1024U, p.probe_bytes, p.probe_reserve_bytes, p.probe_bytes};
}
inline int format_memory_gate_probe(char* buffer, std::size_t capacity,
                                   MemoryGate gate, const ContiguousProbeResult& result) noexcept {
  const auto name = memory_gate_name(gate);
  const auto policy = memory_gate_probe_policy(gate);
  return std::snprintf(buffer, capacity,
      "gate=%.*s required_probe=%llu verified=%llu attempted_limit=%llu reserve=%llu result=%s",
      static_cast<int>(name.size()), name.data(),
      static_cast<unsigned long long>(policy.minimum_success_bytes),
      static_cast<unsigned long long>(result.verified_bytes),
      static_cast<unsigned long long>(result.attempted_limit_bytes),
      static_cast<unsigned long long>(policy.reserve_bytes),
      result.verified_bytes >= policy.minimum_success_bytes && policy.minimum_success_bytes != 0 ? "PASS" : "FAIL");
}

}  // namespace cth3ds
