#include "test_framework.hpp"

#include "cth3ds/fixed_step.hpp"
#include "cth3ds/simulation_clock.hpp"

TEST(simulation_clock_uses_elapsed_time_with_original_18ms_tick) {
  cth3ds::SimulationClock clock;
  clock.begin(0);
  EXPECT_FALSE(clock.take_step(0));
  unsigned steps=0;
  // More wakeups never speed up the original clock; ~55.56 ticks/second.
  for (unsigned now=1000;now<=1800000;now+=1000) {
    clock.begin(now);
    while(clock.take_step(now))++steps;
  }
  EXPECT_EQ(steps,100U);
  EXPECT_EQ(clock.statistics().dropped_us,0U);
}

TEST(simulation_clock_bounds_debt_steps_and_callback_time) {
  cth3ds::SimulationClock clock;clock.begin(0);clock.begin(1000000);
  for(unsigned i=0;i<4;++i)EXPECT_TRUE(clock.take_step(1000000));
  EXPECT_FALSE(clock.take_step(1000000));
  EXPECT_EQ(clock.statistics().dropped_us,856000U);
  EXPECT_EQ(clock.statistics().debt_us,72000U);
  clock.begin(1000000);
  EXPECT_TRUE(clock.take_step(1000000));
  EXPECT_FALSE(clock.take_step(1024000));
  EXPECT_EQ(clock.statistics().budget_exits,1U);
  // Budget overrun during one expensive callback must yield immediately.
  clock.begin(1024000);EXPECT_TRUE(clock.take_step(1024000));
  EXPECT_FALSE(clock.take_step(1100000));
}

TEST(simulation_clock_rebases_load_sleep_failure_and_backwards_time) {
  cth3ds::SimulationClock clock;clock.begin(0);clock.begin(72000);
  EXPECT_TRUE(clock.take_step(72000));
  clock.interrupt();EXPECT_FALSE(clock.take_step(72001));
  clock.begin(3600000000ULL);EXPECT_FALSE(clock.take_step(3600000000ULL));
  clock.begin(3600018000ULL);EXPECT_TRUE(clock.take_step(3600018000ULL));
  clock.begin(10);EXPECT_FALSE(clock.take_step(10));
  EXPECT_EQ(clock.statistics().rebases,3U);
  EXPECT_EQ(clock.statistics().dropped_us,0U);
  clock.reset();EXPECT_EQ(clock.statistics().steps,0U);
}

TEST(frame_scheduler_initial_frame_renders_both_screens) {
  cth3ds::FrameScheduler scheduler;
  const auto decision = scheduler.advance(1000000);
  EXPECT_EQ(decision.simulation_steps, 0);
  EXPECT_TRUE(decision.render_top);
  EXPECT_TRUE(decision.render_bottom);
}

TEST(frame_scheduler_caps_simulation_catchup) {
  cth3ds::FrameScheduler scheduler(18000, 33333, 50000, 4);
  (void)scheduler.advance(0);
  const auto decision = scheduler.advance(1000000);
  EXPECT_EQ(decision.simulation_steps, 4);
  EXPECT_TRUE(decision.dropped_time);
}

TEST(frame_scheduler_maintains_independent_render_rates) {
  cth3ds::FrameScheduler scheduler(18000, 33333, 50000, 4);
  (void)scheduler.advance(0);
  auto decision = scheduler.advance(34000);
  EXPECT_TRUE(decision.render_top);
  EXPECT_FALSE(decision.render_bottom);
  decision = scheduler.advance(51000);
  EXPECT_FALSE(decision.render_top);
  EXPECT_TRUE(decision.render_bottom);
  scheduler.request_redraw();
  decision = scheduler.advance(52000);
  EXPECT_TRUE(decision.render_top);
  EXPECT_TRUE(decision.render_bottom);
}
