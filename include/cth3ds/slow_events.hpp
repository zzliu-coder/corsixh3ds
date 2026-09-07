#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace cth3ds {
// Main-thread, allocation-free breadcrumbs. SD output is deferred to the
// ordinary observation flush; no per-event I/O or game state changes.
class SlowEvents {
 public:
  static constexpr std::size_t capacity = 32;
  static constexpr std::uint64_t threshold_us = 50000;
  struct Entry {
    std::uint64_t begin{}, elapsed{};
    std::array<char,24> kind{};
    std::array<char,96> identity{};
    std::array<char,64> owner{};
    bool success{};
  };
  void clear() noexcept {
    head_ = count_ = 0;
    dropped_ = 0;
    owner_.fill(0);
  }
  void record(std::uint64_t begin, std::uint64_t end, const char* kind,
              const char* identity, bool success=true, bool force=false) noexcept {
    if(end<begin || (!force && success && end-begin<threshold_us)) return;
    auto& e=entries_[(head_+count_)%capacity];
    e={};e.begin=begin;e.elapsed=end-begin;e.success=success;
    copy(e.kind,kind);copy(e.identity,identity);e.owner=owner_;
    if(count_<capacity) ++count_;
    else {head_=(head_+1)%capacity;++dropped_;}
  }
  void owner(std::uint64_t now, const char* identity) noexcept {
    std::array<char,64> value{};copy(value,identity);
    if(value==owner_) return;
    owner_=value;record(now,now,"window",owner_.data(),true,true);
  }
  void drain(void (*line)(const char*,...)) noexcept {
    if(!count_ && !dropped_) return;
    line("slow-events: rows=%lu dropped=%llu threshold_us=50000 capacity=32",
         (unsigned long)count_,(unsigned long long)dropped_);
    for(std::size_t i=0;i<count_;++i) {
      const auto& e=entries_[(head_+i)%capacity];
      line("slow-event: begin_us=%llu elapsed_us=%llu kind=%s identity=\"%s\" owner=\"%s\" success=%d",
           (unsigned long long)e.begin,(unsigned long long)e.elapsed,
           e.kind.data(),e.identity.data(),e.owner.data(),e.success);
    }
    head_=count_=0;dropped_=0;
  }
 private:
  template<std::size_t N> static void copy(std::array<char,N>& dst,const char* src) noexcept {
    std::size_t i=0;
    if(src) for(;i+1<N && src[i];++i) {
      const auto c=static_cast<unsigned char>(src[i]);
      dst[i]=(c<32 || c=='"' || c=='\\')?'_':src[i];
    }
    dst[i]=0;
  }
  std::array<Entry,capacity> entries_{};
  std::array<char,64> owner_{};
  std::size_t head_{},count_{};
  std::uint64_t dropped_{};
};
} // namespace cth3ds
