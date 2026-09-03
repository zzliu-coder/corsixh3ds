#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace cth3ds {

using Sha256Digest = std::array<std::uint8_t, 32>;

class Sha256 {
 public:
  Sha256() noexcept;

  void update(const void* data, std::size_t size) noexcept;
  [[nodiscard]] Sha256Digest finish() noexcept;

 private:
  void transform(const std::uint8_t* block) noexcept;

  std::array<std::uint32_t, 8> state_{};
  std::array<std::uint8_t, 64> buffer_{};
  std::uint64_t total_bytes_{0U};
  std::size_t buffered_{0U};
  bool finished_{false};
};

[[nodiscard]] Sha256Digest sha256(const void* data, std::size_t size) noexcept;
[[nodiscard]] std::string sha256_hex(const Sha256Digest& digest);
[[nodiscard]] bool parse_sha256_hex(const std::string& value,
                                    Sha256Digest& digest) noexcept;

}  // namespace cth3ds
