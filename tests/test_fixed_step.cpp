#include "test_framework.hpp"

#include "cth3ds/simulation_clock.hpp"
#include "cth3ds/presentation_clock.hpp"

TEST(presentation_clock_retains_requests_and_bounds_idle_refresh) {
  cth3ds::PresentationClock clock;
  EXPECT_TRUE(clock.take(0,false,false));
  EXPECT_FALSE(clock.take(5000,true,false));
  EXPECT_TRUE(clock.take(16667,false,false));
  EXPECT_FALSE(clock.take(34000,false,false));
  EXPECT_TRUE(clock.take(116667,false,false));
  EXPECT_FALSE(clock.take(216667,false,true));
  EXPECT_TRUE(clock.take(216668,true,true));
  EXPECT_TRUE(clock.take(5,true,true));
}

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
  EXPECT_EQ(clock.statistics().completed_steps,0U);
  clock.complete_step(true);clock.complete_step(false);
  EXPECT_EQ(clock.statistics().completed_steps,1U);
  EXPECT_EQ(clock.statistics().failed_steps,1U);
  EXPECT_EQ(clock.statistics().steps,100U);
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

TEST(simulation_clock_preserves_cadence_across_render_rates) {
  // Cheap callbacks at 20/30/60/120 presentation Hz all deliver the same
  // original 18 ms clock. This is scheduling correctness, not hardware FPS.
  for(unsigned hz : {20U,30U,60U,120U}) {
    cth3ds::SimulationClock clock; clock.begin(0);
    for(unsigned frame=1;frame<=hz*18;++frame) {
      const auto now=static_cast<std::uint64_t>(frame)*1000000U/hz;
      clock.begin(now);
      while(clock.take_step(now)) {}
    }
    EXPECT_EQ(clock.statistics().steps,1000U);
    EXPECT_EQ(clock.statistics().dropped_us,0U);
    EXPECT_EQ(clock.statistics().debt_us,0U);
  }
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
