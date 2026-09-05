#include "cth3ds/telemetry.hpp"

#include <algorithm>
#include <limits>

namespace cth3ds {
namespace {
std::size_t bin_for(std::uint64_t us) noexcept {
  if (us <= 100000U) return static_cast<std::size_t>((us + 99U) / 100U);
  std::size_t power = 0;
  for (auto value = us; value > 1U; value >>= 1U) ++power;
  return 1001U + power;
}
std::uint64_t lower(std::size_t bin) noexcept {
  if (bin == 0U) return 0U;
  if (bin <= 1000U) return (bin - 1U) * 100U + 1U;
  return std::max<std::uint64_t>(100001U, std::uint64_t{1} << (bin - 1001U));
}
std::uint64_t upper(std::size_t bin) noexcept {
  if (bin <= 1000U) return bin * 100U;
  const auto power = bin - 1001U;
  return power == 63U ? std::numeric_limits<std::uint64_t>::max()
                      : (std::uint64_t{1} << (power + 1U)) - 1U;
}
}
void DurationDistribution::add(std::uint64_t us) noexcept {
  ++bins_[bin_for(us)]; ++count_;
  if (us > std::numeric_limits<std::uint64_t>::max() - total_) {
    total_ = std::numeric_limits<std::uint64_t>::max(); overflowed_ = true;
  } else { total_ += us; }
  maximum_ = std::max(maximum_, us);
}
DurationSummary DurationDistribution::snapshot() const noexcept {
  DurationSummary result;
  result.count = count_; result.total_us = total_; result.maximum_us = maximum_;
  result.total_overflowed = overflowed_;
  if (count_ == 0U) return result;
  const auto quantile = [&](std::uint64_t percent, std::uint64_t& lo, std::uint64_t& hi) {
    const auto rank = (count_ / 100U) * percent + ((count_ % 100U) * percent + 99U) / 100U;
    std::uint64_t seen = 0;
    for (std::size_t i = 0; i < bins_.size(); ++i) {
      seen += bins_[i];
      if (seen >= rank) { lo = lower(i); hi = std::min(upper(i), maximum_); return; }
    }
  };
  quantile(50, result.p50_lower_us, result.p50_upper_us);
  quantile(95, result.p95_lower_us, result.p95_upper_us);
  quantile(99, result.p99_lower_us, result.p99_upper_us);
  return result;
}
void DurationDistribution::clear() noexcept { bins_.fill(0); count_ = total_ = maximum_ = 0; overflowed_ = false; }
Telemetry::Telemetry(std::size_t) noexcept {}
void Telemetry::record_frame(std::uint64_t us, bool dropped) noexcept {
  legacy_.add(us); if (dropped) ++dropped_;
}
void Telemetry::set_memory(std::size_t texture, std::size_t linear) noexcept {
  texture_bytes_ = texture; linear_bytes_ = linear;
}
bool Telemetry::advance(std::uint64_t now) noexcept {
  if (!started_) { window_begin_us_ = last_us_ = now; started_ = true; }
  if (now < last_us_) { ++invalid_; return false; }
  if (depth_) stages_[static_cast<std::size_t>(stack_[depth_ - 1U].stage)].exclusive_us += now - last_us_;
  last_us_ = now;
  return true;
}
void Telemetry::present_complete(std::uint64_t now, PresentResult result) noexcept {
  if (!advance(now)) return;
  if (result == PresentResult::Failed) { ++failures_; return; }
  if (result == PresentResult::Skipped) { ++skipped_; return; }
  if (result != PresentResult::Success) { ++invalid_; return; }
  ++successes_;
  if (has_present_) {
    if (!has_interval_) coverage_begin_us_ = previous_present_us_;
    intervals_.add(now - previous_present_us_);
    coverage_end_us_ = now; has_interval_ = true;
  }
  previous_present_us_ = now; has_present_ = true;
}
std::uint64_t Telemetry::begin_span(TimingStage stage, std::uint64_t now) noexcept {
  if (static_cast<std::size_t>(stage) >= stages_.size() || depth_ == stack_.size()) {
    ++invalid_; return 0;
  }
  if (!advance(now)) return 0;
  if (++next_token_ == 0) ++next_token_;
  stack_[depth_++] = {stage, next_token_, now};
  return next_token_;
}
bool Telemetry::end_span(std::uint64_t token, std::uint64_t now, bool success) noexcept {
  if (!depth_ || !token || stack_[depth_ - 1U].token != token) { ++invalid_; return false; }
  if (!advance(now)) return false;
  const Span span = stack_[--depth_];
  auto& result = stages_[static_cast<std::size_t>(span.stage)];
  ++result.completed; if (!success) ++result.failed;
  const auto duration = now - span.begin_us;
  result.inclusive_us += duration; result.maximum_us = std::max(result.maximum_us, duration);
  return true;
}
PerformanceSnapshot Telemetry::snapshot() const noexcept { return snapshot(last_us_); }
PerformanceSnapshot Telemetry::snapshot(std::uint64_t now) const noexcept {
  PerformanceSnapshot s;
  now = std::max(now, last_us_);
  s.intervals = intervals_.snapshot(); s.legacy_durations = legacy_.snapshot();
  const auto& compat = s.intervals.count ? s.intervals : s.legacy_durations;
  if (compat.count) s.average_frame_ms = static_cast<double>(compat.total_us) / static_cast<double>(compat.count) / 1000.0;
  s.p95_frame_ms = static_cast<double>(compat.p95_upper_us) / 1000.0;
  s.maximum_frame_ms = static_cast<double>(compat.maximum_us) / 1000.0;
  s.dropped_frames = dropped_; s.texture_bytes = texture_bytes_; s.linear_bytes = linear_bytes_;
  s.stages = stages_;
  for (std::size_t i = 0; i < depth_; ++i) {
    const auto& span = stack_[i]; auto& summary = s.stages[static_cast<std::size_t>(span.stage)];
    ++summary.open; summary.inclusive_us += now - span.begin_us;
    summary.maximum_us = std::max(summary.maximum_us, now - span.begin_us);
  }
  if (depth_) s.stages[static_cast<std::size_t>(stack_[depth_ - 1U].stage)].exclusive_us += now - last_us_;
  s.successful_presents = successes_; s.failed_presents = failures_; s.skipped_presents = skipped_;
  s.window_begin_us = window_begin_us_; s.observed_until_us = now;
  s.elapsed_us = started_ ? now - window_begin_us_ : 0;
  s.interval_coverage_begin_us = coverage_begin_us_; s.interval_coverage_end_us = coverage_end_us_;
  s.has_present_anchor = has_present_; s.open_present_gap_us = has_present_ ? now - previous_present_us_ : 0;
  s.invalid_events = invalid_; return s;
}
bool Telemetry::reset_window(std::uint64_t now) noexcept {
  if (depth_) { ++invalid_; return false; }
  if (!advance(now)) return false;
  intervals_.clear(); legacy_.clear(); stages_.fill({});
  successes_ = failures_ = skipped_ = invalid_ = dropped_ = 0;
  coverage_begin_us_ = coverage_end_us_ = 0; has_interval_ = false;
  window_begin_us_ = now; return true;
}
void Telemetry::clear() noexcept {
  // Keep token generation so a token from an earlier epoch is rejected.
  intervals_.clear(); legacy_.clear(); stages_.fill({}); depth_ = 0;
  last_us_ = window_begin_us_ = previous_present_us_ = coverage_begin_us_ = coverage_end_us_ = 0;
  successes_ = failures_ = skipped_ = invalid_ = dropped_ = 0;
  texture_bytes_ = linear_bytes_ = 0;
  started_ = has_present_ = has_interval_ = false;
}
}  // namespace cth3ds
