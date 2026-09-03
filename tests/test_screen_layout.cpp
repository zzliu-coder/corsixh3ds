#include "test_framework.hpp"

#include "cth3ds/screen_layout.hpp"

TEST(screen_layout_tabs_cover_entire_width) {
  int cursor = 0;
  for (int i = 0; i < 6; ++i) {
    const cth3ds::RectI rect = cth3ds::ScreenLayout::tab_rect(i);
    EXPECT_EQ(rect.x, cursor);
    cursor += rect.w;
  }
  EXPECT_EQ(cursor, cth3ds::ScreenLayout::kBottomWidth);
}

TEST(screen_layout_legacy_letterbox_is_centered) {
  const cth3ds::RectI fitted = cth3ds::ScreenLayout::fit_legacy_to_top();
  EXPECT_EQ(fitted.x, 40);
  EXPECT_EQ(fitted.y, 0);
  EXPECT_EQ(fitted.w, 320);
  EXPECT_EQ(fitted.h, 240);
  const cth3ds::Vec2f top = cth3ds::ScreenLayout::legacy_to_top({320.0F, 240.0F});
  EXPECT_NEAR(top.x, 200.0, 0.001);
  EXPECT_NEAR(top.y, 120.0, 0.001);
  const cth3ds::Vec2f legacy = cth3ds::ScreenLayout::top_to_legacy(top);
  EXPECT_NEAR(legacy.x, 320.0, 0.001);
  EXPECT_NEAR(legacy.y, 240.0, 0.001);
}

TEST(screen_layout_build_grid_snaps_and_clamps) {
  const auto grid = cth3ds::ScreenLayout::build_grid();
  EXPECT_EQ(grid.columns, 19);
  EXPECT_EQ(grid.rows, 8);
  EXPECT_EQ(cth3ds::ScreenLayout::point_to_grid({-20, -20}, grid),
            (cth3ds::Vec2i{0, 0}));
  EXPECT_EQ(cth3ds::ScreenLayout::point_to_grid({999, 999}, grid),
            (cth3ds::Vec2i{18, 7}));
  const auto pixels = cth3ds::ScreenLayout::grid_rect_to_pixels({2, 1, 4, 3}, grid);
  EXPECT_EQ(pixels.x, grid.bounds.x + 2 * grid.cell_size);
  EXPECT_EQ(pixels.y, grid.bounds.y + grid.cell_size);
  EXPECT_EQ(pixels.w, 4 * grid.cell_size);
  EXPECT_EQ(pixels.h, 3 * grid.cell_size);
}

TEST(screen_layout_bottom_touch_maps_to_the_game_frame) {
  // The lower screen mirrors the 640x480 frame at half size, so the mapping
  // has to be an exact doubling for touch to land where the player looks.
  EXPECT_EQ(cth3ds::ScreenLayout::bottom_touch_to_legacy({0, 0}),
            (cth3ds::Vec2i{0, 0}));
  EXPECT_EQ(cth3ds::ScreenLayout::bottom_touch_to_legacy({160, 120}),
            (cth3ds::Vec2i{320, 240}));
  EXPECT_EQ(cth3ds::ScreenLayout::bottom_touch_to_legacy({319, 239}),
            (cth3ds::Vec2i{638, 478}));
}

TEST(screen_layout_bottom_touch_clamps_out_of_range_input) {
  EXPECT_EQ(cth3ds::ScreenLayout::bottom_touch_to_legacy({-40, -10}),
            (cth3ds::Vec2i{0, 0}));
  EXPECT_EQ(cth3ds::ScreenLayout::bottom_touch_to_legacy({5000, 5000}),
            (cth3ds::Vec2i{638, 478}));
}
