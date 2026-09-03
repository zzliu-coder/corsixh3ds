#include "cth3ds/bottom_ui.hpp"

#include <utility>

namespace cth3ds {

BottomUiController::BottomUiController() = default;

void BottomUiController::set_state(BottomUiState state) {
  state_ = std::move(state);
  if (state_.active_tab != BottomTab::Build) {
    build_gesture_.cancel();
    build_drag_started_ = false;
  }
}

Action BottomUiController::action(ActionType type) {
  Action result;
  result.type = type;
  return result;
}

std::vector<Action> BottomUiController::process(const Action& pointer_action) {
  switch (pointer_action.type) {
    case ActionType::PointerDown:
      return handle_pointer_down(pointer_action.position);
    case ActionType::PointerMove:
      return handle_pointer_move(pointer_action.position);
    case ActionType::PointerUp:
      return handle_pointer_up(pointer_action.position);
    case ActionType::Tap:
      return handle_tap(pointer_action.position);
    case ActionType::DoubleTap: {
      Action result = action(ActionType::ShowDetails);
      result.position = pointer_action.position;
      return {result};
    }
    case ActionType::LongPress: {
      Action result = action(ActionType::OpenQuickMenu);
      result.position = pointer_action.position;
      return {result};
    }
    default:
      return {};
  }
}

std::vector<Action> BottomUiController::handle_pointer_down(Vec2i point) {
  pointer_down_ = true;
  pointer_position_ = ScreenLayout::clamp_bottom_touch(point);
  const auto grid = ScreenLayout::build_grid();
  if (state_.active_tab == BottomTab::Build &&
      state_.build_tool == BuildTool::Rooms && grid.bounds.contains(pointer_position_)) {
    build_gesture_.begin(ScreenLayout::point_to_grid(pointer_position_, grid));
    build_drag_started_ = true;
  }
  return {};
}

std::vector<Action> BottomUiController::handle_pointer_move(Vec2i point) {
  pointer_position_ = ScreenLayout::clamp_bottom_touch(point);
  if (build_drag_started_) {
    const auto grid = ScreenLayout::build_grid();
    build_gesture_.update(ScreenLayout::point_to_grid(pointer_position_, grid));
  }
  return {};
}

std::vector<Action> BottomUiController::handle_pointer_up(Vec2i point) {
  pointer_down_ = false;
  pointer_position_ = ScreenLayout::clamp_bottom_touch(point);
  if (build_drag_started_) {
    build_drag_started_ = false;
    const auto grid = ScreenLayout::build_grid();
    const auto room = build_gesture_.finish(ScreenLayout::point_to_grid(pointer_position_, grid));
    if (room) {
      Action result = action(ActionType::BuildRoomRectangle);
      result.rectangle = *room;
      return {result};
    }
  }
  return {};
}

std::vector<Action> BottomUiController::handle_tap(Vec2i point) {
  point = ScreenLayout::clamp_bottom_touch(point);

  for (int i = 0; i < 6; ++i) {
    if (ScreenLayout::tab_rect(i).contains(point)) {
      static constexpr ActionType kTabActions[6] = {
          ActionType::OpenDashboard, ActionType::OpenBuild,
          ActionType::OpenStaff, ActionType::OpenPatients,
          ActionType::OpenFinance, ActionType::OpenMessages,
      };
      state_.active_tab = static_cast<BottomTab>(i);
      return {action(kTabActions[i])};
    }
  }

  for (int i = 0; i < 4; ++i) {
    if (ScreenLayout::action_rect(i).contains(point)) {
      static constexpr ActionType kFooterActions[4] = {
          ActionType::PauseToggle, ActionType::SpeedCycle,
          ActionType::Overview, ActionType::Cancel,
      };
      return {action(kFooterActions[i])};
    }
  }

  const RectI content = ScreenLayout::content_area();
  if (!content.contains(point)) {
    return {};
  }

  switch (state_.active_tab) {
    case BottomTab::Dashboard: {
      const int row = (point.y - content.y) / 38;
      static constexpr ActionType kDashboardActions[4] = {
          ActionType::OpenBank, ActionType::OpenTownMap,
          ActionType::OpenCasebook, ActionType::OpenResearch,
      };
      if (row >= 0 && row < 4) {
        return {action(kDashboardActions[row])};
      }
      break;
    }
    case BottomTab::Build: {
      const auto grid = ScreenLayout::build_grid();
      if (grid.bounds.contains(point)) {
        if (state_.build_tool == BuildTool::Rooms) {
          // Room rectangles are emitted on pointer release after a drag.
          return {};
        }
        Action place = action(ActionType::PlaceItem);
        place.position = ScreenLayout::point_to_grid(point, grid);
        return {place};
      }
      break;
    }
    case BottomTab::Staff:
      return {action(ActionType::OpenStaff)};
    case BottomTab::Patients:
      return {action(ActionType::OpenPatients)};
    case BottomTab::Finance:
      return {action(ActionType::OpenFinance)};
    case BottomTab::Messages:
      return {action(ActionType::OpenMessages)};
  }

  return {};
}

}  // namespace cth3ds
