#include "test_framework.hpp"

#include <algorithm>

#include "cth3ds/input_mapper.hpp"

namespace {

bool has_action(const std::vector<cth3ds::Action>& actions,
                cth3ds::ActionType type) {
  return std::any_of(actions.begin(), actions.end(),
                     [type](const cth3ds::Action& action) {
                       return action.type == type;
                     });
}

}  // namespace

TEST(input_mapper_circle_deadzone_and_pan) {
  cth3ds::InputMapper mapper;
  cth3ds::RawInputSnapshot input;
  input.timestamp_us = 1000;
  input.circle_x = 10;
  EXPECT_TRUE(mapper.update(input, cth3ds::InputContext::World, 0.016F).empty());
  input.circle_x = 156;
  const auto actions = mapper.update(input, cth3ds::InputContext::World, 0.5F);
  EXPECT_EQ(actions.size(), std::size_t{1});
  EXPECT_EQ(actions.front().type, cth3ds::ActionType::PanCamera);
  EXPECT_NEAR(actions.front().vector.x, 180.0, 0.01);
}

TEST(input_mapper_build_buttons_use_contextual_actions) {
  cth3ds::InputMapper mapper;
  cth3ds::RawInputSnapshot input;
  input.timestamp_us = 1000;
  input.down = cth3ds::button_mask(cth3ds::Button::X) |
               cth3ds::button_mask(cth3ds::Button::Y) |
               cth3ds::button_mask(cth3ds::Button::L) |
               cth3ds::button_mask(cth3ds::Button::R);
  const auto actions = mapper.update(input, cth3ds::InputContext::BuildRoom, 0.016F);
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::RotateObject));
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::ToggleWalls));
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::PreviousCategory));
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::NextCategory));
}

TEST(input_mapper_dpad_repeat_respects_delay) {
  cth3ds::InputMapper mapper;
  cth3ds::RawInputSnapshot input;
  input.timestamp_us = 1000000;
  input.down = cth3ds::button_mask(cth3ds::Button::DRight);
  input.held = input.down;
  auto actions = mapper.update(input, cth3ds::InputContext::Menu, 0.016F);
  EXPECT_EQ(actions.size(), std::size_t{1});
  EXPECT_FALSE(actions.front().repeated);

  input.down = 0;
  input.timestamp_us = 1200000;
  actions = mapper.update(input, cth3ds::InputContext::Menu, 0.016F);
  EXPECT_TRUE(actions.empty());

  input.timestamp_us = 1340000;
  actions = mapper.update(input, cth3ds::InputContext::Menu, 0.016F);
  EXPECT_EQ(actions.size(), std::size_t{1});
  EXPECT_TRUE(actions.front().repeated);
}

TEST(input_mapper_tap_double_tap_and_long_press) {
  cth3ds::InputMapper mapper;
  cth3ds::RawInputSnapshot input;
  input.timestamp_us = 1000000;
  input.touching = true;
  input.touch = {50, 60};
  auto actions = mapper.update(input, cth3ds::InputContext::World, 0.016F);
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::PointerDown));

  input.timestamp_us = 1100000;
  input.touching = false;
  actions = mapper.update(input, cth3ds::InputContext::World, 0.016F);
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::PointerUp));
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::Tap));

  input.timestamp_us = 1200000;
  input.touching = true;
  actions = mapper.update(input, cth3ds::InputContext::World, 0.016F);
  input.timestamp_us = 1250000;
  input.touching = false;
  actions = mapper.update(input, cth3ds::InputContext::World, 0.016F);
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::DoubleTap));

  input.timestamp_us = 2000000;
  input.touching = true;
  input.touch = {100, 100};
  (void)mapper.update(input, cth3ds::InputContext::World, 0.016F);
  input.timestamp_us = 2500000;
  actions = mapper.update(input, cth3ds::InputContext::World, 0.016F);
  EXPECT_TRUE(has_action(actions, cth3ds::ActionType::LongPress));
}


namespace {
// Explicit UI/native seam: this models the bridge contract, not App or SDL.
struct MixedFixture {
  cth3ds::InputMapper mapper;
  cth3ds::RawInputSnapshot input;
  cth3ds::Vec2i cursor{320, 240};
  cth3ds::InputContext context{cth3ds::InputContext::World};
  std::vector<cth3ds::Action> actions;
  std::vector<cth3ds::Vec2i> clicks;
  std::vector<int> order;
  std::function<void(const cth3ds::Action&)> after;
  bool pressed{false};

  bool dispatch(const cth3ds::Action& action) {
    using cth3ds::ActionType;
    actions.push_back(action);
    order.push_back(static_cast<int>(action.type));
    if (action.type == ActionType::PointerMove) {
      cursor = {action.position.x * 2, action.position.y * 2};
    } else if (action.type == ActionType::CursorStep) {
      cursor.x = std::clamp(cursor.x + static_cast<int>(action.vector.x * 16), 0, 639);
      cursor.y = std::clamp(cursor.y + static_cast<int>(action.vector.y * 16), 0, 479);
    } else if (action.type == ActionType::PointerDown) {
      pressed = true;
    } else if (action.type == ActionType::PointerUp) {
      pressed = false;
    } else if (action.type == ActionType::Confirm || action.type == ActionType::PlaceItem ||
               action.type == ActionType::ShowDetails || action.type == ActionType::Cancel) {
      clicks.push_back(cursor);
    }
    if (after) after(action);
    return true;
  }
  bool run() {
    return mapper.dispatch_mixed(input, 0.016F, [&]() {
      order.push_back(-1);
      return context;
    }, [&](const auto& action) { return dispatch(action); });
  }
  bool cancel() {
    return mapper.cancel_mixed([&](const auto& action) { return dispatch(action); });
  }
};
}  // namespace

TEST(input_mapper_mixed_touch_direction_faces_share_current_point) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.touching = true;
  f.input.touch = {100, 100};
  f.input.held = button_mask(Button::DRight) | button_mask(Button::A) |
                 button_mask(Button::B) | button_mask(Button::Y);
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.cursor, (Vec2i{216, 200}));
  EXPECT_EQ(f.clicks.size(), std::size_t{3});
  for (const auto point : f.clicks) EXPECT_EQ(point, (Vec2i{216, 200}));
  EXPECT_EQ(f.order[0], static_cast<int>(ActionType::PointerMove));
  EXPECT_EQ(f.order[1], static_cast<int>(ActionType::PointerDown));
  EXPECT_EQ(f.order[2], -1);
  EXPECT_EQ(f.order[3], static_cast<int>(ActionType::CursorStep));
  EXPECT_EQ(f.order[4], -1);
  EXPECT_EQ(f.order[5], static_cast<int>(ActionType::Confirm));
}

TEST(input_mapper_mixed_reads_scene_after_touch_direction_and_each_face) {
  using namespace cth3ds;
  MixedFixture f;
  f.context = InputContext::Menu;
  f.after = [&](const Action& a) {
    if (a.type == ActionType::PointerDown) f.context = InputContext::BuildRoom;
    if (a.type == ActionType::CursorStep) f.context = InputContext::PlaceObject;
    if (a.type == ActionType::PlaceItem) f.context = InputContext::Dialog;
    if (a.type == ActionType::Cancel) f.context = InputContext::World;
  };
  f.input.touching = true;
  f.input.held = button_mask(Button::DRight) | button_mask(Button::A) |
                 button_mask(Button::B) | button_mask(Button::Y);
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(has_action(f.actions, ActionType::PlaceItem));
  EXPECT_TRUE(has_action(f.actions, ActionType::ShowDetails));
  EXPECT_FALSE(has_action(f.actions, ActionType::ToggleWalls));
}

TEST(input_mapper_mixed_all_contexts_move_visible_cursor) {
  using namespace cth3ds;
  for (const auto context : {InputContext::World, InputContext::Menu, InputContext::Dialog,
                             InputContext::TextInput, InputContext::BuildRoom,
                             InputContext::PlaceObject}) {
    MixedFixture f;
    f.context = context;
    f.cursor = {200, 200};
    f.input.held = button_mask(Button::DRight) | button_mask(Button::A);
    EXPECT_TRUE(f.run());
    EXPECT_EQ(f.cursor, (Vec2i{216, 200}));
    EXPECT_EQ(f.clicks.front(), f.cursor);
    EXPECT_TRUE(has_action(f.actions, context == InputContext::PlaceObject ?
                            ActionType::PlaceItem : ActionType::Confirm));
  }
}

TEST(input_mapper_mixed_touch_clamps_and_drag_release_keeps_ui_point) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.touching = true;
  f.input.touch = {-20, 400};
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.cursor, (Vec2i{0, 478}));
  f.input.touch = {400, -20};
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.cursor, (Vec2i{638, 0}));
  f.input.held = button_mask(Button::DRight) | button_mask(Button::DUp);
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.cursor, (Vec2i{639, 0}));
  EXPECT_TRUE(f.pressed);
  f.input.touching = false;
  f.input.touch = {0, 0}; // HID has no valid position on release.
  EXPECT_TRUE(f.run());
  EXPECT_FALSE(f.pressed);
  EXPECT_EQ(f.cursor, (Vec2i{639, 0}));
  EXPECT_FALSE(has_action(f.actions, ActionType::Tap));
  EXPECT_FALSE(has_action(f.actions, ActionType::DoubleTap));
  EXPECT_FALSE(has_action(f.actions, ActionType::LongPress));
}

TEST(input_mapper_mixed_held_is_authority_and_duplicate_snapshot_has_no_edges) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.down = button_mask(Button::A); // stale SDL/HID edge is ignored.
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.empty());
  f.input.held = button_mask(Button::A) | button_mask(Button::DRight);
  f.input.down = 0;
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.size(), std::size_t{2});
  f.actions.clear();
  f.input.down = f.input.held;
  f.input.up = f.input.held;
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.empty());
  f.input.held = 0;
  EXPECT_TRUE(f.run());
  f.input.held = button_mask(Button::A);
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.size(), std::size_t{1});
}

TEST(input_mapper_mixed_repeat_is_bounded_after_long_stall) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.timestamp_us = 1000000;
  f.input.held = button_mask(Button::DRight);
  EXPECT_TRUE(f.run());
  f.actions.clear();
  f.input.timestamp_us = 1329999;
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.empty());
  f.input.timestamp_us = 1330000;
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.size(), std::size_t{1});
  EXPECT_TRUE(f.actions.front().repeated);
  f.actions.clear();
  f.input.timestamp_us = 1000000000000ULL;
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.size(), std::size_t{1});
  f.actions.clear();
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.empty());
}

TEST(input_mapper_mixed_cancel_releases_drag_and_requires_neutral) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.touching = true;
  f.input.touch = {100, 100};
  f.input.held = button_mask(Button::DRight) | button_mask(Button::A);
  f.input.circle_x = 156;
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.cancel());
  EXPECT_FALSE(f.pressed);
  EXPECT_EQ(f.cursor, (Vec2i{216, 200}));
  f.actions.clear();
  f.input.timestamp_us = 5000000;
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.empty());
  f.input.touching = false;
  f.input.held = 0;
  f.input.circle_x = 0;
  EXPECT_TRUE(f.run());
  f.input.touching = true;
  f.input.held = button_mask(Button::A);
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.pressed);
  EXPECT_EQ(f.actions.size(), std::size_t{3});
}

TEST(input_mapper_mixed_restore_without_prior_suspend_blocks_held_controls) {
  using namespace cth3ds;
  MixedFixture f;
  EXPECT_TRUE(f.cancel());
  EXPECT_TRUE(f.cancel());
  f.input.held = button_mask(Button::A);
  f.input.touching = true;
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.empty());
  f.mapper.reset(); // A new UI epoch may accept a fresh initial sample.
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.size(), std::size_t{3});
}

TEST(input_mapper_mixed_dispatch_failure_stops_batch_and_release_can_retry) {
  using namespace cth3ds;
  InputMapper mapper;
  RawInputSnapshot input;
  input.touching = true;
  input.held = button_mask(Button::A);
  int reads = 0;
  std::vector<ActionType> events;
  EXPECT_FALSE(mapper.dispatch_mixed(input, 0.016F, [&]() {
    ++reads; return InputContext::World;
  }, [&](const Action& a) {
    events.push_back(a.type);
    return a.type != ActionType::PointerDown;
  }));
  EXPECT_EQ(reads, 0);
  EXPECT_EQ(events.size(), std::size_t{2});
  EXPECT_FALSE(mapper.cancel_mixed([](const Action&) { return false; }));
  EXPECT_TRUE(mapper.cancel_mixed([&](const Action& a) {
    EXPECT_EQ(a.type, ActionType::PointerUp); return true;
  }));
}

TEST(input_mapper_mixed_clock_rewind_cancels_repeat_and_drag) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.timestamp_us = 5000000;
  f.input.touching = true;
  f.input.held = button_mask(Button::DRight);
  EXPECT_TRUE(f.run());
  f.actions.clear();
  f.input.timestamp_us = 1;
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.size(), std::size_t{1});
  EXPECT_EQ(f.actions.front().type, ActionType::PointerUp);
  EXPECT_FALSE(f.pressed);
}

TEST(input_mapper_mixed_zero_repeat_interval_finishes_and_circle_units_match) {
  using namespace cth3ds;
  InputMapperConfig config;
  config.repeat_interval_us = 0;
  MixedFixture f;
  f.mapper = InputMapper(config);
  f.context = InputContext::Menu;
  f.input.circle_x = 156;
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions.front().type, ActionType::CursorStep);
  EXPECT_NEAR(f.actions.front().vector.x * 16, 5.76, 0.001);
  f.input.circle_x = 0;
  f.input.held = button_mask(Button::DRight);
  EXPECT_TRUE(f.run());
  f.input.timestamp_us = 1000000000000ULL;
  EXPECT_TRUE(f.run());
  EXPECT_TRUE(f.actions.back().repeated);
}

TEST(input_mapper_mixed_touch_release_changes_scene_before_same_batch_buttons) {
  using namespace cth3ds;
  MixedFixture f;
  f.input.touching = true;
  EXPECT_TRUE(f.run());
  f.after = [&](const Action& action) {
    if (action.type == ActionType::PointerUp) {
      f.context = InputContext::PlaceObject;
      f.cursor = {400, 300}; // A replacement UI supplies the current point.
    }
  };
  f.actions.clear();
  f.input.touching = false;
  f.input.held = button_mask(Button::DLeft) | button_mask(Button::A);
  EXPECT_TRUE(f.run());
  EXPECT_EQ(f.actions[0].type, ActionType::PointerUp);
  EXPECT_EQ(f.actions[2].type, ActionType::PlaceItem);
  EXPECT_EQ(f.clicks.back(), (Vec2i{384, 300}));
}

TEST(input_mapper_mixed_failed_direction_dispatch_prevents_face_action) {
  using namespace cth3ds;
  InputMapper mapper;
  RawInputSnapshot input;
  input.held = button_mask(Button::DRight) | button_mask(Button::A);
  int calls = 0;
  EXPECT_FALSE(mapper.dispatch_mixed(input, 0.016F,
      [] { return InputContext::World; }, [&](const Action& action) {
        ++calls;
        EXPECT_EQ(action.type, ActionType::CursorStep);
        return false;
      }));
  EXPECT_EQ(calls, 1);
}
