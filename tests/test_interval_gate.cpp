#include "test_framework.hpp"

#include <cstdint>
#include <limits>

#include "cth3ds/interval_gate.hpp"

TEST(interval_gate_can_fire_immediately) {
  cth3ds::IntervalGate gate(100U);
  gate.reset(1000U, true);
  EXPECT_TRUE(gate.due(1000U));
  EXPECT_FALSE(gate.due(1099U));
  EXPECT_TRUE(gate.due(1100U));
}

TEST(interval_gate_skips_catch_up_bursts) {
  cth3ds::IntervalGate gate(100U);
  gate.reset(0U, false);
  EXPECT_TRUE(gate.due(1000U));
  EXPECT_FALSE(gate.due(1000U));
  EXPECT_EQ(gate.next_deadline_us(), std::uint64_t{1100U});
}

TEST(interval_gate_recovers_from_clock_reset) {
  cth3ds::IntervalGate gate(100U);
  gate.reset(500U, false);
  EXPECT_FALSE(gate.due(550U));
  EXPECT_TRUE(gate.due(10U));
}

TEST(interval_gate_handles_saturation) {
  cth3ds::IntervalGate gate(100U);
  const auto near_max = std::numeric_limits<std::uint64_t>::max() - 20U;
  gate.reset(near_max, true);
  EXPECT_TRUE(gate.due(near_max));
  EXPECT_EQ(gate.next_deadline_us(), std::numeric_limits<std::uint64_t>::max());
}
