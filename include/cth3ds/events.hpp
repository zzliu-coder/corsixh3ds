#pragma once

#include <cstdint>
#include <string>

#include "cth3ds/types.hpp"

namespace cth3ds {

enum class Button : std::uint32_t {
  A = 1U << 0U,
  B = 1U << 1U,
  Select = 1U << 2U,
  Start = 1U << 3U,
  DRight = 1U << 4U,
  DLeft = 1U << 5U,
  DUp = 1U << 6U,
  DDown = 1U << 7U,
  R = 1U << 8U,
  L = 1U << 9U,
  X = 1U << 10U,
  Y = 1U << 11U,
};

[[nodiscard]] constexpr std::uint32_t button_mask(Button button) noexcept {
  return static_cast<std::uint32_t>(button);
}

[[nodiscard]] constexpr bool has_button(std::uint32_t mask, Button button) noexcept {
  return (mask & button_mask(button)) != 0U;
}

enum class InputContext {
  World,
  BuildRoom,
  PlaceObject,
  Menu,
  Dialog,
  TextInput,
};

struct RawInputSnapshot {
  std::uint64_t timestamp_us{0};
  std::uint32_t held{0};
  std::uint32_t down{0};
  std::uint32_t up{0};
  int circle_x{0};
  int circle_y{0};
  bool touching{false};
  Vec2i touch{};
};

enum class ActionType {
  None,
  PanCamera,
  CursorStep,
  PointerDown,
  PointerMove,
  PointerUp,
  Tap,
  DoubleTap,
  LongPress,
  Confirm,
  Cancel,
  OpenQuickMenu,
  RotateObject,
  ToggleWalls,
  ShowDetails,
  ZoomIn,
  ZoomOut,
  PauseToggle,
  Overview,
  PreviousCategory,
  NextCategory,
  SpeedCycle,
  OpenDashboard,
  OpenBuild,
  OpenStaff,
  OpenPatients,
  OpenFinance,
  OpenMessages,
  OpenBank,
  OpenTownMap,
  OpenCasebook,
  OpenResearch,
  OpenPolicy,
  OpenCharts,
  HireStaff,
  FurnishCorridor,
  EditRoom,
  QuickSave,
  QuickLoad,
  CloseTopWindow,
  BuildRoomRectangle,
  PlaceItem,
  LifecycleSuspend,
  LifecycleResume,
  LifecycleExit,
};

struct Action {
  ActionType type{ActionType::None};
  Vec2f vector{};
  Vec2i position{};
  RectI rectangle{};
  int value{0};
  bool repeated{false};
  std::string text{};
};

}  // namespace cth3ds
