#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "cth3ds/events.hpp"

namespace cth3ds {

struct InputMapperConfig {
  int circle_deadzone{24};
  int circle_max{156};
  float camera_pixels_per_second{360.0F};
  std::uint64_t repeat_delay_us{330000};
  std::uint64_t repeat_interval_us{90000};
  std::uint64_t long_press_us{450000};
  std::uint64_t double_tap_us{280000};
  int gesture_slop_px{6};
};

class InputMapper {
 public:
  explicit InputMapper(InputMapperConfig config = {});

  [[nodiscard]] std::vector<Action> update(const RawInputSnapshot& input,
                                           InputContext context,
                                           float delta_seconds);
  void reset() noexcept;

 private:
  struct RepeatState {
    bool active{false};
    std::uint64_t next_repeat_us{0};
  };

  [[nodiscard]] Vec2f normalized_circle(const RawInputSnapshot& input) const noexcept;
  void append_button_actions(std::vector<Action>& actions,
                             const RawInputSnapshot& input,
                             InputContext context);
  void append_dpad_actions(std::vector<Action>& actions,
                           const RawInputSnapshot& input);
  void append_touch_actions(std::vector<Action>& actions,
                            const RawInputSnapshot& input);

  InputMapperConfig config_{};
  std::array<RepeatState, 4> repeat_states_{};
  bool was_touching_{false};
  Vec2i touch_start_{};
  Vec2i last_touch_{};
  std::uint64_t touch_started_us_{0};
  bool long_press_emitted_{false};
  std::uint64_t last_tap_us_{0};
  Vec2i last_tap_position_{};
};

}  // namespace cth3ds
