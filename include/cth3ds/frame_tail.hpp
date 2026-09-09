#pragma once
#include <array>
#include <cstdint>
#include <limits>
#include "cth3ds/telemetry.hpp"

namespace cth3ds {
enum class FramePhase : std::uint8_t {
  Other, GCObserve, GCStep, Flush, Wait, Runtime, Benchmark, Count
};
inline constexpr std::array<const char*,7> kFramePhaseNames{
  "loop_other", "gc_observe", "gc_step", "observation_flush",
  "event_wait", "runtime", "benchmark_call"};

// Exclusive wall-clock residency. Independent of the Telemetry span stack:
// a flush may reset that stack's window while this sample remains open.
class FrameTail {
 public:
  enum class FlushAction : std::uint8_t { None, Compact, Full, Deferred, CompactDeferred, Terminal };
  struct Token { std::uint32_t epoch{}, depth{}; FramePhase previous{}; };
  struct Record {
    std::array<std::uint64_t,7> whole{}, first_prefix{}, last_prefix{};
    std::uint64_t sequence{}, begin{}, end{}, first{}, last{};
    std::uint64_t success{}, failed{}, skipped{};
    std::uint64_t flush_begin{}, flush_end{};
    std::uint32_t epoch{},flush_reason{}, invalid{};
    FramePhase begin_phase{}, end_phase{};
    FlushAction flush_action{};
    bool flush_completed{};
  };
  enum Fault : std::uint32_t { Clock=1, Overflow=2, Scope=4, Order=8 };
  void reset() noexcept {
    ++epoch_; if(!epoch_)++epoch_;
    depth_=0; phase_=FramePhase::Other; active_=false; pending_=false; cursor_=0; record_={};
  }
  bool active() const noexcept { return active_; }
  bool take_report() noexcept {const bool pending=pending_;pending_=false;return pending;}
  const Record& record() const noexcept { return record_; }
  Token enter(FramePhase phase,std::uint64_t now) noexcept {
    settle(now);
    if(phase>=FramePhase::Count || depth_==std::numeric_limits<std::uint32_t>::max()) {
      record_.invalid|=Scope; return {};
    }
    const Token token{epoch_,++depth_,phase_}; phase_=phase; return token;
  }
  void leave(Token token,std::uint64_t now) noexcept {
    if(token.epoch!=epoch_ || !token.depth || token.depth!=depth_) {
      record_.invalid|=Scope; return;
    }
    settle(now); --depth_; phase_=token.previous;
  }
  void begin(std::uint64_t now) noexcept {
    if(active_){record_.invalid|=Order;return;}
    const auto sequence=record_.sequence;
    record_={}; record_.sequence=sequence; add(record_.sequence,1);
    record_.epoch=epoch_;record_.begin=cursor_=now; record_.begin_phase=phase_; active_=true;
  }
  void present(std::uint64_t now,PresentResult result) noexcept {
    if(!active_)return;
    settle(now);
    if(result==PresentResult::Failed){add(record_.failed,1);return;}
    if(result!=PresentResult::Success){add(record_.skipped,1);return;}
    if(!record_.success){record_.first=now;record_.first_prefix=record_.whole;}
    record_.last=now;record_.last_prefix=record_.whole;add(record_.success,1);
  }
  void close(std::uint64_t now) noexcept {
    if(!active_){record_.invalid|=Order;return;}
    settle(now);record_.end=now;record_.end_phase=phase_;active_=false;pending_=true;
  }
  void flush_begin(std::uint64_t now,std::uint32_t reason) noexcept {
    if(!active_)return;
    record_.flush_begin=now;record_.flush_end=0;record_.flush_reason=reason;record_.flush_action=FlushAction::None;
    record_.flush_completed=false;
  }
  void flush_action(FlushAction action) noexcept {if(active_)record_.flush_action=action;}
  void flush_end(std::uint64_t now) noexcept {
    if(!active_)return;
    record_.flush_end=now;record_.flush_completed=true;
    if(now<record_.flush_begin)record_.invalid|=Clock;
  }
 private:
  void add(std::uint64_t& value,std::uint64_t delta) noexcept {
    if(delta>std::numeric_limits<std::uint64_t>::max()-value){record_.invalid|=Overflow;return;}
    value+=delta;
  }
  void settle(std::uint64_t now) noexcept {
    if(!active_)return;
    if(now<cursor_){record_.invalid|=Clock;return;}
    add(record_.whole[static_cast<unsigned>(phase_)],now-cursor_);cursor_=now;
  }
  Record record_{};
  std::uint64_t cursor_{};
  std::uint32_t epoch_{1},depth_{};
  FramePhase phase_{FramePhase::Other};
  bool active_{},pending_{};
};
static_assert(sizeof(FrameTail)<=512,"frame-tail diagnostics must remain bounded");
} // namespace cth3ds
