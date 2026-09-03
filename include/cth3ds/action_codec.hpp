#pragma once

#include <string_view>

#include "cth3ds/bottom_ui.hpp"
#include "cth3ds/events.hpp"

namespace cth3ds {

[[nodiscard]] std::string_view action_name(ActionType type) noexcept;
[[nodiscard]] std::string_view context_name(InputContext context) noexcept;
[[nodiscard]] InputContext parse_context(std::string_view value) noexcept;
[[nodiscard]] std::string_view bottom_tab_name(BottomTab tab) noexcept;

}  // namespace cth3ds
