#include "test_framework.hpp"

#include <array>
#include <cstdint>

#include "cth3ds/audio_mixer.hpp"

TEST(audio_pan_is_centered_at_equal_power) {
  const auto gain = cth3ds::constant_power_pan(0.0F, 1.0F);
  EXPECT_NEAR(gain.left, 0.707106, 0.0001);
  EXPECT_NEAR(gain.right, 0.707106, 0.0001);
}

TEST(audio_pan_clamps_position) {
  const auto left = cth3ds::constant_power_pan(-2.0F, 1.0F);
  const auto right = cth3ds::constant_power_pan(2.0F, 1.0F);
  EXPECT_NEAR(left.left, 1.0, 0.0001);
  EXPECT_NEAR(left.right, 0.0, 0.0001);
  EXPECT_NEAR(right.left, 0.0, 0.0001);
  EXPECT_NEAR(right.right, 1.0, 0.0001);
}

TEST(audio_mixer_saturates_pcm16) {
  const std::array<std::int16_t, 2> mono{30000, -30000};
  std::array<std::int16_t, 4> stereo{10000, 10000, -10000, -10000};
  cth3ds::mix_mono_pcm16_to_stereo(mono.data(), mono.size(), stereo.data(),
                                   {1.0F, 1.0F});
  EXPECT_EQ(stereo[0], std::int16_t{32767});
  EXPECT_EQ(stereo[1], std::int16_t{32767});
  EXPECT_EQ(stereo[2], std::int16_t{-32768});
  EXPECT_EQ(stereo[3], std::int16_t{-32768});
}

TEST(audio_ring_buffer_wraps_without_data_loss) {
  cth3ds::AudioRingBuffer ring(3);
  const std::array<std::int16_t, 4> first{1, 2, 3, 4};
  EXPECT_EQ(ring.write(first.data(), 2), std::size_t{2});
  std::array<std::int16_t, 2> one{};
  EXPECT_EQ(ring.read(one.data(), 1), std::size_t{1});
  EXPECT_EQ(one[0], std::int16_t{1});
  const std::array<std::int16_t, 4> second{5, 6, 7, 8};
  EXPECT_EQ(ring.write(second.data(), 2), std::size_t{2});
  std::array<std::int16_t, 6> all{};
  EXPECT_EQ(ring.read(all.data(), 3), std::size_t{3});
  EXPECT_EQ(all[0], std::int16_t{3});
  EXPECT_EQ(all[2], std::int16_t{5});
  EXPECT_EQ(all[4], std::int16_t{7});
}
