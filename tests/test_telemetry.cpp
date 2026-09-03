#include "test_framework.hpp"

#include "cth3ds/telemetry.hpp"

TEST(telemetry_calculates_average_percentile_and_maximum) {
  cth3ds::Telemetry telemetry(10);
  telemetry.record_frame(10000, false);
  telemetry.record_frame(20000, true);
  telemetry.record_frame(30000, false);
  telemetry.record_frame(40000, false);
  telemetry.set_memory(1024, 2048);
  const auto snapshot = telemetry.snapshot();
  EXPECT_NEAR(snapshot.average_frame_ms, 25.0, 0.001);
  EXPECT_NEAR(snapshot.p95_frame_ms, 30.0, 0.001);
  EXPECT_NEAR(snapshot.maximum_frame_ms, 40.0, 0.001);
  EXPECT_EQ(snapshot.dropped_frames, std::uint64_t{1});
  EXPECT_EQ(snapshot.texture_bytes, std::size_t{1024});
  EXPECT_EQ(snapshot.linear_bytes, std::size_t{2048});
}

TEST(telemetry_history_is_bounded) {
  cth3ds::Telemetry telemetry(2);
  telemetry.record_frame(1000, false);
  telemetry.record_frame(2000, false);
  telemetry.record_frame(9000, false);
  const auto snapshot = telemetry.snapshot();
  EXPECT_NEAR(snapshot.average_frame_ms, 5.5, 0.001);
}
