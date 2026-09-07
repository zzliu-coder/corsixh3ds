#include "cth3ds/framebuffer_scaler.hpp"

#include <algorithm>
#include <array>
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

namespace {
std::uint32_t output_pixel(std::uint32_t pixel, bool swap_bytes) noexcept {
  if (!swap_bytes) return pixel;
  return ((pixel & 0xffU) << 24U) | ((pixel & 0xff00U) << 8U) |
         ((pixel >> 8U) & 0xff00U) | (pixel >> 24U);
}
}  // namespace

Vec2i follow_pointer_viewport(Vec2i origin, Vec2i pointer,
    int source_width, int source_height, int view_width, int view_height,
    int margin) noexcept {
  if (view_width <= 0 || view_height <= 0 || source_width < view_width ||
      source_height < view_height) return {};
  const int mx = std::clamp(margin, 0, (view_width - 1) / 2);
  const int my = std::clamp(margin, 0, (view_height - 1) / 2);
  pointer.x = std::clamp(pointer.x, 0, source_width - 1);
  pointer.y = std::clamp(pointer.y, 0, source_height - 1);
  origin.x = std::clamp(origin.x, 0, source_width - view_width);
  origin.y = std::clamp(origin.y, 0, source_height - view_height);
  if (pointer.x < origin.x + mx) origin.x = pointer.x - mx;
  else if (pointer.x >= origin.x + view_width - mx)
    origin.x = pointer.x - view_width + mx + 1;
  if (pointer.y < origin.y + my) origin.y = pointer.y - my;
  else if (pointer.y >= origin.y + view_height - my)
    origin.y = pointer.y - view_height + my + 1;
  return {std::clamp(origin.x, 0, source_width - view_width),
          std::clamp(origin.y, 0, source_height - view_height)};
}

bool scale_rgba_view(const std::uint32_t* source, int source_width,
    int source_height, int source_pitch_pixels, RectI view,
    std::uint32_t* destination, int width, int height,
    int destination_pitch_pixels, bool swap_bytes) noexcept {
  if (!source || !destination || source == destination || view.x < 0 || view.y < 0 ||
      view.w <= 0 || view.h <= 0 || source_width < view.w || source_height < view.h ||
      view.x > source_width - view.w || view.y > source_height - view.h ||
      source_pitch_pixels < source_width || destination_pitch_pixels < width) return false;
  if (view.w == width && view.h == height)
    return copy_rgba_view(source, source_width, source_height, source_pitch_pixels,
        {view.x, view.y}, destination, width, height, destination_pitch_pixels, swap_bytes);
  std::array<std::uint16_t, kMaxScalerAxis> columns{}, rows{};
  if (!build_nearest_axis_table(view.w, width, columns.data(), kMaxScalerAxis) ||
      !build_nearest_axis_table(view.h, height, rows.data(), kMaxScalerAxis)) return false;
  for (int y = 0; y < height; ++y) {
    const auto* row = source + static_cast<std::ptrdiff_t>(view.y + rows[static_cast<std::size_t>(y)]) * source_pitch_pixels + view.x;
    auto* out = destination + static_cast<std::ptrdiff_t>(y) * destination_pitch_pixels;
    for (int x = 0; x < width; ++x) out[x] = output_pixel(row[columns[static_cast<std::size_t>(x)]], swap_bytes);
  }
  return true;
}

bool copy_rgba_view(const std::uint32_t* source, int source_width,
    int source_height, int source_pitch_pixels, Vec2i origin,
    std::uint32_t* destination, int view_width, int view_height,
    int destination_pitch_pixels, bool swap_bytes) noexcept {
  if (!source || !destination || source == destination || view_width <= 0 ||
      view_height <= 0 || source_width < view_width || source_height < view_height ||
      source_pitch_pixels < source_width || destination_pitch_pixels < view_width ||
      origin.x < 0 || origin.y < 0 || origin.x > source_width - view_width ||
      origin.y > source_height - view_height) return false;
  for (int y = 0; y < view_height; ++y) {
    const auto* row = source + static_cast<std::ptrdiff_t>(y + origin.y) *
                               source_pitch_pixels + origin.x;
    auto* out = destination + static_cast<std::ptrdiff_t>(y) * destination_pitch_pixels;
    for (int x = 0; x < view_width; ++x) out[x] = output_pixel(row[x], swap_bytes);
  }
  return true;
}

bool halve_rgba(const std::uint32_t* source, int source_width,
                int source_height, int source_pitch_pixels,
                std::uint32_t* destination,
                int destination_pitch_pixels, bool swap_bytes) noexcept {
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
      destination_row[x] = output_pixel(source_row[x * 2], swap_bytes);
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
