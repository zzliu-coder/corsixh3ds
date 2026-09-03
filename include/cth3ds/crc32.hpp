#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace cth3ds {

[[nodiscard]] std::uint32_t crc32(const void* data, std::size_t size,
                                  std::uint32_t seed = 0U) noexcept;
[[nodiscard]] inline std::uint32_t crc32(const std::vector<std::uint8_t>& data,
                                         std::uint32_t seed = 0U) noexcept {
  return crc32(data.data(), data.size(), seed);
}

}  // namespace cth3ds
