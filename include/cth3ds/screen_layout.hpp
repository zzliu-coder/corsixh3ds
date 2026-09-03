#pragma once

#include "cth3ds/types.hpp"

namespace cth3ds {

class ScreenLayout {
 public:
  static constexpr int kTopWidth = 400;
  static constexpr int kTopHeight = 240;
  static constexpr int kBottomWidth = 320;
  static constexpr int kBottomHeight = 240;
  static constexpr int kLegacyWidth = 640;
  static constexpr int kLegacyHeight = 480;

  static constexpr RectI top_screen() noexcept { return {0, 0, kTopWidth, kTopHeight}; }
  static constexpr RectI bottom_screen() noexcept { return {0, 0, kBottomWidth, kBottomHeight}; }
  static constexpr RectI status_bar() noexcept { return {0, 0, kBottomWidth, 24}; }
  static constexpr RectI tab_bar() noexcept { return {0, 24, kBottomWidth, 32}; }
  static constexpr RectI content_area() noexcept { return {0, 56, kBottomWidth, 152}; }
  static constexpr RectI action_bar() noexcept { return {0, 208, kBottomWidth, 32}; }

  [[nodiscard]] static Vec2i clamp_bottom_touch(Vec2i point) noexcept;
  [[nodiscard]] static RectI tab_rect(int index, int count = 6) noexcept;
  [[nodiscard]] static RectI action_rect(int index, int count = 4) noexcept;
  [[nodiscard]] static RectI fit_legacy_to_top() noexcept;
  [[nodiscard]] static Vec2f legacy_to_top(Vec2f legacy) noexcept;
  [[nodiscard]] static Vec2f top_to_legacy(Vec2f top) noexcept;

  //! Where a lower-screen touch lands in CorsixTH's 640x480 frame.
  //!
  //! The lower screen shows that frame at exactly half size, so this is a
  //! plain doubling: no rounding, no offset, and whatever is under the
  //! player's finger is the pixel the game receives.
  [[nodiscard]] static Vec2i bottom_touch_to_legacy(Vec2i touch) noexcept;

  struct Grid {
    RectI bounds{};
    int cell_size{16};
    int columns{0};
    int rows{0};
  };

  [[nodiscard]] static Grid build_grid() noexcept;
  [[nodiscard]] static Vec2i point_to_grid(Vec2i point, const Grid& grid) noexcept;
  [[nodiscard]] static RectI grid_rect_to_pixels(RectI cells, const Grid& grid) noexcept;
};

}  // namespace cth3ds
