#pragma once
#include <cstdio>
#include <cstddef>
#include <string>

// Only fopen is replaced in a private copy of the complete production header.
// setvbuf/fwrite/fflush/fclose remain the host's actual stdio implementation.
namespace logging_io {
inline std::string delivered;
inline std::size_t writes{},closes{},fail_after=static_cast<std::size_t>(-1);
inline bool short_write{},close_failure{};
inline void (*on_write)(){};
inline void reset() {
  delivered.clear();writes=closes=0;fail_after=static_cast<std::size_t>(-1);
  short_write=close_failure=false;
  on_write=nullptr;
}
}
std::FILE* logging_open(const char*,const char*);
