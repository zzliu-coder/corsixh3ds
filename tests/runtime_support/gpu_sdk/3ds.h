#pragma once
#include <cstdint>
using u8=std::uint8_t;using u16=std::uint16_t;using u32=std::uint32_t;using u64=std::uint64_t;
constexpr u64 SYSCLOCK_ARM11=1000000;
constexpr int GFX_TOP=0,GFX_BOTTOM=1,GFX_LEFT=0;
constexpr int GSP_RGBA8_OES=0,GSP_BGR8_OES=1,GX_TRANSFER_FMT_RGBA8=0,GX_TRANSFER_FMT_RGB8=1;
int gfxGetScreenFormat(int);
#define GX_TRANSFER_FLIP_VERT(x) 0
#define GX_TRANSFER_OUT_TILED(x) 0
#define GX_TRANSFER_RAW_COPY(x) 0
#define GX_TRANSFER_IN_FORMAT(x) 0
#define GX_TRANSFER_OUT_FORMAT(x) ((x)<<12U)
#define GX_TRANSFER_SCALING(x) 0
u64 svcGetSystemTick();u32 linearSpaceFree();u32 vramSpaceFree();
void GPUCMD_GetBuffer(u32**,u32*,u32*);
