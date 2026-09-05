#include "test_framework.hpp"
#include "cth3ds/telemetry.hpp"
#include "cth3ds/fixed_step.hpp"
#include <limits>

using cth3ds::TimingStage;
using cth3ds::PresentResult;
static const cth3ds::SpanSummary& stage(const cth3ds::PerformanceSnapshot& s, TimingStage kind) {
  return s.stages[static_cast<std::size_t>(kind)];
}
TEST(telemetry_calculates_average_percentile_and_maximum) {
  cth3ds::Telemetry t(10);
  for (int i = 1; i <= 4; ++i) t.record_frame(static_cast<std::uint64_t>(i) * 10000U, i == 2);
  t.set_memory(1024, 2048);
  const auto s = t.snapshot();
  EXPECT_NEAR(s.average_frame_ms, 25.0, .001);
  EXPECT_NEAR(s.p95_frame_ms, 40.0, .001); // nearest rank, upper bound
  EXPECT_NEAR(s.maximum_frame_ms, 40.0, .001);
  EXPECT_EQ(s.dropped_frames, 1U); EXPECT_EQ(s.texture_bytes, 1024U);
  EXPECT_EQ(s.linear_bytes, 2048U); EXPECT_EQ(s.successful_presents, 0U);
  EXPECT_EQ(s.intervals.count, 0U); EXPECT_EQ(s.legacy_durations.count, 4U);
}
TEST(telemetry_history_is_bounded) {
  cth3ds::Telemetry t(2);
  t.record_frame(1000, false); t.record_frame(2000, false); t.record_frame(9000, false);
  EXPECT_NEAR(t.snapshot().average_frame_ms, 4.0, .001); // fixed storage, all observations
  EXPECT_TRUE(sizeof(t) <= 20U * 1024U);
}
TEST(telemetry_complete_minute_keeps_early_slow_frames_and_more_than_240) {
  cth3ds::Telemetry t;
  t.reset_window(0); t.present_complete(0, PresentResult::Success);
  std::uint64_t now = 0;
  for (int i = 0; i < 1000; ++i) {
    now += i < 100 ? 300000U : 33333U;
    t.present_complete(now, PresentResult::Success);
  }
  const auto s = t.snapshot(60000000);
  EXPECT_EQ(s.successful_presents, 1001U); EXPECT_EQ(s.intervals.count, 1000U);
  EXPECT_EQ(s.intervals.total_us, 59999700U); EXPECT_EQ(s.intervals.maximum_us, 300000U);
  EXPECT_TRUE(s.intervals.p95_lower_us <= 300000U && s.intervals.p95_upper_us >= 300000U);
  EXPECT_EQ(s.elapsed_us, 60000000U); EXPECT_EQ(s.open_present_gap_us, 300U);
}
TEST(telemetry_controlled_logic_top_bottom_save_delay_attribution) {
  for (const auto delayed : {TimingStage::Logic, TimingStage::Top, TimingStage::Bottom, TimingStage::Save}) {
    cth3ds::Telemetry t; std::uint64_t now = 0;
    t.present_complete(now, PresentResult::Success);
    for (auto kind : {TimingStage::Event, TimingStage::Runtime, TimingStage::Logic,
                      TimingStage::Render, TimingStage::Bottom, TimingStage::GC, TimingStage::Save}) {
      auto token = t.begin_span(kind, now); now += 1000;
      if (kind == delayed) now += 7000;
      if (kind == TimingStage::Render) {
        auto top = t.begin_span(TimingStage::Top, now);
        now += 1000 + (delayed == TimingStage::Top ? 7000 : 0);
        EXPECT_TRUE(t.end_span(top, now));
      }
      EXPECT_TRUE(t.end_span(token, now));
    }
    t.present_complete(now, PresentResult::Success);
    const auto s = t.snapshot();
    EXPECT_EQ(s.intervals.total_us, 15000U);
    std::uint64_t exclusive = 0;
    for (std::size_t i = 0; i < 10; ++i) exclusive += s.stages[i].exclusive_us;
    EXPECT_EQ(exclusive, 15000U);
    EXPECT_EQ(stage(s, delayed).exclusive_us, 8000U);
    EXPECT_EQ(stage(s, TimingStage::Render).exclusive_us, 1000U);
    EXPECT_EQ(stage(s, TimingStage::Render).inclusive_us, delayed == TimingStage::Top ? 9000U : 2000U);
  }
}
TEST(telemetry_failed_skipped_frames_preserve_long_gap_and_no_frame_save_span) {
  cth3ds::Telemetry t; t.present_complete(0, PresentResult::Success);
  t.present_complete(1000, PresentResult::Failed); t.present_complete(2000, PresentResult::Skipped);
  const auto token = t.begin_span(TimingStage::Save, 2000);
  const auto open = t.snapshot(70002000);
  EXPECT_EQ(stage(open, TimingStage::Save).open, 1U);
  EXPECT_EQ(stage(open, TimingStage::Save).inclusive_us, 70000000U);
  EXPECT_EQ(open.open_present_gap_us, 70002000U); EXPECT_EQ(open.intervals.count, 0U);
  EXPECT_FALSE(t.reset_window(70002000));
  EXPECT_TRUE(t.end_span(token, 70002000, false));
  t.present_complete(70003000, PresentResult::Success);
  const auto s = t.snapshot();
  EXPECT_EQ(s.intervals.total_us, 70003000U); EXPECT_EQ(s.failed_presents, 1U);
  EXPECT_EQ(s.skipped_presents, 1U); EXPECT_EQ(s.successful_presents, 2U);
  EXPECT_EQ(stage(s, TimingStage::Save).failed, 1U);
}
TEST(telemetry_windows_keep_crossing_interval_and_counts_separate) {
  cth3ds::Telemetry t; t.reset_window(0);
  t.present_complete(10, PresentResult::Success); t.present_complete(40, PresentResult::Success);
  EXPECT_TRUE(t.reset_window(60)); t.present_complete(100, PresentResult::Success);
  const auto s = t.snapshot();
  EXPECT_EQ(s.window_begin_us, 60U); EXPECT_EQ(s.elapsed_us, 40U);
  EXPECT_EQ(s.successful_presents, 1U); EXPECT_EQ(s.intervals.count, 1U);
  EXPECT_EQ(s.intervals.total_us, 60U); EXPECT_EQ(s.interval_coverage_begin_us, 40U);
  EXPECT_EQ(s.interval_coverage_end_us, 100U);
}
TEST(telemetry_rejects_non_lifo_backwards_and_excess_depth_without_corrupting_spans) {
  cth3ds::Telemetry t; auto a = t.begin_span(TimingStage::Render, 0);
  auto b = t.begin_span(TimingStage::Top, 10);
  EXPECT_FALSE(t.end_span(a, 20)); EXPECT_FALSE(t.end_span(b, 9));
  EXPECT_TRUE(t.end_span(b, 20)); EXPECT_TRUE(t.end_span(a, 30));
  EXPECT_EQ(t.snapshot().invalid_events, 2U);
  auto stale = t.begin_span(TimingStage::Load, 30); t.clear();
  auto fresh = t.begin_span(TimingStage::Load, 0);
  EXPECT_FALSE(t.end_span(stale, 1)); EXPECT_TRUE(t.end_span(fresh, 1));
  std::uint64_t tokens[16];
  for (auto& token : tokens) token = t.begin_span(TimingStage::Event, 2);
  EXPECT_EQ(t.begin_span(TimingStage::Event, 2), 0U);
  for (int i = 15; i >= 0; --i) EXPECT_TRUE(t.end_span(tokens[i], 3));
}
TEST(telemetry_quantile_bounds_cover_zero_target_and_extreme_pause) {
  for (auto us : {std::uint64_t{0}, std::uint64_t{33340}, std::uint64_t{100001},
                  std::numeric_limits<std::uint64_t>::max()}) {
    cth3ds::DurationDistribution d; d.add(us); const auto s = d.snapshot();
    EXPECT_TRUE(s.p95_lower_us <= us && us <= s.p95_upper_us);
    EXPECT_EQ(s.maximum_us, us); EXPECT_EQ(s.total_us, us);
  }
}
TEST(telemetry_clear_resets_epoch_but_legacy_never_becomes_product_fps) {
  cth3ds::Telemetry t; t.record_frame(1, true); t.present_complete(100, PresentResult::Success);
  t.clear(); t.present_complete(5, PresentResult::Success);
  EXPECT_EQ(t.snapshot().intervals.count, 0U); EXPECT_EQ(t.snapshot().dropped_frames, 0U);
  EXPECT_EQ(t.snapshot().legacy_durations.count, 0U);
}
TEST(telemetry_restore_span_keeps_wall_pause_while_simulation_clock_resets) {
  cth3ds::Telemetry t; cth3ds::FrameScheduler scheduler;
  scheduler.reset(1000); t.present_complete(1000, PresentResult::Success);
  auto restore = t.begin_span(TimingStage::Restore, 2000);
  const std::uint64_t resumed = 120002000;
  scheduler.reset(resumed);
  EXPECT_EQ(scheduler.advance(resumed).simulation_steps, 0);
  EXPECT_TRUE(t.end_span(restore, resumed));
  t.present_complete(resumed + 1000, PresentResult::Success);
  EXPECT_EQ(t.snapshot().intervals.maximum_us, 120002000U);
  EXPECT_EQ(stage(t.snapshot(), TimingStage::Restore).inclusive_us, 120000000U);
}

TEST(telemetry_extreme_duration_sum_saturates_with_explicit_flag) {
  cth3ds::DurationDistribution d;
  d.add(std::numeric_limits<std::uint64_t>::max()); d.add(1);
  EXPECT_TRUE(d.snapshot().total_overflowed);
  EXPECT_EQ(d.snapshot().total_us, std::numeric_limits<std::uint64_t>::max());
  d.clear(); EXPECT_FALSE(d.snapshot().total_overflowed);
}
