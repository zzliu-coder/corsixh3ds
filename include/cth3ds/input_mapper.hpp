#pragma once

#include <array>
#include <cstdint>
#include <functional>
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
  // Game mirror path. Both callbacks run synchronously on the Lua/UI thread.
  // read_context reads Platform:inputState; dispatch must finish App:dispatch
  // before returning true. False stops the batch and requires cancel_mixed.
  // Sample HID once; held/touching are authoritative, down/up are ignored.
  // Pointer positions are bottom pixels; the bridge doubles/clamps once.
  // CursorStep is in 16-logical-pixel units; clicks and PointerUp use App.ui's
  // current point. PointerUp.value==1 cancels UI press/drag without clicking.
  // No UI coordinate is retained here. Do not mix update() and
  // dispatch_mixed() within an epoch (update is the legacy panel path).
  using ContextReader = std::function<InputContext()>;
  using ActionDispatcher = std::function<bool(const Action&)>;
  [[nodiscard]] bool dispatch_mixed(const RawInputSnapshot& input,
                                    float delta_seconds,
                                    const ContextReader& read_context,
                                    const ActionDispatcher& dispatch);
  // Invoke on the normal UI thread before suspend, and on restore even if
  // suspend+restore arrived together. Release a drag at the current UI point;
  // ignore controls held across cancellation until each returns to neutral.
  [[nodiscard]] bool cancel_mixed(const ActionDispatcher& dispatch);
  // Fresh epoch only; lifecycle transitions use cancel_mixed instead.
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
  std::uint32_t previous_held_{0};
  std::uint32_t blocked_buttons_{0};
  bool blocked_touch_{false};
  bool blocked_circle_{false};
  std::uint64_t mixed_timestamp_us_{0};
};

}  // namespace cth3ds
