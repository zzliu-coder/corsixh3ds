#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <limits>
#include "cth3ds/log_format.hpp"

namespace cth3ds {

// Fixed-capacity SD diagnostics. Exact three paths are supplied by the caller.
// Rotation runs before opening the writer; a failure preserves remaining logs
// and disables this writer. No directory traversal or unbounded retry.
class BoundedLog {
 public:
  using Clock = std::uint64_t (*)() noexcept;
  struct Cost { std::uint64_t calls{}, total_us{}, max_us{}; };
  struct Costs { Cost format, write, flush; std::uint64_t fast{}, fallback{}; bool valid{true}; };
  void set_clock(Clock clock) noexcept { clock_=clock; }
  const Costs& costs() const noexcept { return costs_; }
  // R61 reached 0.95 MiB after 22 minutes. Keep the expanded-hospital run
  // and its terminal evidence within a bounded three-run / 6 MiB SD budget.
  static constexpr std::size_t kLimit = 2U * 1024U * 1024U;
  static constexpr std::size_t kReserve = 16U * 1024U;
  // One ordinary 10-second report is 4.4--5.4 KiB on the R69 run. Keep it
  // together until its existing flush boundary, in FILE-owned static storage.
  static constexpr std::size_t kBufferSize = 8192U;
  ~BoundedLog() { close(); }
  bool open(const char* current, const char* previous, const char* oldest) noexcept {
    close();
    if (!remove_optional(oldest) || !rename_optional(previous, oldest) ||
        !rename_optional(current, previous)) return false;
    file_ = std::fopen(current, "wb");
    if (!file_) return false;
    if (std::setvbuf(file_, buffer_.data(), _IOFBF, buffer_.size()) != 0) {
      std::fclose(file_); file_ = nullptr; return false;
    }
    bytes_.store(0); truncated_.store(false); failed_.store(false);
    emergency_.store(false); flushes_.store(0);
    costs_={};
    return true;
  }
  // Keep fatal evidence visible immediately, including the preceding context.
  void emergency() noexcept { emergency_.store(true); flush(); }
  bool flush() noexcept {
    if (!available()) return false;
    flushes_.fetch_add(1);
    const auto started=tick();
    const int result=std::fflush(file_);
    record(costs_.flush,started);
    if (result != 0) failed_.store(true);
    return !failed_.load();
  }
  void write(const char* data, std::size_t length) noexcept {
    if (!file_ || failed_.load()) return;
    const auto limit = emergency_.load() ? kLimit : kLimit - kReserve;
    auto prior = bytes_.load();
    while (true) {
      if (length > limit || prior > limit - length) {
        if (!truncated_.exchange(true)) {
          static constexpr char message[] = "\nlog-truncated: normal-capacity-exhausted error-reserve=16384\n";
          // A truncation notice may use the reserved error space.
          const auto count = sizeof(message) - 1U;
          prior = bytes_.fetch_add(count);
          if (prior <= kLimit - count) write_bytes(message, count);
        }
        return;
      }
      if (bytes_.compare_exchange_weak(prior, prior + length)) break;
    }
    write_bytes(data, length);
  }
  void vline(const char* format, std::va_list arguments) noexcept {
    std::array<char, 2048> line;
    const auto started=tick();
    std::size_t fast_length=0;
    std::va_list copy; va_copy(copy,arguments);
    const bool fast=log_detail::format(line.data(),line.size()-2U,fast_length,format,copy);
    va_end(copy);
    const int result = fast ? static_cast<int>(fast_length) :
      std::vsnprintf(line.data(), line.size() - 1U, format, arguments);
    record(costs_.format,started);
    add(fast?costs_.fast:costs_.fallback,1);
    if (result < 0) return;
    std::size_t length = std::min(static_cast<std::size_t>(result), line.size() - 2U);
    if (static_cast<std::size_t>(result) > length) {
      constexpr char marker[] = " [line-truncated]";
      std::memcpy(line.data() + length - sizeof(marker) + 1U, marker, sizeof(marker) - 1U);
    }
    line[length++] = '\n';
    write(line.data(), length);
  }
  // Preformatted producers retain the same 2046-byte payload and truncation
  // marker as vline("%s", text), without invoking the formatter a second time.
  void line(const char* text) noexcept {
    std::array<char, 2048> line;
    std::size_t length = 0;
    if (text) {
      while (length < line.size() - 2U && text[length]) ++length;
      std::memcpy(line.data(), text, length);
      if (text[length]) {
        constexpr char marker[] = " [line-truncated]";
        std::memcpy(line.data() + length - sizeof(marker) + 1U, marker, sizeof(marker) - 1U);
      }
    }
    line[length++] = '\n';
    write(line.data(), length);
  }
  void close() noexcept {
    if (file_) {
      flush();
      if (std::fclose(file_) != 0) failed_.store(true);
      file_ = nullptr;
    }
  }
  bool available() const noexcept { return file_ && !failed_.load(); }
  bool truncated() const noexcept { return truncated_.load(); }
  std::size_t bytes() const noexcept { return bytes_.load(); }
  std::size_t flushes() const noexcept { return flushes_.load(); }
  bool failed() const noexcept { return failed_.load(); }
 private:
  static bool remove_optional(const char* path) noexcept {
    return std::remove(path) == 0 || errno == ENOENT;
  }
  static bool rename_optional(const char* from, const char* to) noexcept {
    return std::rename(from, to) == 0 || errno == ENOENT;
  }
  void write_bytes(const char* data, std::size_t size) noexcept {
    const auto started=tick();
    const auto written=std::fwrite(data, 1U, size, file_);
    record(costs_.write,started);
    if (written != size) failed_.store(true);
    if (emergency_.load()) flush();
  }
  std::uint64_t tick() const noexcept { return clock_?clock_():0; }
  void add(std::uint64_t& value,std::uint64_t delta) noexcept {
    if(delta>std::numeric_limits<std::uint64_t>::max()-value) {
      costs_.valid=false; value=std::numeric_limits<std::uint64_t>::max();
    } else value+=delta;
  }
  void record(Cost& cost,std::uint64_t started) noexcept {
    const auto ended=tick();
    if(ended<started) costs_.valid=false;
    const auto elapsed=ended>=started?ended-started:0;
    add(cost.calls,1); add(cost.total_us,elapsed); cost.max_us=std::max(cost.max_us,elapsed);
  }
  Clock clock_{};
  Costs costs_{};
  std::FILE* file_{nullptr};
  // Owned for the entire FILE lifetime; no dynamic allocation or writer thread.
  std::array<char, kBufferSize> buffer_{};
  std::atomic<std::size_t> flushes_{0};
  std::atomic<std::size_t> bytes_{0};
  std::atomic<bool> truncated_{false}, failed_{false}, emergency_{false};
};
}  // namespace cth3ds
