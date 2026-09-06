#pragma once
#include <cstdint>
#include <cstddef>
namespace cth3ds {
enum class MemoryGate {Operation};
void runtime_observe_memory(const char*,const char*,const char*,MemoryGate,uint64_t,bool,uint64_t,bool,bool,bool) noexcept;
bool runtime_audio_reserve(size_t,const char*) noexcept;
void report_allocation_failure(const char*,const char*,uint64_t,const char*,const char*) noexcept;
void report_fatal(const char*) noexcept;
}
