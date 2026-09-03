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
