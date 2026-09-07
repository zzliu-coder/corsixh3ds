// A deliberately delayed command queue exercises the production GPU backend.
// This models storage/ordering and pixels, not PICA hardware performance.
#include <SDL.h>
#include <citro2d.h>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <functional>
#include <array>
#include <string>
#include <vector>
#include "cth3ds/gpu_api.hpp"
#include "cth3ds/gpu_layout.hpp"
namespace {
std::vector<std::function<void()>> commands,pending;
C3D_RenderTarget* current{};C3D_RenderTarget* outputs[2]{};
SDL_Rect clip{};bool clipped{},in_frame{},ready{};
unsigned offset{},cost=64,objects{},max_objects{},waits{},allocations{},live{},fail_at{};
bool allocation(){return ++allocations!=fail_at;}
bool corrupt_sampling{},corrupt_clear{},corrupt_raster{},corrupt_lcd{},reject_invalidate{},wrong_dimensions{};
std::array<std::array<u8,400*240*4>,2> lcd{};
std::vector<std::string> diagnostic_lines;
std::vector<C3D_RenderTarget*> drawn_targets;
// Model transfer bytes independently of the production LCD decoder. Physical
// byte offset walks columns bottom-to-top, and top/bottom use different formats.
void transfer_lcd(int screen,C3D_RenderTarget* t);

void finish(){for(auto& call:pending)call();pending.clear();++waits;}
u32& raw(C3D_Tex* tex,int x,int y){return static_cast<u32*>(tex->data)[cth3ds::gpu_tile_offset(x,tex->height-1-y,tex->width)];}
u32 pixel(C3D_Tex* tex,int x,int y){return cth3ds::gpu_pixel(raw(tex,x,y));}
// PICA sampling and framebuffer rasterization use opposite Y origins.
// Independent tex3ds RGBA8 output stores source row zero in memory row zero.
// Never call the framebuffer accessor from this texture sampler.
u32 texture_pixel(C3D_Tex* tex,int x,int y){
  if(corrupt_sampling)y=tex->height-1-y;
  static constexpr unsigned mx[]={0,1,4,5,16,17,20,21};
  static constexpr unsigned my[]={0,2,8,10,32,34,40,42};
  const auto index=((y/8)*(tex->width/8)+x/8)*64+mx[x%8]+my[y%8];
  const auto* p=static_cast<const unsigned char*>(tex->data)+index*4;
  return (u32(p[0])<<24U)|(u32(p[1])<<16U)|(u32(p[2])<<8U)|p[3];
}
u32 blend(u32 src,u32 dst){
  u32 result=0,a=src>>24U;
  for(unsigned s=0;s<24;s+=8)result|=(((((src>>s)&255U)*a+((dst>>s)&255U)*(255U-a))/255U)<<s);
  return result|((a+(dst>>24U)*(255U-a)/255U)<<24U);
}
void paint(C3D_RenderTarget* target,int x,int y,u32 colour){raw(target->tex,x,y)=cth3ds::gpu_pixel(blend(colour,pixel(target->tex,x,y)));}
template<class Pixel> void raster(C3D_RenderTarget* target,float x,float y,float w,float h,SDL_Rect cut,Pixel get){
  const int left=std::max(0,cut.x),right=std::min(target->width,cut.x+cut.w);
  const int top=std::max(0,cut.y),bottom=std::min(target->height,cut.y+cut.h);
  for(int iy=std::max(top,int(std::ceil(y-0.5f)));iy<std::min(bottom,int(std::ceil(y+h-0.5f)));++iy)
    for(int ix=std::max(left,int(std::ceil(x-0.5f)));ix<std::min(right,int(std::ceil(x+w-0.5f)));++ix)
      paint(target,ix,iy,get((ix+0.5f-x)/w,(iy+0.5f-y)/h));
}
SDL_Rect bounds(){return clipped?clip:SDL_Rect{0,0,current->width,current->height};}
void emitted(){assert(in_frame);assert(++objects<=max_objects);offset+=cost;assert(offset<65536);}
}
u64 svcGetSystemTick(){static u64 clock;return ++clock;}u32 linearSpaceFree(){return 8000000;}u32 vramSpaceFree(){return 6000000;}
u8* gfxGetFramebuffer(gfxScreen_t screen,int eye,u16* width,u16* height){
  assert(eye==GFX_LEFT);if(width)*width=wrong_dimensions?239:240;
  if(height)*height=screen==GFX_TOP?400:320;return lcd[screen].data();
}
Result GSPGPU_InvalidateDataCache(const void*,u32){assert(pending.empty());return reject_invalidate?-1:0;}
namespace {
void transfer_lcd(int screen,C3D_RenderTarget* t){
  u8* dest=lcd[screen].data();
  for(int x=0;x<t->width;++x)for(int y=t->height-1;y>=0;--y){
    const auto p=pixel(t->tex,x,y);const u8 r=p,g=p>>8,b=p>>16,a=p>>24;
    if(screen==GFX_TOP){*dest++=b;*dest++=g;*dest++=r;}
    else {*dest++=a;*dest++=b;*dest++=g;*dest++=r;}
  }
  if(corrupt_lcd)lcd[screen].fill(0);
}
}
int gfxGetScreenFormat(int screen){return screen==GFX_TOP?GSP_BGR8_OES:GSP_RGBA8_OES;}
void GPUCMD_GetBuffer(u32**,u32* size,u32* pos){*size=65536;*pos=offset;}
bool C3D_Init(int){ready=allocation();return ready;}void C3D_Fini(){assert(pending.empty());ready=false;}
bool C2D_Init(unsigned n){max_objects=n;return allocation();}void C2D_Fini(){}
bool C3D_TexInit(C3D_Tex* tex,int w,int h,int){if(!allocation())return false;tex->data=std::calloc(w*h,4);tex->width=w;tex->height=h;++live;return true;}
bool C3D_TexInitVRAM(C3D_Tex* t,int w,int h,int f){return C3D_TexInit(t,w,h,f);}
void C3D_TexDelete(C3D_Tex* tex){assert(pending.empty());std::free(tex->data);tex->data=nullptr;--live;}
void C3D_TexSetFilter(C3D_Tex*,int,int){}void C3D_TexSetWrap(C3D_Tex*,int,int){}
C3D_RenderTarget* C3D_RenderTargetCreateFromTex(C3D_Tex* tex,int,int,int depth){assert(depth==-1);if(!allocation())return nullptr;++live;return new C3D_RenderTarget{tex,false,tex->width,tex->height};}
C3D_RenderTarget* C3D_RenderTargetCreate(int w,int h,int,int depth){
  assert(depth==-1);if(!allocation())return nullptr;auto* tex=new C3D_Tex;
  // Rotated LCD output is exposed in logical coordinates by this test model.
  int tw=8,th=8;while(tw<h)tw*=2;while(th<w)th*=2;
  if(!C3D_TexInit(tex,tw,th,0)){delete tex;return nullptr;}
  ++live;return new C3D_RenderTarget{tex,true,h,w};
}
void C3D_RenderTargetDelete(C3D_RenderTarget* t){if(t->owner){C3D_TexDelete(t->tex);delete t->tex;}delete t;--live;}
void C3D_RenderTargetSetOutput(C3D_RenderTarget* t,int screen,int eye,u32 flags){assert(eye==GFX_LEFT);assert(flags==u32(gfxGetScreenFormat(screen)<<12));if(!in_frame)finish();outputs[screen]=t;}
bool C3D_FrameBegin(u8){assert(ready&&!in_frame);finish();in_frame=true;offset=objects=0;return true;}
void C3D_FrameEnd(u8 flags){
  assert(flags==0); // production retains safe whole-linear-cache flush
  assert(in_frame&&pending.empty());
  for(int s=0;s<2;++s){auto* t=outputs[s];
    if(t && std::find(drawn_targets.begin(),drawn_targets.end(),t)!=drawn_targets.end())
      commands.emplace_back([=]{transfer_lcd(s,t);});
  }
  drawn_targets.clear();pending=std::move(commands);commands.clear();in_frame=false;
}
float C3D_GetDrawingTime(){return 1;}
void C2D_Flush(){}void C2D_Prepare(){}void C2D_SetTintMode(int){}void C2D_ViewReset(){}
void C3D_DepthTest(bool enabled,int,int mask){assert(!enabled&&mask==GPU_WRITE_COLOR);}
void C3D_AlphaBlend(int,int,int src,int dst,int alpha,int adst){assert(src==GPU_SRC_ALPHA&&dst==GPU_ONE_MINUS_SRC_ALPHA&&alpha==GPU_ONE&&adst==GPU_ONE_MINUS_SRC_ALPHA);}
void C2D_SceneBegin(C3D_RenderTarget* t){current=t;drawn_targets.push_back(t);}
void C3D_SetScissor(int mode,int l,int b,int r,int t){clipped=mode;clip={l,current->height-t,r-l,t-b};}
void C2D_TargetClear(C3D_RenderTarget* t,u32 c){commands.emplace_back([=]{for(int y=0;y<t->height;++y)for(int x=0;x<t->width;++x)raw(t->tex,x,y)=cth3ds::gpu_pixel(corrupt_clear?0U:c);});}
bool C2D_DrawImage(C2D_Image image,const C2D_DrawParams* p,const C2D_ImageTint* colour){
  emitted();const auto sub=*image.subtex;const auto params=*p;const auto tint=colour?colour->colour:0xffffffffU;
  const auto cut=bounds();auto* target=current;auto* tex=image.tex;
  commands.emplace_back([=]{raster(target,params.pos.x,params.pos.y,std::fabs(params.pos.w),std::fabs(params.pos.h),cut,[=](float u,float v){
    if(params.pos.w<0)u=1-u;if(params.pos.h<0)v=1-v;
    int x=std::clamp(int((sub.left+u*(sub.right-sub.left))*tex->width),0,tex->width-1);
    int y=std::clamp(int((1-sub.top+v*(sub.top-sub.bottom))*tex->height),0,tex->height-1);
    u32 value=texture_pixel(tex,x,y),result=0;for(unsigned s=0;s<32;s+=8)result|=(((((value>>s)&255U)*((tint>>s)&255U))/255U)<<s);return result;
  });});return true;
}
bool C2D_DrawRectSolid(float x,float y,float,float w,float h,u32 c){emitted();auto* t=current;auto cut=bounds();commands.emplace_back([=]{raster(t,x,y,w,h,cut,[=](float,float){return corrupt_raster?0xff000000U:c;});});return true;}
bool C2D_DrawLine(float,float,u32,float,float,u32,float,float){assert(false&&"line model intentionally excluded");return false;}
namespace cth3ds{void runtime_diagnostic_line(const char* line) noexcept {diagnostic_lines.emplace_back(line);std::puts(line);}}

int main(){
  using namespace cth3ds;assert(SDL_Init(0)==0);
  auto* out=SDL_CreateRGBSurfaceWithFormat(0,640,480,32,SDL_PIXELFORMAT_ABGR8888);
  auto* renderer=SDL_CreateSoftwareRenderer(out);assert(renderer);
  // Every partial initialization must release its own objects.
  allocations=0;fail_at=0;assert(gpu_initialize());const unsigned allocation_steps=allocations;gpu_shutdown();
  for(unsigned failure=1;failure<=allocation_steps;++failure){allocations=0;fail_at=failure;assert(!gpu_initialize());assert(live==0);}
  fail_at=0;
  for(bool* fault:{&corrupt_clear,&corrupt_raster,&corrupt_lcd,&reject_invalidate,&wrong_dimensions}){
    *fault=true;diagnostic_lines.clear();assert(!gpu_initialize());assert(!gpu_active()&&live==0);
    bool saw_failure=false;for(const auto& line:diagnostic_lines)
      saw_failure|=line.find("gpu-stage:")!=std::string::npos && line.find("status=FAIL")!=std::string::npos;
    assert(saw_failure);*fault=false;
  }
  corrupt_sampling=true;assert(!gpu_initialize());assert(!gpu_active()&&live==0);
  corrupt_sampling=false;assert(gpu_initialize());
  std::vector<u32> colours(640*480);for(int y=0;y<480;++y)for(int x=0;x<640;++x)colours[y*640+x]=0xff000000U|u32(x%256)|u32(y%256)<<8U|u32((x+y)%256)<<16U;
  auto* background=gpu_image_create(renderer,640,480,colours.data());assert(background);
  auto draw=[&](SDL_Texture* tex,SDL_Rect src,SDL_FRect dest,int flip){assert(gpu_image_draw(tex,&src,&dest,static_cast<SDL_RendererFlip>(flip))==0);};
  SDL_FRect full{0,0,640,480};
  for(int flip=0;flip<4;++flip){
    assert(gpu_begin());assert(gpu_clear(0xff000000U));draw(background,{0,0,640,480},full,flip);
    assert(gpu_read_pixels(out));auto* p=static_cast<u32*>(out->pixels);
    for(int y=0;y<480;++y)for(int x=0;x<640;++x)assert(p[y*640+x]==colours[(flip&2?479-y:y)*640+(flip&1?639-x:x)]);
  }
  // Alpha, colour modulation, clipping, image deletion before GPU completion.
  std::vector<u32> translucent(17*13,0x80402010U);auto* sprite=gpu_image_create(renderer,17,13,translucent.data());
  SDL_SetTextureColorMod(sprite,128,255,255);SDL_SetTextureAlphaMod(sprite,128);
  assert(gpu_begin());assert(gpu_clear(0xff102030U));SDL_Rect cut{12,11,9,7};gpu_clip(&cut);
  draw(sprite,{0,0,17,13},{10,10,17,13},0);gpu_image_destroy(sprite);
  assert(gpu_read_pixels(out));for(int y=0;y<480;++y)for(int x=0;x<640;++x){u32 expected=(x>=12&&x<21&&y>=11&&y<18)?blend(0x40402008U,0xff102030U):0xff102030U;assert(static_cast<u32*>(out->pixels)[y*640+x]==expected);}
  // Four full pages force a checkpoint; already queued pixels must stay valid.
  std::vector<SDL_Texture*> large;
  for(int i=0;i<7;++i){std::vector<u32> data(512*512,0xff000000U|u32(30+i));large.push_back(gpu_image_create(renderer,512,512,data.data()));}
  const auto previous_waits=waits;assert(gpu_begin());assert(gpu_clear(0xff000000U));
  for(int i=0;i<7;++i)draw(large[i],{0,0,512,512},{float(i*50),20,40,40},0);
  assert(gpu_read_pixels(out));assert(waits>previous_waits+2);
  for(int i=0;i<7;++i)assert(static_cast<u32*>(out->pixels)[30*640+i*50+10]==(0xff000000U|u32(30+i)));
  for(auto* tex:large)gpu_image_destroy(tex);
  assert(gpu_begin());assert(gpu_clear(0xff000000U));
  assert(gpu_line(10,10,30,10,0xffaabbccU));assert(gpu_line(40,30,40,10,0xffaabbccU));
  assert(gpu_line(50,50,50,50,0xffaabbccU));assert(gpu_read_pixels(out));
  for(int x=10;x<=30;++x)assert(static_cast<u32*>(out->pixels)[10*640+x]==0xffaabbccU);
  for(int y=10;y<=30;++y)assert(static_cast<u32*>(out->pixels)[y*640+40]==0xffaabbccU);
  assert(static_cast<u32*>(out->pixels)[50*640+50]==0xffaabbccU);
  // Actual command cursor and vertex capacity each cause bounded safe splits.
  for(unsigned command_cost:{8U,300U}){cost=command_cost;assert(gpu_begin());assert(gpu_clear(0xff000000U));SDL_Rect rect{0,0,1,1};for(int i=0;i<4300;++i)assert(gpu_fill(&rect,0xff112233U));assert(gpu_top({120,120,400,240}));assert(gpu_bottom({120,120,400,240},nullptr,0));gpu_quiesce();}
  cost=64;
  // Both outputs consume the same already composed canvas; top is 1:1 and
  // bottom uses nearest half scale. Keep white-frame border out of comparisons.
  assert(gpu_begin());assert(gpu_clear(0xff000000U));draw(background,{0,0,640,480},full,0);
  assert(gpu_top({100,80,400,240}));assert(gpu_bottom({100,80,400,240},nullptr,0));
  auto* top=outputs[GFX_TOP];auto* bottom=outputs[GFX_BOTTOM];gpu_quiesce();
  for(int y=0;y<240;++y)for(int x=0;x<400;++x)assert(pixel(top->tex,x,y)==colours[(y+80)*640+x+100]);
  // At exact half-scale texel boundaries, decreasing V selects the lower
  // source-row neighbour; both neighbours are equidistant under nearest.
  for(int y=5;y<30;++y)for(int x=5;x<30;++x)assert(pixel(bottom->tex,x,y)==colours[(2*y)*640+2*x+1]);
  // Wide crop uses the same framebuffer-to-texture conversion. An asymmetric
  // CPU overlay independently exercises the short non-square texture upload.
  std::vector<u32> overlay(320*12);
  for(int y=0;y<12;++y)for(int x=0;x<320;++x)overlay[y*320+x]=0xff000000U|u32(x%256)|u32(y*17)<<8U;
  assert(gpu_begin());assert(gpu_clear(0xff000000U));draw(background,{0,0,640,480},full,0);
  assert(gpu_top({160,150,480,288}));assert(gpu_bottom({160,150,480,288},overlay.data(),12));
  top=outputs[GFX_TOP];bottom=outputs[GFX_BOTTOM];gpu_quiesce();
  for(int y=0;y<240;++y)for(int x=0;x<400;++x){
    const double sx=(x+0.5)*1.2,sy=(y+0.5)*1.2;
    const int ix=int(std::floor(sx)),iy=int(std::floor(sy));
    const bool tie_x=std::abs(sx-std::round(sx))<0.00001;
    const bool tie_y=std::abs(sy-std::round(sy))<0.00001;
    bool match=false;
    for(int dx=0;dx<=(tie_x?1:0);++dx)for(int dy=0;dy<=(tie_y?1:0);++dy)
      match|=pixel(top->tex,x,y)==colours[(150+iy-dy)*640+160+ix-dx];
    assert(match);
  }
  for(int y=0;y<12;++y)for(int x=0;x<320;++x)assert(pixel(bottom->tex,x,y)==overlay[y*320+x]);
  gpu_image_destroy(background);gpu_images_release(renderer);gpu_log_statistics();gpu_shutdown();assert(live==0);
  SDL_DestroyRenderer(renderer);SDL_FreeSurface(out);SDL_Quit();
  std::printf("PASS production GPU: four flips, multi-piece images, clipping, alpha, delayed eviction, command and vertex bounds, dual outputs, %u init failures\n",allocation_steps);
}
