#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace cth3ds {

struct TextureCacheEntry {
  std::string key{};
  std::size_t bytes{0};
  std::uint64_t last_used{0};
  bool pinned{false};
};

class TextureCache {
 public:
  explicit TextureCache(std::size_t budget_bytes);

  [[nodiscard]] bool insert(std::string key, std::size_t bytes,
                            bool pinned = false);
  [[nodiscard]] bool touch(const std::string& key) noexcept;
  [[nodiscard]] bool erase(const std::string& key) noexcept;
  void set_budget(std::size_t budget_bytes);
  void clear_unpinned() noexcept;

  [[nodiscard]] bool contains(const std::string& key) const noexcept;
  [[nodiscard]] std::size_t used_bytes() const noexcept { return used_bytes_; }
  [[nodiscard]] std::size_t budget_bytes() const noexcept { return budget_bytes_; }
  [[nodiscard]] std::vector<std::string> keys_by_recency() const;
  [[nodiscard]] const TextureCacheEntry* find(const std::string& key) const noexcept;

 private:
  [[nodiscard]] bool make_room(std::size_t bytes_needed);
  [[nodiscard]] std::optional<std::string> least_recent_unpinned() const;

  std::size_t budget_bytes_{0};
  std::size_t used_bytes_{0};
  std::uint64_t clock_{0};
  std::unordered_map<std::string, TextureCacheEntry> entries_{};
};

}  // namespace cth3ds
