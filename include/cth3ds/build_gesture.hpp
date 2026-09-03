#pragma once

#include <optional>

#include "cth3ds/types.hpp"

namespace cth3ds {

class BuildGesture {
 public:
  explicit BuildGesture(int minimum_width = 2, int minimum_height = 2);

  void begin(Vec2i grid_cell) noexcept;
  void update(Vec2i grid_cell) noexcept;
  [[nodiscard]] std::optional<RectI> finish(Vec2i grid_cell) noexcept;
  void cancel() noexcept;

  [[nodiscard]] bool active() const noexcept { return active_; }
  [[nodiscard]] RectI preview() const noexcept;

 private:
  [[nodiscard]] RectI normalized(Vec2i end) const noexcept;

  bool active_{false};
  Vec2i start_{};
  Vec2i current_{};
  int minimum_width_{2};
  int minimum_height_{2};
};

}  // namespace cth3ds
