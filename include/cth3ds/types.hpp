#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace cth3ds {

struct Vec2i {
  int x{0};
  int y{0};

  constexpr bool operator==(const Vec2i& other) const noexcept {
    return x == other.x && y == other.y;
  }
  constexpr bool operator!=(const Vec2i& other) const noexcept {
    return !(*this == other);
  }
};

struct Vec2f {
  float x{0.0F};
  float y{0.0F};
};

struct RectI {
  int x{0};
  int y{0};
  int w{0};
  int h{0};

  constexpr bool operator==(const RectI& other) const noexcept {
    return x == other.x && y == other.y && w == other.w && h == other.h;
  }
  constexpr bool operator!=(const RectI& other) const noexcept {
    return !(*this == other);
  }

  [[nodiscard]] constexpr int right() const noexcept { return x + w; }
  [[nodiscard]] constexpr int bottom() const noexcept { return y + h; }
  [[nodiscard]] constexpr bool empty() const noexcept { return w <= 0 || h <= 0; }
  [[nodiscard]] constexpr bool contains(Vec2i p) const noexcept {
    return p.x >= x && p.y >= y && p.x < right() && p.y < bottom();
  }
};

[[nodiscard]] constexpr int clamp_int(int value, int low, int high) noexcept {
  return value < low ? low : (value > high ? high : value);
}

[[nodiscard]] inline float clamp_float(float value, float low, float high) noexcept {
  return std::max(low, std::min(value, high));
}

[[nodiscard]] inline float length(Vec2f v) noexcept {
  return std::sqrt(v.x * v.x + v.y * v.y);
}

}  // namespace cth3ds
