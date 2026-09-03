#include "test_framework.hpp"

#include "cth3ds/build_gesture.hpp"

TEST(build_gesture_normalizes_reverse_drag) {
  cth3ds::BuildGesture gesture;
  gesture.begin({8, 6});
  gesture.update({3, 2});
  const cth3ds::RectI preview = gesture.preview();
  EXPECT_EQ(preview, (cth3ds::RectI{3, 2, 6, 5}));
  const auto result = gesture.finish({3, 2});
  EXPECT_TRUE(result.has_value());
  EXPECT_EQ(*result, (cth3ds::RectI{3, 2, 6, 5}));
  EXPECT_FALSE(gesture.active());
}

TEST(build_gesture_rejects_room_smaller_than_minimum) {
  cth3ds::BuildGesture gesture(2, 2);
  gesture.begin({4, 4});
  const auto result = gesture.finish({4, 5});
  EXPECT_FALSE(result.has_value());
}

TEST(build_gesture_cancel_removes_preview) {
  cth3ds::BuildGesture gesture;
  gesture.begin({1, 1});
  gesture.update({5, 5});
  gesture.cancel();
  EXPECT_FALSE(gesture.active());
  EXPECT_TRUE(gesture.preview().empty());
}
