#include "test_framework.hpp"

#include "cth3ds/fixed_step.hpp"

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
