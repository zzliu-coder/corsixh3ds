#pragma once

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace cth3ds {

struct ResourceEntry {
  std::string path{};
  std::uint64_t offset{0};
  std::uint64_t size{0};
  std::uint32_t checksum{0};
  std::uint16_t flags{0};
};

class ResourcePack {
 public:
  ResourcePack() = default;
  ResourcePack(const ResourcePack&) = delete;
  ResourcePack& operator=(const ResourcePack&) = delete;
  ResourcePack(ResourcePack&&) noexcept = default;
  ResourcePack& operator=(ResourcePack&&) noexcept = default;

  [[nodiscard]] bool open(const std::filesystem::path& path, std::string& error);
  void close() noexcept;
  [[nodiscard]] bool is_open() const noexcept { return stream_.is_open(); }
  [[nodiscard]] std::size_t file_count() const noexcept { return entries_.size(); }
  [[nodiscard]] const ResourceEntry* find(const std::string& path) const noexcept;
  [[nodiscard]] std::optional<std::vector<std::uint8_t>> read(
      const std::string& path, bool verify_checksum, std::string& error);
  [[nodiscard]] std::vector<std::string> paths() const;

 private:
  std::ifstream stream_{};
  std::uint64_t archive_size_{0};
  std::unordered_map<std::string, ResourceEntry> entries_{};
};

struct PackInputFile {
  std::string path{};
  std::vector<std::uint8_t> data{};
  std::uint16_t flags{0};
};

[[nodiscard]] bool write_resource_pack(const std::filesystem::path& path,
                                       std::vector<PackInputFile> files,
                                       std::string& error);

}  // namespace cth3ds
