#pragma once
#pragma GCC system_header

#include <cstddef>

extern "C" void* memalign(std::size_t alignment, std::size_t bytes);
extern "C" std::size_t malloc_usable_size(void* pointer);

// Minimal newlib-compatible allocator telemetry used by the host syntax
// target. The real 3DS build receives this declaration from devkitARM/newlib.
struct mallinfo {
  int arena;
  int ordblks;
  int smblks;
  int hblks;
  int hblkhd;
  int usmblks;
  int fsmblks;
  int uordblks;
  int fordblks;
  int keepcost;
};

inline struct mallinfo mallinfo() {
  return {0, 0, 0, 0, 0, 0, 0, 2 * 1024 * 1024, 32 * 1024 * 1024, 0};
}
