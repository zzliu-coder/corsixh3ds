#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace cth3ds {

struct StereoGain {
  float left{1.0F};
  float right{1.0F};
};

[[nodiscard]] StereoGain constant_power_pan(float normalized_position,
                                            float volume = 1.0F) noexcept;

void mix_mono_pcm16_to_stereo(const std::int16_t* input,
                              std::size_t sample_count,
                              std::int16_t* interleaved_output,
                              StereoGain gain) noexcept;

class AudioRingBuffer {
 public:
  explicit AudioRingBuffer(std::size_t frames_capacity);

  [[nodiscard]] std::size_t write(const std::int16_t* interleaved_stereo,
                                  std::size_t frames) noexcept;
  [[nodiscard]] std::size_t read(std::int16_t* interleaved_stereo,
                                 std::size_t frames) noexcept;
  void clear() noexcept;
  [[nodiscard]] std::size_t available_frames() const noexcept { return size_frames_; }
  [[nodiscard]] std::size_t free_frames() const noexcept { return capacity_frames_ - size_frames_; }

 private:
  std::vector<std::int16_t> samples_{};
  std::size_t capacity_frames_{0};
  std::size_t read_frame_{0};
  std::size_t write_frame_{0};
  std::size_t size_frames_{0};
};

}  // namespace cth3ds
