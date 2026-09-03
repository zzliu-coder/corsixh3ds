#include "cth3ds/screen_layout.hpp"

#include <algorithm>

namespace cth3ds {

Vec2i ScreenLayout::clamp_bottom_touch(Vec2i point) noexcept {
  point.x = clamp_int(point.x, 0, kBottomWidth - 1);
  point.y = clamp_int(point.y, 0, kBottomHeight - 1);
  return point;
}

RectI ScreenLayout::tab_rect(int index, int count) noexcept {
  if (count <= 0 || index < 0 || index >= count) {
    return {};
  }
  const int left = index * kBottomWidth / count;
  const int right = (index + 1) * kBottomWidth / count;
  return {left, tab_bar().y, right - left, tab_bar().h};
}

RectI ScreenLayout::action_rect(int index, int count) noexcept {
  if (count <= 0 || index < 0 || index >= count) {
    return {};
  }
  const int left = index * kBottomWidth / count;
  const int right = (index + 1) * kBottomWidth / count;
  return {left, action_bar().y, right - left, action_bar().h};
}

RectI ScreenLayout::fit_legacy_to_top() noexcept {
  // 640x480 maps to 320x240, centered on the 400-pixel top screen.
  return {40, 0, 320, 240};
}

Vec2f ScreenLayout::legacy_to_top(Vec2f legacy) noexcept {
  const RectI target = fit_legacy_to_top();
  return {
      static_cast<float>(target.x) + legacy.x * static_cast<float>(target.w) /
                                          static_cast<float>(kLegacyWidth),
      static_cast<float>(target.y) + legacy.y * static_cast<float>(target.h) /
                                          static_cast<float>(kLegacyHeight),
  };
}

Vec2f ScreenLayout::top_to_legacy(Vec2f top) noexcept {
  const RectI target = fit_legacy_to_top();
  return {
      (top.x - static_cast<float>(target.x)) * static_cast<float>(kLegacyWidth) /
          static_cast<float>(target.w),
      (top.y - static_cast<float>(target.y)) * static_cast<float>(kLegacyHeight) /
          static_cast<float>(target.h),
  };
}

ScreenLayout::Grid ScreenLayout::build_grid() noexcept {
  const RectI content = content_area();
  Grid grid;
  grid.bounds = {8, content.y + 8, 304, 128};
  grid.cell_size = 16;
  grid.columns = grid.bounds.w / grid.cell_size;
  grid.rows = grid.bounds.h / grid.cell_size;
  return grid;
}

Vec2i ScreenLayout::point_to_grid(Vec2i point, const Grid& grid) noexcept {
  const int local_x = clamp_int(point.x - grid.bounds.x, 0, grid.bounds.w - 1);
  const int local_y = clamp_int(point.y - grid.bounds.y, 0, grid.bounds.h - 1);
  return {local_x / grid.cell_size, local_y / grid.cell_size};
}

RectI ScreenLayout::grid_rect_to_pixels(RectI cells, const Grid& grid) noexcept {
  const int x0 = clamp_int(cells.x, 0, grid.columns);
  const int y0 = clamp_int(cells.y, 0, grid.rows);
  const int x1 = clamp_int(cells.x + cells.w, 0, grid.columns);
  const int y1 = clamp_int(cells.y + cells.h, 0, grid.rows);
  return {
      grid.bounds.x + x0 * grid.cell_size,
      grid.bounds.y + y0 * grid.cell_size,
      std::max(0, x1 - x0) * grid.cell_size,
      std::max(0, y1 - y0) * grid.cell_size,
  };
}

}  // namespace cth3ds

namespace cth3ds {

Vec2i ScreenLayout::bottom_touch_to_legacy(Vec2i touch) noexcept {
  static_assert(kLegacyWidth == kBottomWidth * 2,
                "the lower screen mirror assumes an exact 2:1 reduction");
  static_assert(kLegacyHeight == kBottomHeight * 2,
                "the lower screen mirror assumes an exact 2:1 reduction");
  const Vec2i clamped = clamp_bottom_touch(touch);
  return {clamp_int(clamped.x * 2, 0, kLegacyWidth - 1),
          clamp_int(clamped.y * 2, 0, kLegacyHeight - 1)};
}

}  // namespace cth3ds
