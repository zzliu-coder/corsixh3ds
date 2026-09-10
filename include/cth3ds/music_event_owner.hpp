#pragma once

#include <atomic>
#include <cstdint>
#include <limits>

namespace cth3ds {

// Owns notification identity, not a decoder or the playlist. There is one main
// thread (begin/invalidate/consume), and the SDL mixer callback is the producer.
// Before begin(), the caller MUST disable the finish hook and halt/join the old
// mixer playback. A callback has no decoder argument: without that fence it
// could mistake a newly published generation for the old decoder's completion.
class MusicEventOwner {
 public:
  using Token = std::int32_t; // Losslessly stored in SDL_UserEvent::code.
  enum class Phase : std::uint32_t {
    inactive = 0, playing = 1, completed = 2, delivery_failed = 3
  };
  struct Snapshot { Token token; Phase phase; };

  static_assert(std::atomic<std::uint32_t>::is_always_lock_free,
                "Music callback requires lock-free 32-bit atomics");
  static constexpr Token max_token =
      static_cast<Token>(std::numeric_limits<std::uint32_t>::max() >> 2);

  // Seed is only useful for exhaustion testing. Zero is the production start.
  explicit MusicEventOwner(Token last_issued = 0) noexcept
      : last_issued_(last_issued >= 0 && last_issued <= max_token
                         ? last_issued : max_token) {}

  Token begin() noexcept {
    if (last_issued_ == max_token) {
      state_.store(0, std::memory_order_release);
      return 0; // Fail closed; an old queued token can never alias a new song.
    }
    const Token token = ++last_issued_;
    state_.store(pack(token, Phase::playing), std::memory_order_release);
    return token;
  }

  // Explicit stop/destroy invalidates even an EOF already removed from SDL's
  // queue. Freeing an older, non-current music userdata uses its own token.
  void invalidate(Token token) noexcept {
    if (token > 0 && snapshot().token == token)
      state_.store(0, std::memory_order_release);
  }
  void invalidate_all() noexcept { state_.store(0, std::memory_order_release); }

  // Mixer callback: O(1), no allocation, mutex, retry loop, or Lua access.
  // Return zero for duplicate callbacks, explicit stops, or no active playback.
  Token completed() noexcept {
    auto expected = state_.load(std::memory_order_acquire);
    if ((expected & 3U) != static_cast<std::uint32_t>(Phase::playing)) return 0;
    const auto token = static_cast<Token>(expected >> 2);
    return state_.compare_exchange_strong(expected, pack(token, Phase::completed),
               std::memory_order_acq_rel, std::memory_order_acquire) ? token : 0;
  }

  // SDL_PushEvent <= 0 means the completion was filtered or lost. Keep this
  // observable; it must not look like another playing song or a valid dispatch.
  void delivery_failed(Token token) noexcept {
    if (token <= 0) return;
    auto expected = pack(token, Phase::completed);
    state_.compare_exchange_strong(expected, pack(token, Phase::delivery_failed),
        std::memory_order_acq_rel, std::memory_order_acquire);
  }

  // Called immediately before dispatching music_over. Only the first event for
  // the current naturally completed playback may advance the original playlist.
  bool consume(Token token) noexcept {
    if (token <= 0 || token > max_token) return false;
    auto expected = pack(token, Phase::completed);
    return state_.compare_exchange_strong(expected, pack(token, Phase::inactive),
        std::memory_order_acq_rel, std::memory_order_acquire);
  }

  Snapshot snapshot() const noexcept {
    const auto value = state_.load(std::memory_order_acquire);
    return {static_cast<Token>(value >> 2), static_cast<Phase>(value & 3U)};
  }

 private:
  static constexpr std::uint32_t pack(Token token, Phase phase) noexcept {
    return (static_cast<std::uint32_t>(token) << 2) |
           static_cast<std::uint32_t>(phase);
  }
  std::atomic<std::uint32_t> state_{0};
  Token last_issued_; // Main thread only; never read by the callback.
};

// The generated SDL audio/core and platform health reader share this one owner.
// C++17 inline storage avoids separate per-translation-unit event identities.
inline MusicEventOwner music_event_owner;

} // namespace cth3ds
