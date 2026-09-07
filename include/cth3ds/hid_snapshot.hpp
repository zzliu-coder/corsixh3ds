#pragma once
#include <atomic>
#include <cstdint>
#include "cth3ds/events.hpp"

namespace cth3ds {
// Read the Old-3DS PAD/touch shared sections without changing libctru's global
// hidScanInput state used by SDL. Layout follows libctru services/hid.c.
// Retry concurrent service updates; no write, allocation, Lua or SDL operation.
inline bool read_hid_snapshot(const volatile std::uint32_t* memory,
                               std::uint64_t now, RawInputSnapshot& out) noexcept {
  if (!memory) return false;
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    const auto pad = memory[4], touch = memory[46];
    if (pad > 7 || touch > 7) return false;
    const auto pad_tick_lo = memory[0], pad_tick_hi = memory[1];
    const auto touch_tick_lo = memory[42], touch_tick_hi = memory[43];
    if ((pad == 0 && pad_tick_lo == memory[2] && pad_tick_hi == memory[3]) ||
        (touch == 0 && touch_tick_lo == memory[44] && touch_tick_hi == memory[45]) ||
        (pad_tick_hi & 0x80000000U) || (touch_tick_hi & 0x80000000U)) return false;
    std::atomic_thread_fence(std::memory_order_acquire);
    RawInputSnapshot sample{};
    sample.timestamp_us = now;
    sample.held = memory[10 + pad * 4] & 0xfffU;
    const auto circle = memory[13 + pad * 4];
    sample.circle_x = static_cast<std::int16_t>(circle & 0xffffU);
    sample.circle_y = static_cast<std::int16_t>(circle >> 16U);
    const auto point = memory[50 + touch * 2];
    sample.touch = {static_cast<int>(point & 0xffffU), static_cast<int>(point >> 16U)};
    sample.touching = memory[51 + touch * 2] != 0;
    std::atomic_thread_fence(std::memory_order_acquire);
    if (pad == memory[4] && touch == memory[46] && pad_tick_lo == memory[0] &&
        pad_tick_hi == memory[1] && touch_tick_lo == memory[42] && touch_tick_hi == memory[43]) {
      out = sample; return true;
    }
  }
  return false;
}
} // namespace cth3ds
