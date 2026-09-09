#pragma once
#include <cstdarg>
#include <cstddef>
#include <cstring>

namespace cth3ds::log_detail {
#if defined(__3DS__) && !defined(CTH3DS_STUB_BUILD)
static_assert(sizeof(unsigned)==4 && sizeof(unsigned long)==4 &&
              sizeof(unsigned long long)==8 && sizeof(std::size_t)==4,
              "Log varargs must use the ARM ILP32 conversion types");
#endif
// Only the common diagnostic grammar. Preflight never consumes arguments;
// flags, widths, other lengths and floating point retain libc's formatter.
inline bool supported(const char* format) noexcept {
  if (!format) return false;
  for (const char* p=format; *p; ++p) {
    if (*p!='%') continue;
    ++p;
    if (*p=='%' || *p=='d' || *p=='u' || *p=='s') continue;
    if (*p=='.' && p[1]=='*' && p[2]=='s') { p+=2; continue; }
    if (*p=='l') {
      ++p; if (*p=='l') ++p;
      if (*p=='u') continue;
    }
    return false;
  }
  return true;
}

// Return a bounded length: limit+1 means truncation, exactly as the sink needs.
// The caller owns the va_list and supplies a copy, so dynamic fallback leaves
// the original arguments untouched. No NUL terminator is consumed by the sink.
inline bool format(char* out, std::size_t limit, std::size_t& size,
                   const char* pattern, std::va_list args) noexcept {
  if (!supported(pattern)) return false;
  size=0;
  const auto put=[&](char c) { if(size<limit) out[size]=c; if(size<=limit) ++size; };
  for (const char* p=pattern; *p; ++p) {
    if (*p!='%') { put(*p); }
    else {
      ++p;
      if (*p=='%') put('%');
      else if (*p=='s' || *p=='.') {
        int precision=-1;
        if (*p=='.') { precision=va_arg(args,int); p+=2; if(precision<0) return false; }
        const char* value=va_arg(args,const char*);
        if(!value) return false; // libc-specific null-string spelling is retained.
        while ((precision!=0) && *value) {
          put(*value++); if(size>limit) return true;
          if(precision>0) --precision;
        }
      } else {
        unsigned long long value;
        if (*p=='d') {
          const int signed_value=va_arg(args,int);
          const unsigned magnitude=static_cast<unsigned>(signed_value);
          if(signed_value<0) { put('-'); value=0U-magnitude; }
          else value=magnitude;
        } else if (*p=='l') {
          ++p;
          if (*p=='l') { ++p; value=va_arg(args,unsigned long long); }
          else value=va_arg(args,unsigned long);
        } else value=va_arg(args,unsigned);
        char reverse[20]; std::size_t digits=0;
        do { reverse[digits++]=static_cast<char>('0'+value%10U); value/=10U; } while(value);
        while(digits) { put(reverse[--digits]); if(size>limit) return true; }
      }
    }
    if(size>limit) return true;
  }
  return true;
}
} // namespace cth3ds::log_detail
