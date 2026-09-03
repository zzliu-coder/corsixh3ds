#pragma once

#include <cstddef>
#include <cstdint>

using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using Result = std::int32_t;

#define R_SUCCEEDED(value) ((value) >= 0)

constexpr u32 KEY_A = 1U << 0U;
constexpr u32 KEY_B = 1U << 1U;
constexpr u32 KEY_SELECT = 1U << 2U;
constexpr u32 KEY_START = 1U << 3U;
constexpr u32 KEY_DRIGHT = 1U << 4U;
constexpr u32 KEY_DLEFT = 1U << 5U;
constexpr u32 KEY_DUP = 1U << 6U;
constexpr u32 KEY_DDOWN = 1U << 7U;
constexpr u32 KEY_R = 1U << 8U;
constexpr u32 KEY_L = 1U << 9U;
constexpr u32 KEY_X = 1U << 10U;
constexpr u32 KEY_Y = 1U << 11U;
constexpr u32 KEY_TOUCH = 1U << 20U;

struct circlePosition { std::int16_t dx; std::int16_t dy; };
struct touchPosition { u16 px; u16 py; };

inline u32 hidKeysDown() { return 0U; }
inline u32 hidKeysHeld() { return 0U; }
inline u32 hidKeysUp() { return 0U; }
inline void hidScanInput() {}
inline void hidCircleRead(circlePosition* position) { position->dx = 0; position->dy = 0; }
inline void hidTouchRead(touchPosition* position) { position->px = 0; position->py = 0; }
inline Result HIDUSER_GetSoundVolume(u8* out) { *out = 42U; return 0; }

enum APT_HookType {
  APTHOOK_ONSUSPEND = 0,
  APTHOOK_ONRESTORE,
  APTHOOK_ONSLEEP,
  APTHOOK_ONWAKEUP,
  APTHOOK_ONEXIT,
  APTHOOK_COUNT,
};
using aptHookFn = void (*)(APT_HookType, void*);
struct aptHookCookie { aptHookCookie* next; aptHookFn callback; void* param; };
inline void aptHook(aptHookCookie*, aptHookFn, void*) {}
inline void aptUnhook(aptHookCookie*) {}
inline void aptSetSleepAllowed(bool) {}

inline Result ptmuInit() { return 0; }
inline void ptmuExit() {}
inline Result PTMU_GetBatteryLevel(u8* out) { *out = 5U; return 0; }
inline Result PTMU_GetBatteryChargeState(u8* out) { *out = 0U; return 0; }

struct osSharedConfig_s { volatile u8 wifi_strength{3U}; };
inline osSharedConfig_s stub_shared_config{};
#define OS_SharedConfig (&stub_shared_config)

enum MemRegion {
  MEMREGION_APPLICATION = 0,
  MEMREGION_SYSTEM = 1,
  MEMREGION_BASE = 2,
};
inline u32 osGetMemRegionFree(MemRegion) { return 53U * 1024U * 1024U; }
inline u8 osGetWifiStrength() { return OS_SharedConfig->wifi_strength; }
inline u64 osGetTime() { return 1000U; }
inline u32 envGetHeapSize() { return 48U * 1024U * 1024U; }
inline u32 envGetLinearHeapSize() { return 8U * 1024U * 1024U; }
inline u32 linearSpaceFree() { return 8U * 1024U * 1024U; }
void* linearMemAlign(std::size_t bytes, std::size_t alignment);
void linearFree(void* pointer);
std::size_t linearGetSize(void* pointer);
inline bool aptMainLoop() { return false; }
inline void gspWaitForVBlank() {}
