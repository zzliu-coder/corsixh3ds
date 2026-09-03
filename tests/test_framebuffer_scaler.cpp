#include "test_framework.hpp"

#include <cstdint>
#include <vector>

#include "cth3ds/framebuffer_scaler.hpp"

TEST(framebuffer_scaler_top_screen_preserves_aspect_ratio) {
  EXPECT_EQ(cth3ds::calculate_letterbox_viewport(640, 480, 400, 240),
            (cth3ds::RectI{40, 0, 320, 240}));
}

TEST(framebuffer_scaler_bottom_screen_is_native) {
  EXPECT_EQ(cth3ds::calculate_letterbox_viewport(320, 240, 320, 240),
            (cth3ds::RectI{0, 0, 320, 240}));
}

TEST(framebuffer_scaler_rejects_invalid_dimensions) {
  EXPECT_TRUE(cth3ds::calculate_letterbox_viewport(0, 1, 2, 2).empty());
  EXPECT_TRUE(cth3ds::calculate_letterbox_viewport(1, 1, -1, 2).empty());
}

TEST(framebuffer_scaler_clears_bars_and_maps_nearest_pixels) {
  const std::uint32_t source[] = {
      0xFF000001U, 0xFF000002U,
      0xFF000003U, 0xFF000004U,
  };
  std::vector<std::uint32_t> destination(8U, 0U);
  EXPECT_TRUE(cth3ds::scale_nearest_letterboxed_rgba(
      source, 2, 2, 2, destination.data(), 4, 2, 4, 0xFFABCDEFU));
  EXPECT_EQ(destination[0], 0xFFABCDEFU);
  EXPECT_EQ(destination[1], 0xFF000001U);
  EXPECT_EQ(destination[2], 0xFF000002U);
  EXPECT_EQ(destination[3], 0xFFABCDEFU);
  EXPECT_EQ(destination[4], 0xFFABCDEFU);
  EXPECT_EQ(destination[5], 0xFF000003U);
  EXPECT_EQ(destination[6], 0xFF000004U);
  EXPECT_EQ(destination[7], 0xFFABCDEFU);
}

TEST(framebuffer_scaler_validates_pitch_and_pointers) {
  std::uint32_t pixel = 0U;
  EXPECT_FALSE(cth3ds::scale_nearest_letterboxed_rgba(
      nullptr, 1, 1, 1, &pixel, 1, 1, 1));
  EXPECT_FALSE(cth3ds::scale_nearest_letterboxed_rgba(
      &pixel, 2, 1, 1, &pixel, 1, 1, 1));
}

TEST(framebuffer_scaler_axis_table_matches_division) {
  std::uint16_t table[cth3ds::kMaxScalerAxis];
  EXPECT_TRUE(cth3ds::build_nearest_axis_table(640, 320, table,
                                               cth3ds::kMaxScalerAxis));
  for (int i = 0; i < 320; ++i) {
    EXPECT_EQ(static_cast<int>(table[i]), (i * 640) / 320);
  }
  EXPECT_TRUE(cth3ds::build_nearest_axis_table(17, 240, table,
                                               cth3ds::kMaxScalerAxis));
  for (int i = 0; i < 240; ++i) {
    EXPECT_EQ(static_cast<int>(table[i]), (i * 17) / 240);
  }
}

TEST(framebuffer_scaler_axis_table_rejects_oversized_spans) {
  std::uint16_t table[8];
  EXPECT_FALSE(cth3ds::build_nearest_axis_table(10, 9, table, 8));
  EXPECT_FALSE(cth3ds::build_nearest_axis_table(0, 4, table, 8));
  EXPECT_FALSE(cth3ds::build_nearest_axis_table(4, 0, table, 8));
}

TEST(framebuffer_scaler_detects_integer_downscale) {
  int factor = 0;
  EXPECT_TRUE(cth3ds::is_integer_downscale(640, 320, &factor));
  EXPECT_EQ(factor, 2);
  EXPECT_TRUE(cth3ds::is_integer_downscale(320, 320, &factor));
  EXPECT_EQ(factor, 1);
  EXPECT_FALSE(cth3ds::is_integer_downscale(641, 320, &factor));
}

TEST(framebuffer_scaler_top_screen_mapping_is_two_to_one) {
  // The real CorsixTH case. Every destination pixel must sample an even
  // source coordinate, i.e. an exact 2:1 reduction with no resampling drift.
  std::uint16_t columns[cth3ds::kMaxScalerAxis];
  const cth3ds::RectI viewport =
      cth3ds::calculate_letterbox_viewport(640, 480, 400, 240);
  EXPECT_EQ(viewport, (cth3ds::RectI{40, 0, 320, 240}));
  EXPECT_TRUE(cth3ds::build_nearest_axis_table(640, viewport.w, columns,
                                               cth3ds::kMaxScalerAxis));
  for (int i = 0; i < viewport.w; ++i) {
    EXPECT_EQ(static_cast<int>(columns[i]), i * 2);
  }
}

TEST(framebuffer_scaler_centre_crop_for_top_screen) {
  // 640x480 CorsixTH frame on the 400x240 top screen: the whole screen is
  // covered by native-resolution pixels taken from the middle of the frame.
  const cth3ds::CropView view = cth3ds::calculate_centre_crop(640, 480, 400, 240);
  EXPECT_EQ(view.destination, (cth3ds::RectI{0, 0, 400, 240}));
  EXPECT_EQ(view.source_origin, (cth3ds::Vec2i{120, 120}));
}

TEST(framebuffer_scaler_centre_crop_letterboxes_a_small_source) {
  const cth3ds::CropView view = cth3ds::calculate_centre_crop(100, 80, 400, 240);
  EXPECT_EQ(view.destination, (cth3ds::RectI{150, 80, 100, 80}));
  EXPECT_EQ(view.source_origin, (cth3ds::Vec2i{0, 0}));
}

TEST(framebuffer_scaler_halve_takes_every_second_pixel) {
  const std::uint32_t source[] = {
      1, 2, 3, 4,
      5, 6, 7, 8,
      9, 10, 11, 12,
      13, 14, 15, 16,
  };
  std::vector<std::uint32_t> destination(4U, 0U);
  EXPECT_TRUE(cth3ds::halve_rgba(source, 4, 4, 4, destination.data(), 2));
  EXPECT_EQ(destination[0], 1U);
  EXPECT_EQ(destination[1], 3U);
  EXPECT_EQ(destination[2], 9U);
  EXPECT_EQ(destination[3], 11U);
}

TEST(framebuffer_scaler_halve_rejects_bad_arguments) {
  std::uint32_t pixel = 0U;
  EXPECT_FALSE(cth3ds::halve_rgba(nullptr, 4, 4, 4, &pixel, 2));
  EXPECT_FALSE(cth3ds::halve_rgba(&pixel, 1, 4, 4, &pixel, 2));
  EXPECT_FALSE(cth3ds::halve_rgba(&pixel, 4, 4, 2, &pixel, 2));
}
