#pragma once
#include <cstdint>
namespace cth3ds {
// Draw requests survive pacing. Simulation has its own 18ms elapsed clock.
class PresentationClock {
 public:
  static constexpr std::uint64_t interval_us=16667,idle_menu_us=100000;
  bool take(std::uint64_t now,bool changed,bool world) noexcept {
    dirty_=dirty_||changed;
    const bool first=!initialized_||now<last_;
    const auto elapsed=first?interval_us:now-last_;
    if(!first&&elapsed<interval_us)return false;
    // Unknown legacy menu animations retain a bounded 10Hz refresh. Explicit
    // UI/input changes request the next 60Hz slot; active worlds keep repainting.
    if(!first&&!dirty_&&(world||elapsed<idle_menu_us))return false;
    initialized_=true;last_=now;dirty_=false;return true;
  }
  void reset() noexcept {*this={};}
 private:
  std::uint64_t last_{};bool initialized_{},dirty_{};
};
}
