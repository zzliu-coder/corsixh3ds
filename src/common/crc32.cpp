#include "cth3ds/crc32.hpp"

#include <array>

namespace cth3ds {
namespace {

constexpr std::array<std::uint32_t, 256> make_table() {
  std::array<std::uint32_t, 256> table{};
  for (std::uint32_t i = 0; i < 256U; ++i) {
    std::uint32_t value = i;
    for (int bit = 0; bit < 8; ++bit) {
      value = (value & 1U) != 0U ? (value >> 1U) ^ 0xEDB88320U : value >> 1U;
    }
    table[static_cast<std::size_t>(i)] = value;
  }
  return table;
}

constexpr auto kTable = make_table();

}  // namespace

std::uint32_t crc32(const void* data, std::size_t size, std::uint32_t seed) noexcept {
  const auto* bytes = static_cast<const std::uint8_t*>(data);
  std::uint32_t value = seed ^ 0xFFFFFFFFU;
  for (std::size_t i = 0; i < size; ++i) {
    const std::uint8_t index = static_cast<std::uint8_t>((value ^ bytes[i]) & 0xFFU);
    value = (value >> 8U) ^ kTable[static_cast<std::size_t>(index)];
  }
  return value ^ 0xFFFFFFFFU;
}

}  // namespace cth3ds
