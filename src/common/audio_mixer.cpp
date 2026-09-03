#include "cth3ds/audio_mixer.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include "cth3ds/types.hpp"

namespace cth3ds {
namespace {

std::int16_t saturating_add(std::int16_t current, float value) noexcept {
  const float sum = static_cast<float>(current) + value;
  const float low = static_cast<float>(std::numeric_limits<std::int16_t>::min());
  const float high = static_cast<float>(std::numeric_limits<std::int16_t>::max());
  return static_cast<std::int16_t>(std::lround(clamp_float(sum, low, high)));
}

}  // namespace

StereoGain constant_power_pan(float normalized_position, float volume) noexcept {
  const float position = clamp_float(normalized_position, -1.0F, 1.0F);
  const float safe_volume = clamp_float(volume, 0.0F, 4.0F);
  constexpr float kPiOverFour = 0.7853981633974483F;
  const float angle = (position + 1.0F) * kPiOverFour;
  return {std::cos(angle) * safe_volume, std::sin(angle) * safe_volume};
}

void mix_mono_pcm16_to_stereo(const std::int16_t* input,
                              std::size_t sample_count,
                              std::int16_t* interleaved_output,
                              StereoGain gain) noexcept {
  if (input == nullptr || interleaved_output == nullptr) {
    return;
  }
  for (std::size_t i = 0; i < sample_count; ++i) {
    const float sample = static_cast<float>(input[i]);
    interleaved_output[i * 2U] =
        saturating_add(interleaved_output[i * 2U], sample * gain.left);
    interleaved_output[i * 2U + 1U] =
        saturating_add(interleaved_output[i * 2U + 1U], sample * gain.right);
  }
}

AudioRingBuffer::AudioRingBuffer(std::size_t frames_capacity)
    : samples_(frames_capacity * 2U, 0), capacity_frames_(frames_capacity) {}

std::size_t AudioRingBuffer::write(const std::int16_t* interleaved_stereo,
                                   std::size_t frames) noexcept {
  if (interleaved_stereo == nullptr || capacity_frames_ == 0U) {
    return 0U;
  }
  const std::size_t to_write = std::min(frames, free_frames());
  for (std::size_t i = 0; i < to_write; ++i) {
    const std::size_t destination = ((write_frame_ + i) % capacity_frames_) * 2U;
    samples_[destination] = interleaved_stereo[i * 2U];
    samples_[destination + 1U] = interleaved_stereo[i * 2U + 1U];
  }
  write_frame_ = (write_frame_ + to_write) % capacity_frames_;
  size_frames_ += to_write;
  return to_write;
}

std::size_t AudioRingBuffer::read(std::int16_t* interleaved_stereo,
                                  std::size_t frames) noexcept {
  if (interleaved_stereo == nullptr || capacity_frames_ == 0U) {
    return 0U;
  }
  const std::size_t to_read = std::min(frames, available_frames());
  for (std::size_t i = 0; i < to_read; ++i) {
    const std::size_t source = ((read_frame_ + i) % capacity_frames_) * 2U;
    interleaved_stereo[i * 2U] = samples_[source];
    interleaved_stereo[i * 2U + 1U] = samples_[source + 1U];
  }
  read_frame_ = (read_frame_ + to_read) % capacity_frames_;
  size_frames_ -= to_read;
  return to_read;
}

void AudioRingBuffer::clear() noexcept {
  read_frame_ = 0U;
  write_frame_ = 0U;
  size_frames_ = 0U;
  std::fill(samples_.begin(), samples_.end(), 0);
}

}  // namespace cth3ds
