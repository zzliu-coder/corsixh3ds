#include "test_framework.hpp"

#include "cth3ds/panel_refresh.hpp"
#include "fixtures/r73_frame_scheduler_original.hpp"

TEST(panel_refresh_preserves_first_frame_deadline_and_early_requests) {
  cth3ds::PanelRefreshGate gate(33333);
  EXPECT_TRUE(gate.due(1000));
  EXPECT_FALSE(gate.due(1001));
  gate.request_redraw();
  gate.request_redraw();
  EXPECT_TRUE(gate.due(1002));
  EXPECT_FALSE(gate.due(34333)); // An early request consumed another period.
  EXPECT_TRUE(gate.due(67666));
  EXPECT_FALSE(gate.due(67666));
}

TEST(panel_refresh_preserves_backwards_time_and_resume_reset) {
  cth3ds::PanelRefreshGate gate(33333);
  EXPECT_TRUE(gate.due(1000000));
  EXPECT_FALSE(gate.due(5)); // Existing deadline is retained, without rebasing.
  gate.request_redraw();
  EXPECT_TRUE(gate.due(6));
  EXPECT_FALSE(gate.due(1033333));
  EXPECT_TRUE(gate.due(1066666));
  gate.reset();
  EXPECT_TRUE(gate.due(86400000000ULL));
  EXPECT_FALSE(gate.due(86400000001ULL));
}

TEST(panel_refresh_matches_fixed_original_bottom_decisions) {
  for (const std::uint64_t period : {0ULL, 1ULL, 33333ULL, 50000ULL, 100000ULL}) {
    cth3ds::PanelRefreshGate gate(period);
    r73_original::FrameScheduler original(18000, 33333, period, 3);
    auto compare = [&](std::uint64_t now) {
      EXPECT_EQ(gate.due(now), original.advance(now).render_bottom);
    };
    compare(0);
    compare(0);
    compare(1);
    for (std::uint64_t i = 1; i <= 4000; ++i) {
      if (i % 7 == 0) {
        gate.request_redraw(); original.request_redraw();
        gate.request_redraw(); original.request_redraw();
      }
      if (i % 251 == 0) {
        gate.reset(); original.reset(i * 1000);
      }
      compare(i * 1000);
      if (i % 11 == 0) compare(i * 1000 - 100);
    }
    // A long pause is reset at the actual lifecycle boundary.
    gate.reset(); original.reset(86400000000ULL);
    compare(86400000000ULL);
    compare(86400000001ULL);
  }
}

TEST(panel_refresh_preserves_unreset_long_gaps_at_product_period) {
  cth3ds::PanelRefreshGate gate(33333);
  r73_original::FrameScheduler original(18000, 33333, 33333, 3);
  for (const std::uint64_t now : {0ULL, 3600000000ULL, 86400000000ULL,
                                  86400000001ULL, 1ULL, 86400033333ULL}) {
    EXPECT_EQ(gate.due(now), original.advance(now).render_bottom);
  }
}
