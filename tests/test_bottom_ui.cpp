#include "test_framework.hpp"

#include "cth3ds/bottom_ui.hpp"

namespace {

cth3ds::Action pointer(cth3ds::ActionType type, cth3ds::Vec2i position) {
  cth3ds::Action action;
  action.type = type;
  action.position = position;
  return action;
}

}  // namespace

TEST(bottom_ui_tab_taps_emit_direct_commands) {
  cth3ds::BottomUiController ui;
  for (int i = 0; i < 6; ++i) {
    const auto rect = cth3ds::ScreenLayout::tab_rect(i);
    const auto actions = ui.process(pointer(cth3ds::ActionType::Tap,
                                            {rect.x + rect.w / 2, rect.y + 2}));
    EXPECT_EQ(actions.size(), std::size_t{1});
    EXPECT_EQ(static_cast<int>(ui.state().active_tab), i);
  }
}

TEST(bottom_ui_footer_maps_pause_speed_map_back) {
  cth3ds::BottomUiController ui;
  const cth3ds::ActionType expected[4] = {
      cth3ds::ActionType::PauseToggle,
      cth3ds::ActionType::SpeedCycle,
      cth3ds::ActionType::Overview,
      cth3ds::ActionType::Cancel,
  };
  for (int i = 0; i < 4; ++i) {
    const auto rect = cth3ds::ScreenLayout::action_rect(i);
    const auto actions = ui.process(pointer(cth3ds::ActionType::Tap,
                                            {rect.x + 1, rect.y + 1}));
    EXPECT_EQ(actions.size(), std::size_t{1});
    EXPECT_EQ(actions.front().type, expected[i]);
  }
}

TEST(bottom_ui_room_drag_emits_grid_rectangle) {
  cth3ds::BottomUiController ui;
  cth3ds::BottomUiState state;
  state.active_tab = cth3ds::BottomTab::Build;
  state.build_tool = cth3ds::BuildTool::Rooms;
  ui.set_state(state);
  const auto grid = cth3ds::ScreenLayout::build_grid();
  const cth3ds::Vec2i start{grid.bounds.x + 2 * grid.cell_size + 1,
                            grid.bounds.y + grid.cell_size + 1};
  const cth3ds::Vec2i end{grid.bounds.x + 7 * grid.cell_size + 1,
                          grid.bounds.y + 5 * grid.cell_size + 1};
  EXPECT_TRUE(ui.process(pointer(cth3ds::ActionType::PointerDown, start)).empty());
  EXPECT_TRUE(ui.process(pointer(cth3ds::ActionType::PointerMove, end)).empty());
  const auto actions = ui.process(pointer(cth3ds::ActionType::PointerUp, end));
  EXPECT_EQ(actions.size(), std::size_t{1});
  EXPECT_EQ(actions.front().type, cth3ds::ActionType::BuildRoomRectangle);
  EXPECT_EQ(actions.front().rectangle, (cth3ds::RectI{2, 1, 6, 5}));
}

TEST(bottom_ui_double_tap_opens_details) {
  cth3ds::BottomUiController ui;
  const auto actions = ui.process(pointer(cth3ds::ActionType::DoubleTap, {120, 100}));
  EXPECT_EQ(actions.size(), std::size_t{1});
  EXPECT_EQ(actions.front().type, cth3ds::ActionType::ShowDetails);
}

TEST(bottom_ui_state_equality_gates_repaints) {
  // The 3DS runtime skips a full lower-screen repaint when the state is
  // unchanged, so equality has to cover every field that is drawn.
  cth3ds::BottomUiState left{};
  cth3ds::BottomUiState right{};
  EXPECT_TRUE(left == right);

  right.cash = 1;
  EXPECT_TRUE(left != right);
  right = left;

  right.notice = "SAVE OK";
  EXPECT_TRUE(left != right);
  right = left;

  right.build_tag = "0.5.0 LUA";
  EXPECT_TRUE(left != right);
  right = left;

  right.free_memory_bytes = 1024U;
  EXPECT_TRUE(left != right);
  right = left;

  right.selected_status = "walking";
  EXPECT_TRUE(left != right);
  right = left;

  right.input_context = cth3ds::InputContext::Dialog;
  EXPECT_TRUE(left != right);
}
