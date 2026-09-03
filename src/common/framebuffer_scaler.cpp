#include "cth3ds/framebuffer_scaler.hpp"

#include <algorithm>
#include <cstddef>

namespace cth3ds {

RectI calculate_letterbox_viewport(int source_width, int source_height,
                                   int destination_width,
                                   int destination_height) noexcept {
  if (source_width <= 0 || source_height <= 0 || destination_width <= 0 ||
      destination_height <= 0) {
    return {};
  }

  // Compare the two candidate scales without floating point. This is exactly
  // the decision used in the SDL2 N3DS patch.
  int viewport_width = destination_width;
  int viewport_height = static_cast<int>(
      (static_cast<std::int64_t>(source_height) * destination_width) /
      source_width);
  if (viewport_height > destination_height) {
    viewport_height = destination_height;
    viewport_width = static_cast<int>(
        (static_cast<std::int64_t>(source_width) * destination_height) /
        source_height);
  }
  viewport_width = std::max(1, std::min(viewport_width, destination_width));
  viewport_height = std::max(1, std::min(viewport_height, destination_height));
  return {(destination_width - viewport_width) / 2,
          (destination_height - viewport_height) / 2, viewport_width,
          viewport_height};
}

bool build_nearest_axis_table(int source_span, int viewport_span,
                              std::uint16_t* table,
                              int table_capacity) noexcept {
  if (table == nullptr || source_span <= 0 || viewport_span <= 0 ||
      viewport_span > table_capacity || viewport_span > kMaxScalerAxis ||
      source_span > 0xFFFF) {
    return false;
  }
  // Incremental Bresenham-style stepping. It reproduces
  //   source = (destination * source_span) / viewport_span
  // exactly, without a division (let alone a 64-bit division) per pixel, which
  // matters because the ARM11 in an Old 3DS has no hardware divider.
  int source = 0;
  int remainder = 0;
  for (int destination = 0; destination < viewport_span; ++destination) {
    table[destination] = static_cast<std::uint16_t>(source);
    remainder += source_span;
    while (remainder >= viewport_span) {
      remainder -= viewport_span;
      ++source;
    }
  }
  return true;
}

bool is_integer_downscale(int source_span, int viewport_span,
                          int* factor) noexcept {
  if (source_span <= 0 || viewport_span <= 0 || source_span % viewport_span != 0) {
    return false;
  }
  if (factor != nullptr) {
    *factor = source_span / viewport_span;
  }
  return true;
}

CropView calculate_centre_crop(int source_width, int source_height,
                               int destination_width,
                               int destination_height) noexcept {
  if (source_width <= 0 || source_height <= 0 || destination_width <= 0 ||
      destination_height <= 0) {
    return {};
  }
  const int visible_width = std::min(source_width, destination_width);
  const int visible_height = std::min(source_height, destination_height);
  CropView view;
  view.destination = {(destination_width - visible_width) / 2,
                      (destination_height - visible_height) / 2, visible_width,
                      visible_height};
  view.source_origin = {(source_width - visible_width) / 2,
                        (source_height - visible_height) / 2};
  return view;
}

bool halve_rgba(const std::uint32_t* source, int source_width,
                int source_height, int source_pitch_pixels,
                std::uint32_t* destination,
                int destination_pitch_pixels) noexcept {
  if (source == nullptr || destination == nullptr || source_width < 2 ||
      source_height < 2 || source_pitch_pixels < source_width ||
      destination_pitch_pixels < source_width / 2) {
    return false;
  }
  const int output_width = source_width / 2;
  const int output_height = source_height / 2;
  for (int y = 0; y < output_height; ++y) {
    const auto* source_row =
        source + static_cast<std::ptrdiff_t>(y) * 2 * source_pitch_pixels;
    auto* destination_row =
        destination + static_cast<std::ptrdiff_t>(y) * destination_pitch_pixels;
    for (int x = 0; x < output_width; ++x) {
      destination_row[x] = source_row[x * 2];
    }
  }
  return true;
}

bool scale_nearest_letterboxed_rgba(
    const std::uint32_t* source, int source_width, int source_height,
    int source_pitch_pixels, std::uint32_t* destination,
    int destination_width, int destination_height,
    int destination_pitch_pixels, std::uint32_t clear_pixel) noexcept {
  if (source == nullptr || destination == nullptr || source_width <= 0 ||
      source_height <= 0 || destination_width <= 0 || destination_height <= 0 ||
      source_pitch_pixels < source_width ||
      destination_pitch_pixels < destination_width) {
    return false;
  }

  const RectI viewport = calculate_letterbox_viewport(
      source_width, source_height, destination_width, destination_height);
  if (viewport.empty()) {
    return false;
  }

  std::uint16_t columns[kMaxScalerAxis];
  std::uint16_t rows[kMaxScalerAxis];
  if (!build_nearest_axis_table(source_width, viewport.w, columns,
                                kMaxScalerAxis) ||
      !build_nearest_axis_table(source_height, viewport.h, rows,
                                kMaxScalerAxis)) {
    return false;
  }

  for (int y = 0; y < destination_height; ++y) {
    auto* row = destination + static_cast<std::ptrdiff_t>(y) *
                                  destination_pitch_pixels;
    std::fill(row, row + destination_width, clear_pixel);
  }

  for (int destination_y = 0; destination_y < viewport.h; ++destination_y) {
    const auto* source_row =
        source + static_cast<std::ptrdiff_t>(rows[destination_y]) *
                     source_pitch_pixels;
    auto* destination_row =
        destination + static_cast<std::ptrdiff_t>(viewport.y + destination_y) *
                          destination_pitch_pixels +
        viewport.x;
    for (int destination_x = 0; destination_x < viewport.w; ++destination_x) {
      destination_row[destination_x] = source_row[columns[destination_x]];
    }
  }
  return true;
}

}  // namespace cth3ds
