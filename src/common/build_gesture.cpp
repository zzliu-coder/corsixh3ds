#include "cth3ds/build_gesture.hpp"

#include <algorithm>

namespace cth3ds {

BuildGesture::BuildGesture(int minimum_width, int minimum_height)
    : minimum_width_(std::max(1, minimum_width)),
      minimum_height_(std::max(1, minimum_height)) {}

void BuildGesture::begin(Vec2i grid_cell) noexcept {
  active_ = true;
  start_ = grid_cell;
  current_ = grid_cell;
}

void BuildGesture::update(Vec2i grid_cell) noexcept {
  if (active_) {
    current_ = grid_cell;
  }
}

std::optional<RectI> BuildGesture::finish(Vec2i grid_cell) noexcept {
  if (!active_) {
    return std::nullopt;
  }
  current_ = grid_cell;
  active_ = false;
  RectI room = normalized(current_);
  if (room.w < minimum_width_ || room.h < minimum_height_) {
    return std::nullopt;
  }
  return room;
}

void BuildGesture::cancel() noexcept {
  active_ = false;
}

RectI BuildGesture::preview() const noexcept {
  return active_ ? normalized(current_) : RectI{};
}

RectI BuildGesture::normalized(Vec2i end) const noexcept {
  const int left = std::min(start_.x, end.x);
  const int top = std::min(start_.y, end.y);
  const int right = std::max(start_.x, end.x);
  const int bottom = std::max(start_.y, end.y);
  return {left, top, right - left + 1, bottom - top + 1};
}

}  // namespace cth3ds
