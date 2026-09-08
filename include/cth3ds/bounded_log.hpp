#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace cth3ds {

// Fixed-capacity SD diagnostics. Exact three paths are supplied by the caller.
// Rotation runs before opening the writer; a failure preserves remaining logs
// and disables this writer. No directory traversal or unbounded retry.
class BoundedLog {
 public:
  // R61 reached 0.95 MiB after 22 minutes. Keep the expanded-hospital run
  // and its terminal evidence within a bounded three-run / 6 MiB SD budget.
  static constexpr std::size_t kLimit = 2U * 1024U * 1024U;
  static constexpr std::size_t kReserve = 16U * 1024U;
  static constexpr std::size_t kBufferSize = 4096U;
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
    return true;
  }
  // Keep fatal evidence visible immediately, including the preceding context.
  void emergency() noexcept { emergency_.store(true); flush(); }
  bool flush() noexcept {
    if (!available()) return false;
    flushes_.fetch_add(1);
    if (std::fflush(file_) != 0) failed_.store(true);
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
    std::array<char, 2048> line{};
    const int result = std::vsnprintf(line.data(), line.size() - 1U, format, arguments);
    if (result < 0) return;
    std::size_t length = std::min(static_cast<std::size_t>(result), line.size() - 2U);
    if (static_cast<std::size_t>(result) > length) {
      constexpr char marker[] = " [line-truncated]";
      std::memcpy(line.data() + length - sizeof(marker) + 1U, marker, sizeof(marker) - 1U);
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
    if (std::fwrite(data, 1U, size, file_) != size) failed_.store(true);
    if (emergency_.load()) flush();
  }
  std::FILE* file_{nullptr};
  // Owned for the entire FILE lifetime; no dynamic allocation or writer thread.
  std::array<char, kBufferSize> buffer_{};
  std::atomic<std::size_t> flushes_{0};
  std::atomic<std::size_t> bytes_{0};
  std::atomic<bool> truncated_{false}, failed_{false}, emergency_{false};
};
}  // namespace cth3ds
