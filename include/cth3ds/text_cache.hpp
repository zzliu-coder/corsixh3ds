#pragma once
#include <cstddef>
#include <cstdint>

namespace cth3ds {
// Intrusive, main-thread-only ownership list. Nodes live inside the upstream
// cached_text objects. No parallel font manager or extra texture copy.
struct TextCacheNode {
  TextCacheNode *previous{}, *next{};
  void* context{};
  void (*release)(void*) noexcept{};
  std::size_t bytes{};
};
class TextCacheBudget {
 public:
  static constexpr std::size_t limit = 2U * 1024U * 1024U;
  void forget(TextCacheNode& node) noexcept {
    if (!node.release) return;
    if (node.previous) node.previous->next = node.next; else first_ = node.next;
    if (node.next) node.next->previous = node.previous; else last_ = node.previous;
    bytes -= node.bytes;
    node = {};
  }
  void touch(TextCacheNode& node) noexcept {
    if (!node.release || last_ == &node) return;
    const auto saved = node;
    forget(node);
    append(node, saved.bytes, saved.context, saved.release);
  }
  void reserve(TextCacheNode& node, std::size_t amount, void* context,
               void (*release)(void*) noexcept) noexcept {
    forget(node);
    while (first_ && (amount > limit || bytes > limit - amount)) {
      auto* victim = first_;
      auto fn = victim->release;
      auto ctx = victim->context;
      forget(*victim);
      fn(ctx);
      ++evictions;
    }
    append(node, amount, context, release);
    if (amount > limit) ++oversize;
  }
  // A single unusually large layout may be transient. It is never retained
  // past the current measure/draw call. Callers report these separately.
  void finish(TextCacheNode& node) noexcept {
    if (node.release && node.bytes > limit) {
      auto fn = node.release; auto ctx = node.context;
      forget(node); fn(ctx);
    }
  }
  std::size_t bytes{}, peak{};
  std::uint64_t evictions{}, oversize{};
 private:
  void append(TextCacheNode& node, std::size_t amount, void* context,
              void (*release)(void*) noexcept) noexcept {
    node = {last_, nullptr, context, release, amount};
    if (last_) last_->next = &node; else first_ = &node;
    last_ = &node;
    bytes += amount;
    if (bytes > peak) peak = bytes;
  }
  TextCacheNode *first_{}, *last_{};
};
inline TextCacheBudget text_cache;
} // namespace cth3ds
