#include "cth3ds/input_mapper.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

#include "cth3ds/screen_layout.hpp"

namespace cth3ds {
namespace {

constexpr std::array<Button, 4> kDpadButtons{
    Button::DUp, Button::DDown, Button::DLeft, Button::DRight};
constexpr std::array<Vec2f, 4> kDpadVectors{
    Vec2f{0.0F, -1.0F}, Vec2f{0.0F, 1.0F}, Vec2f{-1.0F, 0.0F}, Vec2f{1.0F, 0.0F}};

int squared_distance(Vec2i a, Vec2i b) noexcept {
  const int dx = a.x - b.x;
  const int dy = a.y - b.y;
  return dx * dx + dy * dy;
}

Action make_simple(ActionType type) {
  Action action;
  action.type = type;
  return action;
}

std::uint64_t deadline(std::uint64_t now, std::uint64_t delay) noexcept {
  const auto maximum = std::numeric_limits<std::uint64_t>::max();
  return delay > maximum - now ? maximum : now + delay;
}

}  // namespace

InputMapper::InputMapper(InputMapperConfig config) : config_(std::move(config)) {
  config_.repeat_interval_us = std::max(std::uint64_t{1}, config_.repeat_interval_us);
}

void InputMapper::reset() noexcept {
  repeat_states_ = {};
  was_touching_ = false;
  touch_start_ = {};
  last_touch_ = {};
  touch_started_us_ = 0;
  long_press_emitted_ = false;
  last_tap_us_ = 0;
  last_tap_position_ = {};
  previous_held_ = 0;
  blocked_buttons_ = 0;
  blocked_touch_ = false;
  blocked_circle_ = false;
  mixed_timestamp_us_ = 0;
}

bool InputMapper::cancel_mixed(const ActionDispatcher& dispatch) {
  // Retain the outstanding release if the bridge fails so the caller can
  // retry cleanup or tear down the UI explicitly.
  if (was_touching_) {
    Action cancel = make_simple(ActionType::PointerUp);
    cancel.value = 1; // Bridge cancels UI press/drag without activating a click.
    if (!dispatch(cancel)) return false;
  }
  reset();
  blocked_buttons_ = std::numeric_limits<std::uint32_t>::max();
  blocked_touch_ = true;
  blocked_circle_ = true;
  return true;
}

bool InputMapper::dispatch_mixed(const RawInputSnapshot& input,
                                  float delta_seconds,
                                  const ContextReader& read_context,
                                  const ActionDispatcher& dispatch) {
  // Clock rewind is a lifecycle boundary. Do not replay held input.
  if (input.timestamp_us < mixed_timestamp_us_ && !cancel_mixed(dispatch)) {
    return false;
  }
  mixed_timestamp_us_ = input.timestamp_us;
  blocked_buttons_ &= input.held;
  blocked_touch_ = blocked_touch_ && input.touching;
  RawInputSnapshot sample = input;
  sample.held &= ~blocked_buttons_;
  sample.down = sample.held & ~previous_held_;
  sample.up = previous_held_ & ~sample.held;
  previous_held_ = sample.held;
  sample.touching = input.touching && !blocked_touch_;

  // Real mouse events only. Gesture-derived taps would duplicate the click.
  const Vec2i point = ScreenLayout::clamp_bottom_touch(sample.touch);
  if (sample.touching && (!was_touching_ || point != last_touch_)) {
    Action motion = make_simple(ActionType::PointerMove);
    motion.position = point;
    if (!dispatch(motion)) return false;
    last_touch_ = point;
  }
  if (sample.touching && !was_touching_) {
    Action down = make_simple(ActionType::PointerDown);
    down.position = point;
    // A failing dispatch may have partly pressed the UI; cancellation releases it.
    was_touching_ = true;
    if (!dispatch(down)) return false;
  } else if (!sample.touching && was_touching_) {
    // No cached coordinate: a D-pad step during a drag may have moved App.ui.
    if (!dispatch(make_simple(ActionType::PointerUp))) return false;
    was_touching_ = false;
  }

  const InputContext context = read_context();
  const Vec2f circle = normalized_circle(sample);
  const bool circle_active = std::abs(circle.x) > 0.0001F || std::abs(circle.y) > 0.0001F;
  blocked_circle_ = blocked_circle_ && circle_active;
  if (circle_active && !blocked_circle_ && std::isfinite(delta_seconds) &&
      delta_seconds > 0.0F) {
    Action pan;
    const bool cursor = context == InputContext::Menu || context == InputContext::Dialog ||
                        context == InputContext::TextInput;
    pan.type = cursor ? ActionType::CursorStep : ActionType::PanCamera;
    const float distance = config_.camera_pixels_per_second *
                           std::min(delta_seconds, 0.1F) / (cursor ? 16.0F : 1.0F);
    pan.vector = {circle.x * distance, circle.y * distance};
    if (!dispatch(pan)) return false;
  }
  std::vector<Action> actions;
  actions.reserve(4);
  append_dpad_actions(actions, sample);
  for (const Action& action : actions) {
    if (!dispatch(action)) return false;
  }

  // Re-read even if there are no face edges. Each face action may replace UI;
  // later buttons in the same sample must see that replacement too.
  InputContext face_context = read_context();
  constexpr std::array<Button, 8> buttons{Button::A, Button::B, Button::X, Button::Y,
                                         Button::Start, Button::Select, Button::L, Button::R};
  for (const Button button : buttons) {
    if (!has_button(sample.down, button)) continue;
    actions.clear();
    RawInputSnapshot edge = sample;
    edge.down = button_mask(button);
    append_button_actions(actions, edge, face_context);
    for (const Action& action : actions) {
      if (!dispatch(action)) return false;
    }
    face_context = read_context();
  }
  return true;
}

Vec2f InputMapper::normalized_circle(const RawInputSnapshot& input) const noexcept {
  const float raw_x = static_cast<float>(input.circle_x);
  const float raw_y = static_cast<float>(input.circle_y);
  const float magnitude = std::sqrt(raw_x * raw_x + raw_y * raw_y);
  const float deadzone = static_cast<float>(std::max(0, config_.circle_deadzone));
  const float maximum = static_cast<float>(std::max(config_.circle_deadzone + 1,
                                                     config_.circle_max));
  if (magnitude <= deadzone) {
    return {};
  }
  const float scaled = clamp_float((magnitude - deadzone) / (maximum - deadzone),
                                   0.0F, 1.0F);
  return {raw_x / magnitude * scaled, -raw_y / magnitude * scaled};
}

std::vector<Action> InputMapper::update(const RawInputSnapshot& input,
                                        InputContext context,
                                        float delta_seconds) {
  std::vector<Action> actions;
  actions.reserve(12);

  const Vec2f circle = normalized_circle(input);
  if (std::abs(circle.x) > 0.0001F || std::abs(circle.y) > 0.0001F) {
    Action pan;
    pan.type = (context == InputContext::Menu || context == InputContext::Dialog ||
                context == InputContext::TextInput)
                   ? ActionType::CursorStep
                   : ActionType::PanCamera;
    pan.vector = {
        circle.x * config_.camera_pixels_per_second * delta_seconds,
        circle.y * config_.camera_pixels_per_second * delta_seconds,
    };
    actions.push_back(pan);
  }

  append_button_actions(actions, input, context);
  append_dpad_actions(actions, input);
  append_touch_actions(actions, input);
  return actions;
}

void InputMapper::append_button_actions(std::vector<Action>& actions,
                                        const RawInputSnapshot& input,
                                        InputContext context) {
  if (has_button(input.down, Button::A)) {
    actions.push_back(make_simple(context == InputContext::PlaceObject
                                      ? ActionType::PlaceItem
                                      : ActionType::Confirm));
  }
  if (has_button(input.down, Button::B)) {
    actions.push_back(make_simple(ActionType::Cancel));
  }
  if (has_button(input.down, Button::X)) {
    actions.push_back(make_simple(
        (context == InputContext::BuildRoom || context == InputContext::PlaceObject)
            ? ActionType::RotateObject
            : ActionType::OpenQuickMenu));
  }
  if (has_button(input.down, Button::Y)) {
    actions.push_back(make_simple(
        (context == InputContext::BuildRoom || context == InputContext::PlaceObject)
            ? ActionType::ToggleWalls
            : ActionType::ShowDetails));
  }
  if (has_button(input.down, Button::Start)) {
    actions.push_back(make_simple(ActionType::PauseToggle));
  }
  if (has_button(input.down, Button::Select)) {
    actions.push_back(make_simple(ActionType::Overview));
  }
  if (has_button(input.down, Button::L)) {
    actions.push_back(make_simple(
        (context == InputContext::BuildRoom || context == InputContext::PlaceObject)
            ? ActionType::PreviousCategory
            : ActionType::ZoomOut));
  }
  if (has_button(input.down, Button::R)) {
    actions.push_back(make_simple(
        (context == InputContext::BuildRoom || context == InputContext::PlaceObject)
            ? ActionType::NextCategory
            : ActionType::ZoomIn));
  }
}

void InputMapper::append_dpad_actions(std::vector<Action>& actions,
                                      const RawInputSnapshot& input) {
  for (std::size_t i = 0; i < kDpadButtons.size(); ++i) {
    const Button button = kDpadButtons[i];
    RepeatState& state = repeat_states_[i];
    const bool held = has_button(input.held, button);
    const bool down = has_button(input.down, button);
    const bool up = has_button(input.up, button);

    if (down) {
      Action action;
      action.type = ActionType::CursorStep;
      action.vector = kDpadVectors[i];
      actions.push_back(action);
      state.active = true;
      state.next_repeat_us = deadline(input.timestamp_us, config_.repeat_delay_us);
    } else if (held && state.active && input.timestamp_us >= state.next_repeat_us) {
      Action action;
      action.type = ActionType::CursorStep;
      action.vector = kDpadVectors[i];
      action.repeated = true;
      actions.push_back(action);
      const auto remainder = (input.timestamp_us - state.next_repeat_us) %
                             config_.repeat_interval_us;
      state.next_repeat_us = deadline(input.timestamp_us,
                                      config_.repeat_interval_us - remainder);
    }

    if (up || !held) {
      state.active = false;
      state.next_repeat_us = 0;
    }
  }
}

void InputMapper::append_touch_actions(std::vector<Action>& actions,
                                       const RawInputSnapshot& input) {
  const Vec2i point = ScreenLayout::clamp_bottom_touch(input.touch);
  const int slop_squared = config_.gesture_slop_px * config_.gesture_slop_px;

  if (input.touching && !was_touching_) {
    was_touching_ = true;
    touch_start_ = point;
    last_touch_ = point;
    touch_started_us_ = input.timestamp_us;
    long_press_emitted_ = false;

    Action action;
    action.type = ActionType::PointerDown;
    action.position = point;
    actions.push_back(action);
    return;
  }

  if (input.touching && was_touching_) {
    if (point != last_touch_) {
      Action action;
      action.type = ActionType::PointerMove;
      action.position = point;
      action.vector = {static_cast<float>(point.x - last_touch_.x),
                       static_cast<float>(point.y - last_touch_.y)};
      actions.push_back(action);
      last_touch_ = point;
    }

    if (!long_press_emitted_ &&
        squared_distance(point, touch_start_) <= slop_squared &&
        input.timestamp_us >= touch_started_us_ + config_.long_press_us) {
      Action action;
      action.type = ActionType::LongPress;
      action.position = point;
      actions.push_back(action);
      long_press_emitted_ = true;
    }
    return;
  }

  if (!input.touching && was_touching_) {
    was_touching_ = false;
    Action up_action;
    up_action.type = ActionType::PointerUp;
    up_action.position = last_touch_;
    actions.push_back(up_action);

    if (!long_press_emitted_ &&
        squared_distance(last_touch_, touch_start_) <= slop_squared) {
      Action tap;
      tap.position = last_touch_;
      const bool is_double = last_tap_us_ != 0 &&
                             input.timestamp_us <= last_tap_us_ + config_.double_tap_us &&
                             squared_distance(last_tap_position_, last_touch_) <= slop_squared;
      tap.type = is_double ? ActionType::DoubleTap : ActionType::Tap;
      actions.push_back(tap);
      if (is_double) {
        last_tap_us_ = 0;
      } else {
        last_tap_us_ = input.timestamp_us;
        last_tap_position_ = last_touch_;
      }
    }
  }
}

}  // namespace cth3ds
