#include "cth3ds/texture_cache.hpp"

#include <algorithm>
#include <utility>

namespace cth3ds {

TextureCache::TextureCache(std::size_t budget_bytes) : budget_bytes_(budget_bytes) {}

bool TextureCache::insert(std::string key, std::size_t bytes, bool pinned) {
  const auto existing = entries_.find(key);
  if (existing != entries_.end()) {
    used_bytes_ -= existing->second.bytes;
    entries_.erase(existing);
  }
  if (bytes > budget_bytes_ || !make_room(bytes)) {
    return false;
  }
  TextureCacheEntry entry;
  entry.key = std::move(key);
  entry.bytes = bytes;
  entry.last_used = ++clock_;
  entry.pinned = pinned;
  used_bytes_ += bytes;
  entries_.emplace(entry.key, std::move(entry));
  return true;
}

bool TextureCache::touch(const std::string& key) noexcept {
  const auto iterator = entries_.find(key);
  if (iterator == entries_.end()) {
    return false;
  }
  iterator->second.last_used = ++clock_;
  return true;
}

bool TextureCache::erase(const std::string& key) noexcept {
  const auto iterator = entries_.find(key);
  if (iterator == entries_.end()) {
    return false;
  }
  used_bytes_ -= iterator->second.bytes;
  entries_.erase(iterator);
  return true;
}

void TextureCache::set_budget(std::size_t budget_bytes) {
  budget_bytes_ = budget_bytes;
  (void)make_room(0);
}

void TextureCache::clear_unpinned() noexcept {
  for (auto iterator = entries_.begin(); iterator != entries_.end();) {
    if (!iterator->second.pinned) {
      used_bytes_ -= iterator->second.bytes;
      iterator = entries_.erase(iterator);
    } else {
      ++iterator;
    }
  }
}

bool TextureCache::contains(const std::string& key) const noexcept {
  return entries_.find(key) != entries_.end();
}

const TextureCacheEntry* TextureCache::find(const std::string& key) const noexcept {
  const auto iterator = entries_.find(key);
  return iterator == entries_.end() ? nullptr : &iterator->second;
}

std::vector<std::string> TextureCache::keys_by_recency() const {
  std::vector<const TextureCacheEntry*> sorted;
  sorted.reserve(entries_.size());
  for (const auto& item : entries_) {
    sorted.push_back(&item.second);
  }
  std::sort(sorted.begin(), sorted.end(),
            [](const TextureCacheEntry* left, const TextureCacheEntry* right) {
              return left->last_used > right->last_used;
            });
  std::vector<std::string> keys;
  keys.reserve(sorted.size());
  for (const auto* entry : sorted) {
    keys.push_back(entry->key);
  }
  return keys;
}

bool TextureCache::make_room(std::size_t bytes_needed) {
  if (bytes_needed > budget_bytes_) {
    return false;
  }
  while (used_bytes_ > budget_bytes_ - bytes_needed) {
    const auto victim = least_recent_unpinned();
    if (!victim) {
      return false;
    }
    (void)erase(*victim);
  }
  return true;
}

std::optional<std::string> TextureCache::least_recent_unpinned() const {
  const TextureCacheEntry* victim = nullptr;
  for (const auto& item : entries_) {
    const TextureCacheEntry& entry = item.second;
    if (!entry.pinned && (victim == nullptr || entry.last_used < victim->last_used)) {
      victim = &entry;
    }
  }
  return victim == nullptr ? std::nullopt : std::optional<std::string>(victim->key);
}

}  // namespace cth3ds
