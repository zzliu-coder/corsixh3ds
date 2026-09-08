#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include "cth3ds/events.hpp"

namespace cth3ds {
[[nodiscard]] inline bool benchmark_user_input(const RawInputSnapshot& sample) noexcept {
  return sample.held || sample.down || sample.touching ||
    sample.circle_x<=-24 || sample.circle_x>=24 ||
    sample.circle_y<=-24 || sample.circle_y>=24;
}
// The caller owns synchronization. Edges are never coalesced; held movement
// keeps a sample at least every 32ms. Idle snapshots occupy one tail entry.
class InputQueue {
 public:
  static constexpr std::size_t capacity = 256;
  struct Statistics {
    std::uint64_t sampled{}, coalesced{}, popped{}, overflows{}, discarded{};
    std::uint64_t touch_down{}, touch_up{}, max_age_us{}, max_sample_gap_us{};
    std::size_t peak_depth{};
    std::array<std::uint64_t,32> age_histogram{}; // 10ms bins; final is >=310ms
    std::uint64_t age_p95_upper_us() const noexcept {
      if(!popped)return 0;
      const auto target=popped-popped/20;std::uint64_t count=0;
      for(std::size_t i=0;i<age_histogram.size();++i){
        count+=age_histogram[i];
        if(count>=target)return i==31?max_age_us:(i+1)*10000U;
      }return max_age_us;
    }
  };
  void push(const RawInputSnapshot& sample) noexcept {
    ++stats_.sampled;
    if (have_previous_ && sample.timestamp_us >= previous_.timestamp_us)
      stats_.max_sample_gap_us = std::max(stats_.max_sample_gap_us, sample.timestamp_us - previous_.timestamp_us);
    const bool edge = !have_previous_ || sample.held != previous_.held ||
                      sample.touching != previous_.touching;
    if (sample.touching && (!have_previous_ || !previous_.touching)) ++stats_.touch_down;
    if (!sample.touching && have_previous_ && previous_.touching) ++stats_.touch_up;
    previous_ = sample; have_previous_ = true;
    if (size_ && !edge) {
      auto& tail = data_[(head_ + size_ - 1U) % capacity];
      const bool idle = !sample.held && !sample.touching &&
                        sample.circle_x > -24 && sample.circle_x < 24 &&
                        sample.circle_y > -24 && sample.circle_y < 24;
      if (!tail.edge && sample.timestamp_us >= tail.first_us &&
          (idle || sample.timestamp_us - tail.first_us < 32000U)) {
        tail.sample = sample; ++stats_.coalesced; return;
      }
    }
    if (size_ == capacity) {
      ++stats_.overflows; stats_.discarded += size_; head_ = size_ = 0;
      cancellation_ = true; // Main must cancel the drag before this new sample.
    }
    data_[(head_ + size_) % capacity] = {sample, sample.timestamp_us, edge};
    ++size_; stats_.peak_depth = std::max(stats_.peak_depth, size_);
  }
  bool pop(RawInputSnapshot& out, std::uint64_t now) noexcept {
    if (!size_) return false;
    out = data_[head_].sample;
    head_ = (head_ + 1U) % capacity; --size_; ++stats_.popped;
    const auto age=now>=out.timestamp_us?now-out.timestamp_us:0;
    stats_.max_age_us=std::max(stats_.max_age_us,age);
    const auto bucket=static_cast<std::size_t>(std::min<std::uint64_t>(31,age/10000U));
    ++stats_.age_histogram[bucket];
    return true;
  }
  void discard() noexcept {
    stats_.discarded += size_; head_ = size_ = 0; cancellation_ = true;
    // Intentional pauses/owner changes start a new sampling epoch. Their
    // duration must not inflate the hardware sampling-gap statistic.
    have_previous_ = false;
  }
  bool take_cancellation() noexcept { const bool result = cancellation_; cancellation_ = false; return result; }
  const Statistics& statistics() const noexcept { return stats_; }
  std::size_t size() const noexcept { return size_; }
 private:
  struct Entry { RawInputSnapshot sample{}; std::uint64_t first_us{}; bool edge{}; };
  std::array<Entry, capacity> data_{};
  std::size_t head_{}, size_{};
  RawInputSnapshot previous_{};
  Statistics stats_{};
  bool have_previous_{}, cancellation_{};
};
} // namespace cth3ds
