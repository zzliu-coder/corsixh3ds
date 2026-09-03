#pragma once
#pragma GCC system_header

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
