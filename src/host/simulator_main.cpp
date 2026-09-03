#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "cth3ds/bottom_ui.hpp"
#include "cth3ds/events.hpp"
#include "cth3ds/fixed_step.hpp"
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/screen_layout.hpp"
#include "cth3ds/software_canvas.hpp"

namespace {

cth3ds::Action pointer(cth3ds::ActionType type, cth3ds::Vec2i position) {
  cth3ds::Action action;
  action.type = type;
  action.position = position;
  return action;
}

std::string action_name(cth3ds::ActionType type) {
  using cth3ds::ActionType;
  switch (type) {
    case ActionType::OpenBuild: return "OpenBuild";
    case ActionType::BuildRoomRectangle: return "BuildRoomRectangle";
    case ActionType::PauseToggle: return "PauseToggle";
    case ActionType::SpeedCycle: return "SpeedCycle";
    case ActionType::Overview: return "Overview";
    case ActionType::Cancel: return "Cancel";
    default: return "Other";
  }
}

}  // namespace

int main(int argc, char** argv) {
  const std::filesystem::path output_directory =
      argc > 1 ? std::filesystem::path(argv[1])
               : std::filesystem::path("simulator-output");
  std::error_code ec;
  std::filesystem::create_directories(output_directory, ec);
  if (ec) {
    std::cerr << "Cannot create output directory: " << ec.message() << '\n';
    return 1;
  }

  cth3ds::BottomUiState state;
  state.cash = 73420;
  state.reputation = 612;
  state.day = 17;
  state.month = 9;
  state.year = 1998;
  state.patient_count = 47;
  state.staff_count = 16;
  state.queue_count = 11;
  state.message_count = 3;
  state.battery_level = 4;
  state.volume_slider = 42;
  state.wifi_strength = 3;
  state.free_memory_bytes = 53U * 1024U * 1024U;
  state.notice = "AUTOSAVE OK";
  state.selected_name = "Dr. Avery";
  state.selected_status = "Consulting in GP office";

  cth3ds::BottomUiController ui;
  ui.set_state(state);
  std::vector<cth3ds::Action> trace;

  // Select the BUILD tab.
  const cth3ds::RectI build_tab = cth3ds::ScreenLayout::tab_rect(1);
  const cth3ds::Vec2i build_tab_center{
      build_tab.x + build_tab.w / 2, build_tab.y + build_tab.h / 2};
  const auto tab_actions = ui.process(pointer(cth3ds::ActionType::Tap, build_tab_center));
  trace.insert(trace.end(), tab_actions.begin(), tab_actions.end());

  state.active_tab = cth3ds::BottomTab::Build;
  state.input_context = cth3ds::InputContext::BuildRoom;
  ui.set_state(state);

  // Draw a valid room on the lower-screen grid.
  const cth3ds::ScreenLayout::Grid grid = cth3ds::ScreenLayout::build_grid();
  const cth3ds::Vec2i room_start{grid.bounds.x + 2 * grid.cell_size + 2,
                                grid.bounds.y + 1 * grid.cell_size + 2};
  const cth3ds::Vec2i room_end{grid.bounds.x + 8 * grid.cell_size + 8,
                              grid.bounds.y + 5 * grid.cell_size + 8};
  (void)ui.process(pointer(cth3ds::ActionType::PointerDown, room_start));
  (void)ui.process(pointer(cth3ds::ActionType::PointerMove, room_end));

  cth3ds::SoftwareCanvas top(cth3ds::ScreenLayout::kTopWidth,
                             cth3ds::ScreenLayout::kTopHeight);
  cth3ds::SoftwareCanvas bottom(cth3ds::ScreenLayout::kBottomWidth,
                                cth3ds::ScreenLayout::kBottomHeight);
  cth3ds::render_top_placeholder(top, state, {-12.0F, 4.0F}, 1.0F);
  cth3ds::render_bottom_ui(bottom, ui);

  std::string error;
  if (!top.write_ppm(output_directory / "top.ppm", error)) {
    std::cerr << error << '\n';
    return 1;
  }
  if (!bottom.write_ppm(output_directory / "bottom.ppm", error)) {
    std::cerr << error << '\n';
    return 1;
  }

  const auto room_actions = ui.process(pointer(cth3ds::ActionType::PointerUp, room_end));
  trace.insert(trace.end(), room_actions.begin(), room_actions.end());

  std::ofstream report(output_directory / "trace.json", std::ios::trunc);
  report << "{\n  \"actions\": [\n";
  for (std::size_t i = 0; i < trace.size(); ++i) {
    report << "    {\"type\": \"" << action_name(trace[i].type) << "\"";
    if (trace[i].type == cth3ds::ActionType::BuildRoomRectangle) {
      const auto& rect = trace[i].rectangle;
      report << ", \"rect\": [" << rect.x << ", " << rect.y << ", "
             << rect.w << ", " << rect.h << ']';
    }
    report << '}';
    if (i + 1U != trace.size()) {
      report << ',';
    }
    report << '\n';
  }
  report << "  ],\n  \"top\": [400, 240],\n  \"bottom\": [320, 240]\n}\n";

  std::cout << "Generated simulator frames in " << output_directory << '\n';
  return 0;
}
