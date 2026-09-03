#include "test_framework.hpp"

#include <string_view>

#include "cth3ds/action_codec.hpp"

TEST(action_codec_covers_representative_actions) {
  EXPECT_EQ(cth3ds::action_name(cth3ds::ActionType::PanCamera), std::string_view("pan_camera"));
  EXPECT_EQ(cth3ds::action_name(cth3ds::ActionType::BuildRoomRectangle),
             std::string_view("build_room_rectangle"));
  EXPECT_EQ(cth3ds::action_name(cth3ds::ActionType::LifecycleExit),
             std::string_view("lifecycle_exit"));
}

TEST(action_codec_round_trips_input_context_names) {
  using cth3ds::InputContext;
  for (const auto context : {InputContext::World, InputContext::BuildRoom,
                             InputContext::PlaceObject, InputContext::Menu,
                             InputContext::Dialog, InputContext::TextInput}) {
    EXPECT_EQ(cth3ds::parse_context(cth3ds::context_name(context)), context);
  }
  EXPECT_EQ(cth3ds::parse_context("invalid"), InputContext::World);
}
