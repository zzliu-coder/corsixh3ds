#include "cth3ds/action_codec.hpp"

#include <array>

namespace cth3ds {
namespace {

struct ActionName {
  ActionType type;
  std::string_view name;
};

constexpr std::array<ActionName, 52> kActionNames{{
    {ActionType::None, "none"},
    {ActionType::PanCamera, "pan_camera"},
    {ActionType::CursorStep, "cursor_step"},
    {ActionType::PointerDown, "pointer_down"},
    {ActionType::PointerMove, "pointer_move"},
    {ActionType::PointerUp, "pointer_up"},
    {ActionType::Tap, "tap"},
    {ActionType::DoubleTap, "double_tap"},
    {ActionType::LongPress, "long_press"},
    {ActionType::Confirm, "confirm"},
    {ActionType::Cancel, "cancel"},
    {ActionType::OpenQuickMenu, "open_quick_menu"},
    {ActionType::RotateObject, "rotate_object"},
    {ActionType::ToggleWalls, "toggle_walls"},
    {ActionType::ShowDetails, "show_details"},
    {ActionType::ZoomIn, "zoom_in"},
    {ActionType::ZoomOut, "zoom_out"},
    {ActionType::PauseToggle, "pause_toggle"},
    {ActionType::Overview, "overview"},
    {ActionType::PreviousCategory, "previous_category"},
    {ActionType::NextCategory, "next_category"},
    {ActionType::SpeedCycle, "speed_cycle"},
    {ActionType::OpenDashboard, "open_dashboard"},
    {ActionType::OpenBuild, "open_build"},
    {ActionType::OpenStaff, "open_staff"},
    {ActionType::OpenPatients, "open_patients"},
    {ActionType::OpenFinance, "open_finance"},
    {ActionType::OpenMessages, "open_messages"},
    {ActionType::OpenBank, "open_bank"},
    {ActionType::OpenTownMap, "open_town_map"},
    {ActionType::OpenCasebook, "open_casebook"},
    {ActionType::OpenResearch, "open_research"},
    {ActionType::OpenPolicy, "open_policy"},
    {ActionType::OpenCharts, "open_charts"},
    {ActionType::HireStaff, "hire_staff"},
    {ActionType::FurnishCorridor, "furnish_corridor"},
    {ActionType::EditRoom, "edit_room"},
    {ActionType::QuickSave, "quick_save"},
    {ActionType::QuickLoad, "quick_load"},
    {ActionType::CloseTopWindow, "close_top_window"},
    {ActionType::BuildRoomRectangle, "build_room_rectangle"},
    {ActionType::PlaceItem, "place_item"},
    {ActionType::LifecycleSuspend, "lifecycle_suspend"},
    {ActionType::LifecycleResume, "lifecycle_resume"},
    {ActionType::LifecycleExit, "lifecycle_exit"},
    // Reserved aliases keep the table size stable if actions are appended.
    {ActionType::OpenDashboard, "dashboard"},
    {ActionType::OpenBuild, "build"},
    {ActionType::OpenStaff, "staff"},
    {ActionType::OpenPatients, "patients"},
    {ActionType::OpenFinance, "finance"},
    {ActionType::OpenMessages, "messages"},
    {ActionType::PauseToggle, "pause"},
}};

}  // namespace

std::string_view action_name(ActionType type) noexcept {
  for (const auto& item : kActionNames) {
    if (item.type == type) {
      return item.name;
    }
  }
  return "unknown";
}

std::string_view context_name(InputContext context) noexcept {
  switch (context) {
    case InputContext::World: return "world";
    case InputContext::BuildRoom: return "build_room";
    case InputContext::PlaceObject: return "place_object";
    case InputContext::Menu: return "menu";
    case InputContext::Dialog: return "dialog";
    case InputContext::TextInput: return "text_input";
  }
  return "world";
}

InputContext parse_context(std::string_view value) noexcept {
  if (value == "build_room") return InputContext::BuildRoom;
  if (value == "place_object") return InputContext::PlaceObject;
  if (value == "menu") return InputContext::Menu;
  if (value == "dialog") return InputContext::Dialog;
  if (value == "text_input") return InputContext::TextInput;
  return InputContext::World;
}

std::string_view bottom_tab_name(BottomTab tab) noexcept {
  switch (tab) {
    case BottomTab::Dashboard: return "dashboard";
    case BottomTab::Build: return "build";
    case BottomTab::Staff: return "staff";
    case BottomTab::Patients: return "patients";
    case BottomTab::Finance: return "finance";
    case BottomTab::Messages: return "messages";
  }
  return "dashboard";
}

}  // namespace cth3ds
