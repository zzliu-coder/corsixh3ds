#pragma once
#include <atomic>
#include "cth3ds/hid_snapshot.hpp"
#include "cth3ds/input_queue.hpp"

namespace cth3ds {
// Only the sampler touches HID shared memory. Only the game thread calls Lua,
// SDL input/rendering, or writes logs. SDL's own hidScanInput globals are unused.
class InputCollector3ds {
 public:
  using Clock = std::uint64_t (*)() noexcept;
  bool start(Clock clock) noexcept {
#ifndef CTH3DS_STUB_BUILD
    if (thread_) return !stopping_.load();
    LightLock_Init(&lock_); clock_ = clock;
    if (!R_SUCCEEDED(hidInit())) return false;
    owns_hid_ = true; stopping_.store(false);
    s32 priority = 0x30;
    (void)svcGetThreadPriority(&priority, CUR_THREAD_HANDLE);
    priority = std::max<s32>(0x18, std::min<s32>(0x3f, priority - 1));
    // Old 3DS application core, 8 KiB stack; no additional-core requirement.
    thread_ = threadCreate(&run, this, 8192, priority, 0, false);
    if (!thread_) { hidExit(); owns_hid_ = false; return false; }
#else
    (void)clock;
#endif
    return true;
  }
  bool stop() noexcept {
#ifndef CTH3DS_STUB_BUILD
    stopping_.store(true);
    if (thread_) {
      if (!R_SUCCEEDED(threadJoin(thread_, 1000000000ULL))) return false;
      threadFree(thread_); thread_ = nullptr;
    }
    if (owns_hid_) { hidExit(); owns_hid_ = false; }
#endif
    return true;
  }
  bool pop(RawInputSnapshot& out, std::uint64_t now) noexcept {
    Guard guard(*this); return queue_.pop(out, now);
  }
  void push_for_host(const RawInputSnapshot& in) noexcept {
    Guard guard(*this); queue_.push(in);
  }
  void discard() noexcept { Guard guard(*this); queue_.discard(); }
  bool take_cancellation() noexcept { Guard guard(*this); return queue_.take_cancellation(); }
  InputQueue::Statistics statistics() noexcept { Guard guard(*this); return queue_.statistics(); }
  std::size_t size() noexcept { Guard guard(*this); return queue_.size(); }
  void pause(bool paused) noexcept { paused_.store(paused); discard(); }
 private:
  struct Guard {
    InputCollector3ds& owner;
    explicit Guard(InputCollector3ds& o) : owner(o) {
#ifndef CTH3DS_STUB_BUILD
      LightLock_Lock(&owner.lock_);
#endif
    }
    ~Guard() {
#ifndef CTH3DS_STUB_BUILD
      LightLock_Unlock(&owner.lock_);
#endif
    }
  };
#ifndef CTH3DS_STUB_BUILD
  static void run(void* opaque) {
    auto& self = *static_cast<InputCollector3ds*>(opaque);
    while (!self.stopping_.load()) {
      RawInputSnapshot snapshot;
      if (!self.paused_.load() && read_hid_snapshot(hidSharedMem, self.clock_(), snapshot)) {
        Guard guard(self);
        if (!self.paused_.load()) self.queue_.push(snapshot);
      }
      svcSleepThread(8000000LL);
    }
  }
  LightLock lock_{};
  Thread thread_{};
  Clock clock_{};
  bool owns_hid_{};
#endif
  InputQueue queue_{};
  std::atomic<bool> stopping_{false}, paused_{false};
};
} // namespace cth3ds
