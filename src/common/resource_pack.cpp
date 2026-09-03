#include "cth3ds/resource_pack.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>

#include "cth3ds/crc32.hpp"

namespace cth3ds {
namespace {

constexpr std::array<char, 8> kMagic{'C', 'T', 'H', '3', 'D', 'P', 'K', '1'};
constexpr std::uint32_t kVersion = 1U;
constexpr std::uint64_t kHeaderSize = 40U;
constexpr std::uint32_t kMaximumFiles = 200000U;
constexpr std::uint16_t kMaximumPathLength = 4096U;

void write_u16(std::ostream& stream, std::uint16_t value) {
  const std::array<char, 2> bytes{
      static_cast<char>(value & 0xFFU),
      static_cast<char>((value >> 8U) & 0xFFU),
  };
  stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

void write_u32(std::ostream& stream, std::uint32_t value) {
  std::array<char, 4> bytes{};
  for (unsigned int i = 0; i < 4U; ++i) {
    bytes[static_cast<std::size_t>(i)] =
        static_cast<char>((value >> (i * 8U)) & 0xFFU);
  }
  stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

void write_u64(std::ostream& stream, std::uint64_t value) {
  std::array<char, 8> bytes{};
  for (unsigned int i = 0; i < 8U; ++i) {
    bytes[static_cast<std::size_t>(i)] =
        static_cast<char>((value >> (i * 8U)) & 0xFFU);
  }
  stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

bool read_exact(std::istream& stream, char* destination, std::size_t size) {
  if (size > static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max())) {
    return false;
  }
  stream.read(destination, static_cast<std::streamsize>(size));
  return stream.good();
}

bool read_u16(std::istream& stream, std::uint16_t& value) {
  std::array<unsigned char, 2> bytes{};
  if (!read_exact(stream, reinterpret_cast<char*>(bytes.data()), bytes.size())) {
    return false;
  }
  value = static_cast<std::uint16_t>(bytes[0]) |
          static_cast<std::uint16_t>(static_cast<std::uint16_t>(bytes[1]) << 8U);
  return true;
}

bool read_u32(std::istream& stream, std::uint32_t& value) {
  std::array<unsigned char, 4> bytes{};
  if (!read_exact(stream, reinterpret_cast<char*>(bytes.data()), bytes.size())) {
    return false;
  }
  value = 0U;
  for (unsigned int i = 0; i < 4U; ++i) {
    value |= static_cast<std::uint32_t>(bytes[static_cast<std::size_t>(i)]) <<
             (i * 8U);
  }
  return true;
}

bool read_u64(std::istream& stream, std::uint64_t& value) {
  std::array<unsigned char, 8> bytes{};
  if (!read_exact(stream, reinterpret_cast<char*>(bytes.data()), bytes.size())) {
    return false;
  }
  value = 0U;
  for (unsigned int i = 0; i < 8U; ++i) {
    value |= static_cast<std::uint64_t>(bytes[static_cast<std::size_t>(i)]) <<
             (i * 8U);
  }
  return true;
}

std::string normalize_path(std::string path) {
  std::replace(path.begin(), path.end(), '\\', '/');
  while (path.rfind("./", 0) == 0) {
    path.erase(0, 2);
  }
  return path;
}

std::uint64_t index_size(const std::vector<PackInputFile>& files) {
  std::uint64_t size = 0U;
  for (const auto& file : files) {
    size += 2U + 2U + 4U + 8U + 8U +
            static_cast<std::uint64_t>(file.path.size());
  }
  return size;
}

}  // namespace

bool ResourcePack::open(const std::filesystem::path& path, std::string& error) {
  close();
  stream_.open(path, std::ios::binary);
  if (!stream_) {
    error = "cannot open resource pack";
    return false;
  }
  stream_.seekg(0, std::ios::end);
  const std::streamoff size = stream_.tellg();
  if (size < static_cast<std::streamoff>(kHeaderSize)) {
    error = "resource pack is too small";
    close();
    return false;
  }
  archive_size_ = static_cast<std::uint64_t>(size);
  stream_.seekg(0, std::ios::beg);

  std::array<char, 8> magic{};
  std::uint32_t version = 0U;
  std::uint32_t count = 0U;
  std::uint64_t index_offset = 0U;
  std::uint64_t data_offset = 0U;
  std::uint64_t reserved = 0U;
  if (!read_exact(stream_, magic.data(), magic.size()) ||
      !read_u32(stream_, version) || !read_u32(stream_, count) ||
      !read_u64(stream_, index_offset) || !read_u64(stream_, data_offset) ||
      !read_u64(stream_, reserved)) {
    error = "truncated resource pack header";
    close();
    return false;
  }
  (void)reserved;
  if (magic != kMagic || version != kVersion) {
    error = "unsupported resource pack format";
    close();
    return false;
  }
  if (count > kMaximumFiles || index_offset < kHeaderSize ||
      data_offset < index_offset || data_offset > archive_size_) {
    error = "invalid resource pack header values";
    close();
    return false;
  }

  stream_.seekg(static_cast<std::streamoff>(index_offset), std::ios::beg);
  for (std::uint32_t i = 0U; i < count; ++i) {
    std::uint16_t path_length = 0U;
    ResourceEntry entry;
    if (!read_u16(stream_, path_length) || !read_u16(stream_, entry.flags) ||
        !read_u32(stream_, entry.checksum) || !read_u64(stream_, entry.offset) ||
        !read_u64(stream_, entry.size)) {
      error = "truncated resource pack index";
      close();
      return false;
    }
    if (path_length == 0U || path_length > kMaximumPathLength) {
      error = "invalid path length in resource pack";
      close();
      return false;
    }
    entry.path.resize(path_length);
    if (!read_exact(stream_, entry.path.data(), entry.path.size())) {
      error = "truncated resource pack path";
      close();
      return false;
    }
    entry.path = normalize_path(entry.path);
    if (entry.offset < data_offset || entry.offset > archive_size_ ||
        entry.size > archive_size_ - entry.offset || entries_.count(entry.path) != 0U) {
      error = "invalid or duplicate resource pack entry: " + entry.path;
      close();
      return false;
    }
    entries_.emplace(entry.path, entry);
  }
  return true;
}

void ResourcePack::close() noexcept {
  if (stream_.is_open()) {
    stream_.close();
  }
  archive_size_ = 0U;
  entries_.clear();
}

const ResourceEntry* ResourcePack::find(const std::string& path) const noexcept {
  const auto iterator = entries_.find(normalize_path(path));
  return iterator == entries_.end() ? nullptr : &iterator->second;
}

std::optional<std::vector<std::uint8_t>> ResourcePack::read(
    const std::string& path, bool verify_checksum, std::string& error) {
  const ResourceEntry* entry = find(path);
  if (entry == nullptr) {
    error = "resource not found: " + path;
    return std::nullopt;
  }
  if (entry->size > static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max()) ||
      entry->size > static_cast<std::uint64_t>(std::numeric_limits<std::streamsize>::max())) {
    error = "resource is too large for this platform";
    return std::nullopt;
  }
  std::vector<std::uint8_t> data(static_cast<std::size_t>(entry->size));
  stream_.clear();
  stream_.seekg(static_cast<std::streamoff>(entry->offset), std::ios::beg);
  if (!read_exact(stream_, reinterpret_cast<char*>(data.data()), data.size())) {
    error = "failed to read resource data";
    return std::nullopt;
  }
  if (verify_checksum && crc32(data) != entry->checksum) {
    error = "resource checksum mismatch: " + entry->path;
    return std::nullopt;
  }
  return data;
}

std::vector<std::string> ResourcePack::paths() const {
  std::vector<std::string> result;
  result.reserve(entries_.size());
  for (const auto& item : entries_) {
    result.push_back(item.first);
  }
  std::sort(result.begin(), result.end());
  return result;
}

bool write_resource_pack(const std::filesystem::path& path,
                         std::vector<PackInputFile> files,
                         std::string& error) {
  for (auto& file : files) {
    file.path = normalize_path(file.path);
    if (file.path.empty() || file.path.size() > kMaximumPathLength ||
        file.path.front() == '/' || file.path.find("../") != std::string::npos) {
      error = "invalid resource path: " + file.path;
      return false;
    }
  }
  std::sort(files.begin(), files.end(),
            [](const PackInputFile& left, const PackInputFile& right) {
              return left.path < right.path;
            });
  for (std::size_t i = 1; i < files.size(); ++i) {
    if (files[i - 1].path == files[i].path) {
      error = "duplicate resource path: " + files[i].path;
      return false;
    }
  }
  if (files.size() > kMaximumFiles) {
    error = "too many files for resource pack";
    return false;
  }

  const std::uint64_t index_offset = kHeaderSize;
  const std::uint64_t data_offset = index_offset + index_size(files);
  std::vector<std::uint64_t> offsets;
  offsets.reserve(files.size());
  std::uint64_t cursor = data_offset;
  for (const auto& file : files) {
    offsets.push_back(cursor);
    cursor += static_cast<std::uint64_t>(file.data.size());
  }

  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  if (!stream) {
    error = "cannot create resource pack";
    return false;
  }
  stream.write(kMagic.data(), static_cast<std::streamsize>(kMagic.size()));
  write_u32(stream, kVersion);
  write_u32(stream, static_cast<std::uint32_t>(files.size()));
  write_u64(stream, index_offset);
  write_u64(stream, data_offset);
  write_u64(stream, 0U);

  for (std::size_t i = 0; i < files.size(); ++i) {
    const auto& file = files[i];
    write_u16(stream, static_cast<std::uint16_t>(file.path.size()));
    write_u16(stream, file.flags);
    write_u32(stream, crc32(file.data));
    write_u64(stream, offsets[i]);
    write_u64(stream, static_cast<std::uint64_t>(file.data.size()));
    stream.write(file.path.data(), static_cast<std::streamsize>(file.path.size()));
  }
  for (const auto& file : files) {
    if (!file.data.empty()) {
      stream.write(reinterpret_cast<const char*>(file.data.data()),
                   static_cast<std::streamsize>(file.data.size()));
    }
  }
  stream.flush();
  if (!stream) {
    error = "failed while writing resource pack";
    return false;
  }
  return true;
}

}  // namespace cth3ds
