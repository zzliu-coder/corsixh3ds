#pragma once
#include <string_view>
#include "cth3ds/presentation_masks.hpp"

namespace cth3ds {
// Explicit operation IDs only. Arbitrary errors and benchmark protocols never
// enter this lookup. Both display backends consume the same cached overlay.
struct NoticeHint {
  std::string_view id;
  const char* english;
  const presentation_masks::Mask* chinese;
};
inline constexpr NoticeHint kNoticeHints[] = {
  {"keyboard_unavailable", "KEYBOARD UNAVAILABLE - USE SAVE SLOTS", &presentation_masks::hint_keyboard_unavailable},
  {"digits_only", "USE DIGITS ONLY", &presentation_masks::hint_digits_only},
  {"input_rejected", "INPUT DOES NOT MATCH THIS FIELD", &presentation_masks::hint_input_rejected},
  {"resume_speed", "PAUSED - RESUME BEFORE CHANGING SPEED", &presentation_masks::hint_resume_speed},
  {"speed_unchanged", "SPEED UNCHANGED", &presentation_masks::hint_speed_unchanged},
  {"speed_1", "SPEED: SLOWEST", &presentation_masks::hint_speed_1},
  {"speed_2", "SPEED: SLOWER", &presentation_masks::hint_speed_2},
  {"speed_3", "SPEED: NORMAL", &presentation_masks::hint_speed_3},
  {"speed_4", "SPEED: MAX SPEED", &presentation_masks::hint_speed_4},
  {"speed_5", "SPEED: AND THEN SOME MORE", &presentation_masks::hint_speed_5},
  {"zoom_locked", "ZOOM LOCKED ON 3DS", &presentation_masks::hint_zoom_locked},
  {"save_no_world", "START OR LOAD A HOSPITAL TO SAVE", &presentation_masks::hint_save_no_world},
  {"place", "A: PLACE  X: ROTATE  B: CANCEL", &presentation_masks::hint_place},
  {"room", "DRAG: ROOM  B: CANCEL  Y: WALLS", &presentation_masks::hint_room},
  {"keyboard", "A: KEYBOARD  B: CANCEL", &presentation_masks::hint_keyboard},
  {"wide", "WIDE 480x288 - L: CLEAR", &presentation_masks::hint_wide},
  {"clear", "CLEAR 400x240 - L: WIDE", &presentation_masks::hint_clear},
  {"target", "TARGET REVEALED - PRESS AGAIN", &presentation_masks::hint_target},
  {"input_reset", "INPUT QUEUE RESET AFTER LONG STALL", &presentation_masks::hint_input_reset},
};
inline const NoticeHint* notice_hint(std::string_view id) noexcept {
  for (const auto& hint : kNoticeHints) if (hint.id == id) return &hint;
  return nullptr;
}
} // namespace cth3ds
