#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
struct BlitCounters {
  std::uint64_t direct{}, opaque{}, fallback{}, promoted{}, clipped{}, pixels{};
  std::uint64_t live_bytes{}, peak_bytes{}, live_images{};
  bool enabled{true};
  std::uint64_t probe_reference_us[2]{}, probe_fast_us[2]{};
  bool probe_ran{}, probe_pixels{}, reference_forced{};
  std::uint64_t span_bytes{};
};
inline BlitCounters blit_counters;
// Main-thread counters only. Pixel payloads stay in the existing 6 MiB cache.
struct RenderWork {
  std::uint64_t draws{}, flipped_fallback{}, texture_creates{}, decoded_pixels{};
  std::uint64_t flip_hits{}, flip_misses{}, flip_pixels_saved{};
  std::uint64_t cache_evictions{}, cache_bytes{}, cache_peak_bytes{};
  bool fast_flip_enabled{true};
  void reset_counts() noexcept {
    const bool enabled = fast_flip_enabled;
    const auto bytes = cache_bytes;
    *this = {}; fast_flip_enabled = enabled;
    cache_bytes = cache_peak_bytes = bytes;
  }
};
inline RenderWork render_work{};

// Used once on cache creation. No second image or per-frame scratch buffer.
inline void flip_rgba_in_place(std::uint32_t* pixels, int width, int height,
                               bool horizontal, bool vertical) noexcept {
  if (!pixels || width <= 0 || height <= 0) return;
  if (horizontal) for (int y = 0; y < height; ++y) {
    auto* row = pixels + static_cast<std::ptrdiff_t>(y) * width;
    std::reverse(row, row + width);
  }
  if (vertical) for (int y = 0; y < height / 2; ++y) {
    auto* a = pixels + static_cast<std::ptrdiff_t>(y) * width;
    auto* b = pixels + static_cast<std::ptrdiff_t>(height - 1 - y) * width;
    std::swap_ranges(a, a + width, b);
  }
}
} // namespace cth3ds
