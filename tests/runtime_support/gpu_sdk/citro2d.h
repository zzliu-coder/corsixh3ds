#pragma once
#include "3ds.h"
constexpr int C3D_DEFAULT_CMDBUF_SIZE=0x40000;
constexpr int GPU_NEAREST=0,GPU_CLAMP_TO_EDGE=0,GPU_RGBA8=0,GPU_TEXFACE_2D=0,GPU_RB_RGBA8=0;
constexpr int GPU_SCISSOR_NORMAL=1,GPU_SCISSOR_DISABLE=0,GPU_ALWAYS=0,GPU_WRITE_COLOR=15;
constexpr int C2D_TintMult=1,GPU_BLEND_ADD=0,GPU_SRC_ALPHA=1,GPU_ONE_MINUS_SRC_ALPHA=2,GPU_ONE=3;
struct C3D_Tex{void* data{};int width{},height{};};
struct C3D_RenderTarget{C3D_Tex* tex{};bool owner{};int width{},height{};};
struct Tex3DS_SubTexture{u16 width,height;float left,top,right,bottom;};
struct C2D_Image{C3D_Tex* tex;const Tex3DS_SubTexture* subtex;};
struct C2D_DrawParams{struct {float x{},y{},w{},h{};}pos;struct {float x{},y{};}center;float depth{},angle{};};
struct C2D_ImageTint{u32 colour;};
constexpr u32 C2D_Color32(u8 r,u8 g,u8 b,u8 a){return r|(u32(g)<<8U)|(u32(b)<<16U)|(u32(a)<<24U);}
inline void C2D_PlainImageTint(C2D_ImageTint* t,u32 c,float){t->colour=c;}
bool C3D_Init(int);void C3D_Fini();bool C2D_Init(unsigned);void C2D_Fini();
bool C3D_TexInitVRAM(C3D_Tex*,int,int,int);bool C3D_TexInit(C3D_Tex*,int,int,int);
void C3D_TexDelete(C3D_Tex*);void C3D_TexSetFilter(C3D_Tex*,int,int);void C3D_TexSetWrap(C3D_Tex*,int,int);
C3D_RenderTarget* C3D_RenderTargetCreateFromTex(C3D_Tex*,int,int,int);
C3D_RenderTarget* C3D_RenderTargetCreate(int,int,int,int);
void C3D_RenderTargetDelete(C3D_RenderTarget*);void C3D_RenderTargetSetOutput(C3D_RenderTarget*,int,int,u32);
bool C3D_FrameBegin(u8);void C3D_FrameEnd(u8);float C3D_GetDrawingTime();
void C2D_Flush();void C2D_Prepare();void C2D_SetTintMode(int);void C2D_ViewReset();
void C3D_DepthTest(bool,int,int);void C3D_AlphaBlend(int,int,int,int,int,int);
void C2D_SceneBegin(C3D_RenderTarget*);void C3D_SetScissor(int,int,int,int,int);
void C2D_TargetClear(C3D_RenderTarget*,u32);
bool C2D_DrawImage(C2D_Image,const C2D_DrawParams*,const C2D_ImageTint*);
bool C2D_DrawRectSolid(float,float,float,float,float,u32);
bool C2D_DrawLine(float,float,u32,float,float,u32,float,float);
