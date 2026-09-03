#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
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
  Count,
};

inline constexpr std::array<std::string_view,
                            static_cast<std::size_t>(ResourceMemoryCategory::Count)>
    kResourceMemoryCategoryNames{{
        "language",       "sound_archive", "sound_decoded", "vspr_table",
        "vspr_data",      "vspr_decoded",  "adapter",       "menu",
        "level",          "save_load",     "transition",    "other",
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

inline constexpr std::array<std::string_view, 13U> kMemoryCheckpointNames{{
    "language_discovery", "language_selected", "sound_archive_read",
    "sound_archive_copy", "sound_decode",      "vspr_table",
    "vspr_data",          "vspr_decode",       "adapter_attach",
    "menu",               "first_level",       "save_load",
    "transition",
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

}  // namespace cth3ds
