#pragma once
#include "SDL_rwops.h"
#define MIX_MAX_VOLUME 128
struct Mix_Chunk { int allocated; Uint8* abuf; Uint32 alen; Uint8 volume; };
// Deterministic mixer seam: real SDL2 WAV loading/conversion, modeled channels
// and callback ownership. This does NOT emulate NDSP or device scheduling.
int Mix_AllocateChannels(int);
void Mix_ChannelFinished(void(*)(int));
int Mix_HaltChannel(int);
int Mix_PlayChannel(int,Mix_Chunk*,int);
int Mix_Playing(int);
int Mix_Paused(int);
void Mix_Pause(int);
void Mix_Resume(int);
int Mix_Volume(int,int);
int Mix_VolumeChunk(Mix_Chunk*,int);
Mix_Chunk* Mix_LoadWAV_RW(SDL_RWops*,int);
void Mix_FreeChunk(Mix_Chunk*);
int Mix_QuerySpec(int*,Uint16*,int*);
