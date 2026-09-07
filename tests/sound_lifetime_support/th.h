#pragma once
#include <cstdint>
inline uint32_t bytes_to_uint32_le(const uint8_t* p) {
  return uint32_t(p[0])|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;
}
