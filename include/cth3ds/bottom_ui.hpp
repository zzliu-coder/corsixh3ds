#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "cth3ds/build_gesture.hpp"
#include "cth3ds/events.hpp"
#include "cth3ds/screen_layout.hpp"

namespace cth3ds {

enum class BottomTab : int {
  Dashboard = 0,
  Build = 1,
  Staff = 2,
  Patients = 3,
  Finance = 4,
  Messages = 5,
};

enum class BuildTool {
  Rooms,
  CorridorItems,
  EditRoom,
  HireStaff,
};

struct BottomUiState {
  BottomTab active_tab{BottomTab::Dashboard};
  BuildTool build_tool{BuildTool::Rooms};
  InputContext input_context{InputContext::World};
  std::int64_t cash{0};
  int reputation{0};
  int day{1};
  int month{1};
  int year{1};
  int patient_count{0};
  int staff_count{0};
  int queue_count{0};
  int message_count{0};
  int game_speed{1};
  bool paused{false};
  int battery_level{-1};
  bool charging{false};
  int volume_slider{-1};
  int wifi_strength{-1};
  std::uint64_t free_memory_bytes{0};
  std::string notice{};
  bool notice_is_error{false};
  std::string selected_name{};
  std::string selected_status{};
  // Overlay version plus where the Lua adapter came from, e.g. "0.5.0 LUA".
  // Shown on the status line so a binary/SD-card mismatch is visible on device.
  std::string build_tag{};

  // Used by the 3DS runtime to skip a lower-screen repaint when nothing the
  // player can see actually changed. A repaint costs a full 320x240 software
  // render plus a framebuffer copy, so this is not a micro-optimisation on a
  // 268 MHz ARM11.
  [[nodiscard]] bool operator==(const BottomUiState& other) const noexcept {
    return active_tab == other.active_tab && build_tool == other.build_tool &&
           input_context == other.input_context && cash == other.cash &&
           reputation == other.reputation && day == other.day &&
           month == other.month && year == other.year &&
           patient_count == other.patient_count &&
           staff_count == other.staff_count &&
           queue_count == other.queue_count &&
           message_count == other.message_count &&
           game_speed == other.game_speed && paused == other.paused &&
           battery_level == other.battery_level &&
           charging == other.charging &&
           volume_slider == other.volume_slider &&
           wifi_strength == other.wifi_strength &&
           free_memory_bytes == other.free_memory_bytes &&
           notice == other.notice && notice_is_error == other.notice_is_error &&
           selected_name == other.selected_name &&
           selected_status == other.selected_status &&
           build_tag == other.build_tag;
  }
  [[nodiscard]] bool operator!=(const BottomUiState& other) const noexcept {
    return !(*this == other);
  }
};

class BottomUiController {
 public:
  BottomUiController();

  [[nodiscard]] std::vector<Action> process(const Action& pointer_action);
  void set_state(BottomUiState state);
  [[nodiscard]] const BottomUiState& state() const noexcept { return state_; }
  [[nodiscard]] RectI room_preview_cells() const noexcept { return build_gesture_.preview(); }
  [[nodiscard]] bool is_pressed() const noexcept { return pointer_down_; }
  [[nodiscard]] Vec2i pointer_position() const noexcept { return pointer_position_; }

 private:
  [[nodiscard]] std::vector<Action> handle_tap(Vec2i point);
  [[nodiscard]] std::vector<Action> handle_pointer_down(Vec2i point);
  [[nodiscard]] std::vector<Action> handle_pointer_move(Vec2i point);
  [[nodiscard]] std::vector<Action> handle_pointer_up(Vec2i point);
  [[nodiscard]] static Action action(ActionType type);

  BottomUiState state_{};
  BuildGesture build_gesture_{};
  bool pointer_down_{false};
  Vec2i pointer_position_{};
  bool build_drag_started_{false};
};

}  // namespace cth3ds
