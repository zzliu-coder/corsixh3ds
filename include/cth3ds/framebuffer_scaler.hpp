#pragma once

#include <cstdint>

#include "cth3ds/types.hpp"

namespace cth3ds {

// Maximum destination width the column table can describe. The 3DS top screen
// is 400 pixels wide, so 512 leaves room without a heap allocation.
inline constexpr int kMaxScalerAxis = 512;

// Returns the largest integer-pixel viewport that preserves the source aspect
// ratio inside the destination. Coordinates are expressed in the destination's
// normal left-to-right, top-to-bottom coordinate system.
[[nodiscard]] RectI calculate_letterbox_viewport(int source_width,
                                                  int source_height,
                                                  int destination_width,
                                                  int destination_height) noexcept;

// Nearest-neighbour source index table for one axis: entry i holds the source
// coordinate sampled by destination coordinate i, for i in [0, viewport_span).
// Returns false when the arguments are out of range or the span exceeds
// kMaxScalerAxis. This is the single definition of the sampling grid; the
// SDL2/N3DS framebuffer patch embeds the same expression so that the on-device
// output is bit-identical to what the host tests verify.
[[nodiscard]] bool build_nearest_axis_table(int source_span, int viewport_span,
                                            std::uint16_t* table,
                                            int table_capacity) noexcept;

// True when the mapping degenerates to "take every Nth pixel", which the
// device path implements without any per-pixel index lookup. 640x480 -> 320x240
// (the CorsixTH top screen case) hits this with a factor of 2.
[[nodiscard]] bool is_integer_downscale(int source_span, int viewport_span,
                                        int* factor) noexcept;

// Where a 1:1 centre crop of `source` lands inside `destination`, together with
// the source pixel it starts from. Used for the top screen, which shows the
// hospital at native pixel size: a 640x480 CorsixTH frame is larger than the
// 400x240 top screen in both axes, so cropping keeps every pixel sharp instead
// of throwing half of them away.
struct CropView {
  RectI destination{};   // where the copied region lands on screen
  Vec2i source_origin{}; // first source pixel copied
};

[[nodiscard]] CropView calculate_centre_crop(int source_width, int source_height,
                                             int destination_width,
                                             int destination_height) noexcept;

// Exact 2:1 reduction of an RGBA8888 image, taking every second pixel on both
// axes. This is what the lower screen shows: a whole 640x480 CorsixTH frame in
// 320x240, so touch coordinates map back by a plain doubling.
[[nodiscard]] bool halve_rgba(const std::uint32_t* source, int source_width,
                              int source_height, int source_pitch_pixels,
                              std::uint32_t* destination,
                              int destination_pitch_pixels) noexcept;

// Nearest-neighbour RGBA8888 scaler used by host tests and the simulator. The
// SDL2/N3DS dependency patch implements the same mapping for 16/24/32-bit
// framebuffers.
[[nodiscard]] bool scale_nearest_letterboxed_rgba(
    const std::uint32_t* source, int source_width, int source_height,
    int source_pitch_pixels, std::uint32_t* destination,
    int destination_width, int destination_height, int destination_pitch_pixels,
    std::uint32_t clear_pixel = 0xFF000000U) noexcept;

}  // namespace cth3ds
