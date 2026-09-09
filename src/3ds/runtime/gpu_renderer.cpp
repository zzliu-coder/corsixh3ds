#include "cth3ds/gpu_api.hpp"
#ifdef CORSIXTH_3DS_GPU
#include <3ds.h>
#include <citro2d.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdarg>
#include <cstring>
#include <memory>
#include <new>
#include <vector>
#include "cth3ds/gpu_layout.hpp"
#include "cth3ds/gpu_pixels.hpp"
#include "cth3ds/cpu_work.hpp"
#include "cth3ds/gpu_diagnostics.hpp"
#include "cth3ds/gpu_submit_sample.hpp"
#include "cth3ds/gpu_atlas_affinity.hpp"
#include "runtime_3ds.hpp"

namespace cth3ds {
namespace {
constexpr unsigned page_count=3, max_objects=4096;
constexpr u32 transfer=GX_TRANSFER_FLIP_VERT(0)|GX_TRANSFER_OUT_TILED(0)|
  GX_TRANSFER_RAW_COPY(0)|GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGBA8)|
  GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_NO);
struct Page { C3D_Tex texture{}; GpuSkyline shelf{}; std::uint64_t generation{1},used{},touched{}; };
struct Piece {
  int sx{},sy{},w{},h{},x{},y{},page{-1};
  std::uint64_t generation{};
  std::unique_ptr<std::uint32_t[]> pixels;
  std::unique_ptr<std::uint8_t[]> indices;
};
struct Image {
  SDL_Texture* handle{}; SDL_Renderer* renderer{};
  int width{},height{}; std::uint64_t source_bytes{}; bool indexed{};
  std::unique_ptr<std::array<std::uint32_t,256>> palette;
  std::vector<Piece> pieces; Image* next{}; Image* previous{};
};
struct Stats {
  std::uint64_t frames{},draws{},uploads{},upload_bytes{},hits{},evictions{},splits{},wait_us{};
  std::uint64_t source_bytes{},source_peak{},source_images{},gpu_us{},gpu_jobs{};
  std::uint64_t clip_requests{},clip_skips{},full_sprite_draws{};
  std::uint64_t frame_upload_start{},frame_eviction_start{},frame_upload_peak{},frame_eviction_peak{};
  std::uint64_t indexed_bytes{},source_block_peak{},source_failures{},indexed_images{};
  float cmd_peak{};
} stats;
std::array<Page,page_count> pages;
C3D_Tex canvas{},overlay{};
C3D_RenderTarget *canvas_target{},*top_target{},*bottom_target{};
bool active{},c3_ready{},c2_ready{},in_frame{},pending{},empty_clip{},canvas_clip_active{};
unsigned objects{};std::uint64_t epoch{1},touch_sequence{};
SDL_Rect clip{0,0,640,480};
Image* images{};
GpuSubmitSample submit;
GpuAtlasAffinity affinity;

float command_usage() noexcept {
  // The public libctru cursor reports this job, unlike C3D's last-split metric.
  u32 size=0,offset=0;GPUCMD_GetBuffer(nullptr,&size,&offset);
  return size?static_cast<float>(offset)/size:0.0f;
}
bool command_pressure() noexcept {
  u32 size=0,offset=0;GPUCMD_GetBuffer(nullptr,&size,&offset);
  return size && offset>size*7U/10U;
}

void diagnostic_vline(bool flush,const char* format,va_list args) noexcept {
  char line[1024];
  std::vsnprintf(line,sizeof(line),format,args);runtime_diagnostic_line(line,flush);
}
void boot_log(const char* format,...) noexcept {
  va_list args;va_start(args,format);diagnostic_vline(true,format,args);va_end(args);
}
void buffered_log(const char* format,...) noexcept {
  va_list args;va_start(args,format);diagnostic_vline(false,format,args);va_end(args);
}

void outputs(bool enable) noexcept {
  // SDL owns LCD allocation. Respect each existing framebuffer's pixel size.
  static_assert(GSP_RGBA8_OES==GX_TRANSFER_FMT_RGBA8 && GSP_BGR8_OES==GX_TRANSFER_FMT_RGB8,
    "libctru framebuffer/transfer format mapping changed");
  C3D_RenderTargetSetOutput(enable?top_target:nullptr,GFX_TOP,GFX_LEFT,
    transfer|GX_TRANSFER_OUT_FORMAT(static_cast<u32>(gfxGetScreenFormat(GFX_TOP))));
  C3D_RenderTargetSetOutput(enable?bottom_target:nullptr,GFX_BOTTOM,GFX_LEFT,
    transfer|GX_TRANSFER_OUT_FORMAT(static_cast<u32>(gfxGetScreenFormat(GFX_BOTTOM))));
}
void record_completion() noexcept {
  if(pending){stats.gpu_us+=static_cast<std::uint64_t>(C3D_GetDrawingTime()*1000.0f);
    ++stats.gpu_jobs;pending=false;}
}
void apply_clip() noexcept {
  // The offscreen texture is upright; PICA scissor has a bottom-left origin.
  C2D_Flush();
  C3D_SetScissor(GPU_SCISSOR_NORMAL,clip.x,512-clip.y-clip.h,
    clip.x+clip.w,512-clip.y);
  canvas_clip_active=true;
}
void canvas_scene() noexcept {
  C2D_Prepare(); C3D_DepthTest(false,GPU_ALWAYS,GPU_WRITE_COLOR);
  C3D_AlphaBlend(GPU_BLEND_ADD,GPU_BLEND_ADD,GPU_SRC_ALPHA,
    GPU_ONE_MINUS_SRC_ALPHA,GPU_ONE,GPU_ONE_MINUS_SRC_ALPHA);
  C2D_SetTintMode(C2D_TintMult);
  C2D_SceneBegin(canvas_target); C2D_ViewReset(); apply_clip();
}
bool begin_job() noexcept {
  const auto before=svcGetSystemTick();
  if(!C3D_FrameBegin(0))return false;
  stats.wait_us+=(svcGetSystemTick()-before)*1000000ULL/SYSCLOCK_ARM11;
  record_completion();in_frame=true;objects=0;++epoch;
  outputs(true);canvas_scene();return true;
}
void end_job() noexcept {
  if(!in_frame)return;
  C2D_Flush();stats.cmd_peak=std::max(stats.cmd_peak,command_usage());
  // C2D owns vertex/index buffers; default FrameEnd flushes their CPU cache
  // together with updated atlas regions before the queue starts using them.
  C3D_FrameEnd(0);in_frame=false;pending=true;canvas_clip_active=false;
}
bool checkpoint() noexcept {
  // No screen has been drawn during canvas assembly. Preserve the canvas,
  // finish outstanding draws, then reuse bounded vertex/atlas storage safely.
  end_job();++stats.splits;return begin_job();
}
bool room_for_draw() noexcept {
  if(!in_frame && !begin_job())return false;
  if(objects>=max_objects-32){submit.inc(GpuSubmitSample::ObjectCheckpoint);if(!checkpoint())return false;}
  else if(command_pressure()){submit.inc(GpuSubmitSample::CommandCheckpoint);if(!checkpoint())return false;}
  ++objects;return true;
}
void texture_settings(C3D_Tex& tex) noexcept {
  C3D_TexSetFilter(&tex,GPU_NEAREST,GPU_NEAREST);
  C3D_TexSetWrap(&tex,GPU_CLAMP_TO_EDGE,GPU_CLAMP_TO_EDGE);
}
bool place(Image& image,Piece& piece) noexcept {
  if(piece.page>=0 && piece.generation==pages[piece.page].generation){
    submit.inc(GpuSubmitSample::Hits);
    pages[piece.page].used=epoch;pages[piece.page].touched=++touch_sequence;++stats.hits;return true;
  }
  int selected=-1,x=0,y=0;
  for(unsigned i:affinity.order(pages))
    if(pages[i].shelf.allocate(piece.w,piece.h,x,y)){selected=static_cast<int>(i);break;}
  if(selected<0){
    auto oldest=[&](){unsigned n=0;
      for(unsigned i=1;i<page_count;++i){if(pages[i].touched<pages[n].touched)n=i;}
      return n;};
    unsigned n=oldest();
    if(pages[n].used==epoch){submit.inc(GpuSubmitSample::EvictCheckpoint);if(!checkpoint())return false;n=oldest();}
    auto& page=pages[n];page.shelf={};++page.generation;++stats.evictions;
    if(affinity.page==static_cast<int>(n))affinity.page=-1;
    if(!page.shelf.allocate(piece.w,piece.h,x,y))return false;
    selected=static_cast<int>(n);
  }
  auto& page=pages[selected];
  affinity.placed(selected,page.generation);
  auto* output=static_cast<std::uint32_t*>(page.texture.data);
  // Each page is immutable while the GPU reads it. Appends touch disjoint
  // tiles; eviction is allowed only after a completed queue boundary.
  {
    CpuWorkScope upload(CpuWork::GpuUpload,static_cast<std::uint64_t>(piece.w)*piece.h*4U);
    if(image.indexed)gpu_upload_indices(output,512,x,y,piece.indices.get(),piece.w,piece.h,image.palette->data());
    else gpu_upload_prepared(output,512,x,y,piece.pixels.get(),piece.w,piece.h);
  }
  piece.page=selected;piece.generation=page.generation;piece.x=x;piece.y=y;
  submit.inc(GpuSubmitSample::Uploads);
  page.used=epoch;page.touched=++touch_sequence;++stats.uploads;stats.upload_bytes+=piece.w*piece.h*4U;
  return true;
}
bool draw_image(C3D_Tex& tex,const Tex3DS_SubTexture& sub,SDL_FRect dst,u32 tint,
                bool flip_x=false,bool flip_y=false) noexcept {
  C2D_ImageTint colours;C2D_PlainImageTint(&colours,tint,1.0f);
  C2D_DrawParams params{};
  // C2D uses abs(w/h) for geometry and the sign solely to flip UVs.
  params.pos={dst.x,dst.y,
    flip_x?-dst.w:dst.w,flip_y?-dst.h:dst.h};
  return C2D_DrawImage({&tex,&sub},&params,&colours);
}
bool screen_image(C3D_RenderTarget* target,RectI source,int width,int height) noexcept {
  if(!in_frame)return false;
  C2D_SceneBegin(target); C2D_ViewReset(); C3D_SetScissor(GPU_SCISSOR_DISABLE,0,0,0,0);
  canvas_clip_active=false;
  C3D_DepthTest(false,GPU_ALWAYS,GPU_WRITE_COLOR);
  // With C2D's offscreen projection, logical row y is memory row y (R54
  // device readback). Convert memory rows to bottom-origin texture V once.
  // Keep top >= bottom: Tex3DS uses top < bottom for atlas rotation.
  Tex3DS_SubTexture sub{static_cast<u16>(source.w),static_cast<u16>(source.h),
    source.x/1024.0f,1-source.y/512.0f,(source.x+source.w)/1024.0f,1-(source.y+source.h)/512.0f};
  // Reserve screen objects before switching target: room_for_draw must never
  // split after top is submitted and accidentally resume on the canvas.
  C2D_ImageTint tint;C2D_PlainImageTint(&tint,0xffffffffU,1.0f);
  C2D_DrawParams params{};params.pos={0,0,static_cast<float>(width),static_cast<float>(height)};
  return C2D_DrawImage({&canvas,&sub},&params,&tint);
}
// Independent stages verify clear, raster/clip, atlas/flips, and both LCDs.
// Alternate-row evidence never substitutes for the expected primary pixel.
struct PixelCheck {
  const char* stage;
  unsigned samples{},mismatches{};
  void check(unsigned x,unsigned y,u32 expected,u32 actual,u32 raw_value,u32 alternate) noexcept {
    ++samples;
    if(actual==expected)return;
    if(mismatches++<8U)
      boot_log("gpu-mismatch: stage=%s x=%u y=%u expected=%08lx actual=%08lx raw=%08lx alternate_y_raw=%08lx",
        stage,x,y,static_cast<unsigned long>(expected),static_cast<unsigned long>(actual),
        static_cast<unsigned long>(raw_value),static_cast<unsigned long>(alternate));
  }
  bool finish(bool submitted,bool barrier,bool visible=true) const noexcept {
    const bool ok=submitted&&barrier&&visible&&samples>0&&mismatches==0;
    boot_log("gpu-stage: name=%s status=%s samples=%u mismatches=%u submitted=%u barrier_returned=%u cpu_read_ready=%u",
      stage,ok?"PASS":"FAIL",samples,mismatches,submitted?1U:0U,barrier?1U:0U,visible?1U:0U);
    return ok;
  }
};
void diagnostic_canvas_pixel(PixelCheck& test,unsigned x,unsigned y,u32 expected) noexcept {
  const auto* data=static_cast<const u32*>(canvas.data);
  const auto raw_value=data[gpu_tile_offset(x,y,1024)];
  // Alternate interpretation is EVIDENCE ONLY. It never changes the verdict.
  const auto alternate=data[gpu_tile_offset(x,511U-y,1024)];
  test.check(x,y,expected,gpu_pixel(raw_value),raw_value,alternate);
}
bool diagnostic_complete() noexcept {
  end_job();outputs(false);record_completion();
  return !in_frame&&!pending;
}
struct LcdCapture {
  u8* data{};u16 physical_width{},physical_height{};
  unsigned format{},width{};
  std::size_t bytes{};
};
LcdCapture diagnostic_capture(gfxScreen_t screen,unsigned width) noexcept {
  LcdCapture result;result.width=width;
  result.format=static_cast<unsigned>(gfxGetScreenFormat(screen));
  result.data=gfxGetFramebuffer(screen,GFX_LEFT,&result.physical_width,&result.physical_height);
  result.bytes=static_cast<std::size_t>(result.physical_width)*result.physical_height*
    gpu_lcd_pixel_size(result.format);
  return result;
}
bool diagnostic_lcd(const LcdCapture& capture,const char* name,bool submitted,bool barrier,
                    bool is_top) noexcept {
  PixelCheck test{name};
  const bool dimensions=capture.data&&capture.physical_width==240&&capture.physical_height==capture.width;
  const bool visible=dimensions&&capture.bytes&&R_SUCCEEDED(GSPGPU_InvalidateDataCache(
    capture.data,static_cast<u32>(capture.bytes)));
  boot_log("gpu-target: stage=%s format=%u physical=%ux%u logical=%ux240 bytes=%lu captured_before_submit=1 cache_invalidated=%u lcd_visual=NOT_PROVEN",
    name,capture.format,static_cast<unsigned>(capture.physical_width),
    static_cast<unsigned>(capture.physical_height),capture.width,
    static_cast<unsigned long>(capture.bytes),visible?1U:0U);
  if(visible) {
    constexpr unsigned points[][2]={{15,15},{280,15},{15,210},{280,210},{85,110},{220,150}};
    for(const auto& point:points) {
      const unsigned x=point[0],y=point[1];u32 actual{};
      const bool decoded=gpu_lcd_rgb(capture.data,capture.bytes,capture.format,capture.width,240,x,y,actual);
      const auto expected=gpu_diagnostic_scene(is_top?x+120U:2U*x,is_top?y+96U:2U*y)&0xffffffU;
      test.check(x,y,expected,decoded?actual:0xdeadbeefU,actual,0);
    }
  }
  return test.finish(submitted,barrier,visible);
}
bool startup_self_test() noexcept {
  clip={0,0,640,480};empty_clip=false;
  boot_log("gpu-diagnostic: revision=R56 canvas=1024x512 logical=640x480 atlas=512x512 format=RGBA8 upload_formula=tex3ds_row_y canvas_read_formula=row_y screen_v=1_minus_y full_linear_flush=retained lcd_visual=NOT_PROVEN prepared_tiles=1 source_padding_bytes=0");
  bool all=true;
  // A: no texture or coordinate-dependent content. Distinguish clear/colour
  // storage from upload/sampling, while reporting non-symmetric raw channels.
  PixelCheck clear{"clear-readback"};
  bool submitted=begin_job();
  if(submitted)C2D_TargetClear(canvas_target,0xff653511U);
  bool barrier=diagnostic_complete();
  constexpr unsigned corners[][2]={{0,0},{639,0},{0,479},{639,479},{333,227}};
  for(const auto& point:corners)diagnostic_canvas_pixel(clear,point[0],point[1],0xff653511U);
  all=clear.finish(submitted,barrier)&&all;
  // B: untextured rasterisation and scissor, independent from the uploader.
  PixelCheck raster{"raster-and-clip"};submitted=begin_job();
  if(submitted) {
    C2D_TargetClear(canvas_target,0xff000000U);
    const SDL_Rect red{16,24,28,20},green{580,420,24,28};
    submitted=gpu_fill(&red,0xff0000ffU)&&submitted;
    submitted=gpu_fill(&green,0xff00ff00U)&&submitted;
    const SDL_Rect cut{300,200,20,16},blue{290,190,40,40};gpu_clip(&cut);
    submitted=gpu_fill(&blue,0xffff0000U)&&submitted;
    gpu_clip(nullptr);
  }
  barrier=diagnostic_complete();
  diagnostic_canvas_pixel(raster,20,28,0xff0000ffU);
  diagnostic_canvas_pixel(raster,590,430,0xff00ff00U);
  diagnostic_canvas_pixel(raster,310,208,0xffff0000U);
  diagnostic_canvas_pixel(raster,295,208,0xff000000U);
  diagnostic_canvas_pixel(raster,310,220,0xff000000U);
  all=raster.finish(submitted,barrier)&&all;
  // C: retain all 1024 exact R53 crop/flip comparisons.
  std::array<std::uint32_t,16*16> pattern{};
  for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x)
    pattern[y*16+x]=C2D_Color32(x*13U,y*11U,37U^x^y,255);
  gpu_upload_rgba(static_cast<std::uint32_t*>(pages[0].texture.data),512,
    24,40,pattern.data(),16,16,16);
  PixelCheck texture{"atlas-crop-four-flips"};submitted=begin_job();
  if(submitted) {
    C2D_TargetClear(canvas_target,0xff000000U);
    const Tex3DS_SubTexture sub{16,16,24/512.0f,1-40/512.0f,40/512.0f,1-56/512.0f};
    for(unsigned flip=0;flip<4;++flip)
      submitted=draw_image(pages[0].texture,sub,{12.0f+flip*24,20,16,16},
        0xffffffffU,(flip&1)!=0,(flip&2)!=0)&&submitted;
  }
  barrier=diagnostic_complete();
  for(unsigned flip=0;flip<4;++flip)for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x)
    diagnostic_canvas_pixel(texture,12+flip*24+x,20+y,
      pattern[((flip&2)?15-y:y)*16+((flip&1)?15-x:x)]);
  all=texture.finish(submitted,barrier)&&all;
  // D: use the actual production canvas -> both output -> GX transfer path.
  // Read the buffers selected for this job, not the next post-swap backbuffers.
  submitted=begin_job();
  if(submitted) {
    C2D_TargetClear(canvas_target,0xff000000U);
    for(unsigned y=0;y<480;y+=240)for(unsigned x=0;x<640;x+=320) {
      const SDL_Rect rect{static_cast<int>(x),static_cast<int>(y),320,240};
      submitted=gpu_fill(&rect,gpu_diagnostic_scene(x,y))&&submitted;
    }
  }
  const auto top=diagnostic_capture(GFX_TOP,400),bottom=diagnostic_capture(GFX_BOTTOM,320);
  if(in_frame) {
    submitted=gpu_top({120,96,400,240})&&submitted;
    submitted=gpu_bottom({120,96,400,240},nullptr,0)&&submitted;
  }
  barrier=diagnostic_complete();
  all=diagnostic_lcd(top,"canvas-to-top-buffer",submitted,barrier,true)&&all;
  all=diagnostic_lcd(bottom,"canvas-to-bottom-buffer",submitted,barrier,false)&&all;
  boot_log("gpu-self-test: result=%s pixels=1024 mismatches=%u checks=staged-clear-raster-atlas-dual-output stages=5 lcd_visual=NOT_PROVEN",
    all?"PASS":"FAIL",texture.mismatches);
  if(all) {
    // Self-test pixels must not remain visible throughout Lua/asset startup.
    // Reuse the canvas and both targets, complete the transfer, then let SDL
    // display the normal boot status. No per-frame work or extra allocation.
    bool clean=begin_job();
    if(clean) {
      C2D_TargetClear(canvas_target,C2D_Color32(18,25,32,255));
      clean=screen_image(top_target,{0,0,640,480},400,240)&&clean;
      clean=screen_image(bottom_target,{0,0,640,480},320,240)&&clean;
    }
    const bool completed=diagnostic_complete();
    all=clean&&completed;
    boot_log("gpu-startup: test_pattern_cleared=%u transfer_completed=%u loading_background=18,25,32",
      clean?1U:0U,completed?1U:0U);
  }
  stats={};epoch=1;objects=0;clip={0,0,640,480};empty_clip=false;
  return all;
}
void forget(Image* image) noexcept {
  if(image->previous)image->previous->next=image->next;else images=image->next;
  if(image->next)image->next->previous=image->previous;
  stats.source_bytes-=image->source_bytes;
  if(image->indexed){stats.indexed_bytes-=image->source_bytes;--stats.indexed_images;}
  --stats.source_images;SDL_SetTextureUserData(image->handle,nullptr);delete image;
}
} // namespace

bool gpu_active() noexcept {return active;}
bool gpu_initialize() noexcept {
  if(active)return true;
  if(static_cast<unsigned>(gfxGetScreenFormat(GFX_TOP))>4 ||
     static_cast<unsigned>(gfxGetScreenFormat(GFX_BOTTOM))>4){
    boot_log("gpu: selected=software reason=unknown-framebuffer-format");return false;}
  if(auto* file=std::fopen("sdmc:/3ds/corsixth/bottom-screen-panel.txt","rb")){
    std::fclose(file);boot_log("gpu: selected=software reason=legacy-panel");return false;}
  if(auto* file=std::fopen("sdmc:/3ds/corsixth/gpu-software.txt","rb")){
    std::fclose(file);boot_log("gpu: selected=software reason=reference-marker");return false;}
  c3_ready=C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);
  if(c3_ready)c2_ready=C2D_Init(max_objects);
  if(!c2_ready)goto failed;
  if(!C3D_TexInitVRAM(&canvas,1024,512,GPU_RGBA8))goto failed;
  texture_settings(canvas);
  canvas_target=C3D_RenderTargetCreateFromTex(&canvas,GPU_TEXFACE_2D,0,-1);
  top_target=C3D_RenderTargetCreate(240,400,GPU_RB_RGBA8,-1);
  bottom_target=C3D_RenderTargetCreate(240,320,GPU_RB_RGBA8,-1);
  if(!canvas_target||!top_target||!bottom_target)goto failed;
  for(auto& page:pages){if(!C3D_TexInit(&page.texture,512,512,GPU_RGBA8))goto failed;
    texture_settings(page.texture);}
  if(!C3D_TexInit(&overlay,512,16,GPU_RGBA8))goto failed;
  texture_settings(overlay);active=true;
  if(!startup_self_test()){
    gpu_shutdown();boot_log("gpu: selected=software reason=startup-pixel-contract-failed");return false;
  }
  buffered_log("gpu: selected=citro2d canvas=1024x512 logical=640x480 atlas_pages=3 atlas_linear_bytes=3145728 canvas_vram_bytes=2097152 screens_vram_bytes=691200 depth_bytes=0 stereo=0 linear_free=%lu vram_free=%lu",
    static_cast<unsigned long>(linearSpaceFree()),static_cast<unsigned long>(vramSpaceFree()));
  buffered_log("gpu: existing_lcd_format_top=%u bottom=%u SDL_owns_framebuffers=1",
    static_cast<unsigned>(gfxGetScreenFormat(GFX_TOP)),static_cast<unsigned>(gfxGetScreenFormat(GFX_BOTTOM)));
  buffered_log("gpu: atlas_floor_affinity=%u affinity_bytes=%u extra_texture_bytes=0",
    CTH3DS_GPU_ATLAS_AFFINITY?1U:0U,unsigned(sizeof(affinity)));
  runtime_diagnostic_flush();
  return true;
failed:
  gpu_shutdown();boot_log("gpu: selected=software reason=allocation-or-init-failed");return false;
}
void gpu_quiesce() noexcept {
  if(!c3_ready)return;
  end_job();
  // Detaching linked outputs is a public C3D queue completion barrier. SDL can
  // now paint a boot/fatal page or the system applet can own the screens.
  outputs(false);record_completion();
}
void gpu_shutdown() noexcept {
  affinity={};
  if(c3_ready)gpu_quiesce();
  if(canvas_target)C3D_RenderTargetDelete(canvas_target);
  canvas_target=nullptr;
  if(top_target)C3D_RenderTargetDelete(top_target);
  top_target=nullptr;
  if(bottom_target)C3D_RenderTargetDelete(bottom_target);
  bottom_target=nullptr;
  if(canvas.data)C3D_TexDelete(&canvas);
  canvas={};
  if(overlay.data)C3D_TexDelete(&overlay);
  overlay={};
  for(auto& page:pages){if(page.texture.data)C3D_TexDelete(&page.texture);page={};}
  if(c2_ready)C2D_Fini();
  if(c3_ready)C3D_Fini();
  active=c2_ready=c3_ready=in_frame=pending=false;
}
bool gpu_begin() noexcept {
  if(!active)return false;
  submit.frame();
  if(in_frame)end_job();
  clip={0,0,640,480};empty_clip=false;
  stats.frame_upload_start=stats.upload_bytes;stats.frame_eviction_start=stats.evictions;
  return begin_job();
}
bool gpu_clear(std::uint32_t colour) noexcept {
  if(!in_frame && !gpu_begin())return false;
  C2D_TargetClear(canvas_target,colour);return true;
}
void gpu_clip(const SDL_Rect* rectangle) noexcept {
  const SDL_Rect full{0,0,640,480};
  SDL_Rect next=full;
  const bool next_empty=rectangle && !SDL_IntersectRect(&full,rectangle,&next);
  if(next_empty)next={0,0,1,1};
  ++stats.clip_requests;
  if(canvas_clip_active && empty_clip==next_empty &&
     clip.x==next.x && clip.y==next.y && clip.w==next.w && clip.h==next.h){
    ++stats.clip_skips;return;
  }
  empty_clip=next_empty;clip=next;
  if(in_frame)apply_clip();
}
bool gpu_fill(const SDL_Rect* rectangle,std::uint32_t colour) noexcept {
  if(empty_clip)return true;
  if(!room_for_draw())return false;
  const SDL_Rect full{0,0,640,480};const auto& r=rectangle?*rectangle:full;
  if(r.w<=0||r.h<=0)return true;
  return C2D_DrawRectSolid(static_cast<float>(r.x),static_cast<float>(r.y),0,
    static_cast<float>(r.w),static_cast<float>(r.h),colour);
}
bool gpu_line(int x1,int y1,int x2,int y2,std::uint32_t colour) noexcept {
  if(empty_clip)return true;
  if(x1==x2||y1==y2){const SDL_Rect line{std::min(x1,x2),std::min(y1,y2),
    std::abs(x2-x1)+1,std::abs(y2-y1)+1};return gpu_fill(&line,colour);}
  if(!room_for_draw())return false;
  return C2D_DrawLine(x1+0.5f,y1+0.5f,colour,x2+0.5f,y2+0.5f,colour,1.0f,0);
}
SDL_Texture* gpu_image_create(SDL_Renderer* renderer,int width,int height,const std::uint32_t* pixels) noexcept {
  if(!pixels||width<1||height<1||width>4096||height>4096){SDL_SetError("Invalid GPU image");return nullptr;}
  try {
    auto image=std::make_unique<Image>();image->renderer=renderer;image->width=width;image->height=height;
    const std::size_t count=static_cast<std::size_t>(width)*height;
    image->source_bytes=count*4U;
    CpuWorkScope prepare(CpuWork::GpuPrepare,count*4U);
    image->pieces.reserve(((width+gpu_source_extent-1)/gpu_source_extent)*((height+gpu_source_extent-1)/gpu_source_extent));
    for(int y=0;y<height;y+=gpu_source_extent)for(int x=0;x<width;x+=gpu_source_extent) {
      Piece piece;piece.sx=x;piece.sy=y;piece.w=std::min(gpu_source_extent,width-x);piece.h=std::min(gpu_source_extent,height-y);
      const auto bytes=static_cast<std::size_t>(piece.w)*piece.h*4U;
      piece.pixels.reset(new std::uint32_t[bytes/4U]);
      stats.source_block_peak=std::max<std::uint64_t>(stats.source_block_peak,bytes);
      gpu_prepare_pixels(piece.pixels.get(),pixels+y*width+x,width,piece.w,piece.h);
      image->pieces.push_back(std::move(piece));
    }
    image->handle=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,1,1);
    if(!image->handle)return nullptr;
    if(SDL_SetTextureUserData(image->handle,image.get())!=0){SDL_DestroyTexture(image->handle);return nullptr;}
    image->next=images;if(images)images->previous=image.get();images=image.get();
    stats.source_bytes+=count*4U;stats.source_peak=std::max(stats.source_peak,stats.source_bytes);++stats.source_images;
    return image.release()->handle;
  }catch(...){++stats.source_failures;SDL_OutOfMemory();return nullptr;}
}
SDL_Texture* gpu_image_create_indexed(SDL_Renderer* renderer,int width,int height,
    const std::uint8_t* indices,const std::uint32_t* palette,bool flip_x,bool flip_y) noexcept {
  if(!indices||!palette||width<1||height<1||width>4096||height>4096){SDL_SetError("Invalid indexed GPU image");return nullptr;}
  try {
    auto image=std::make_unique<Image>();image->renderer=renderer;image->width=width;image->height=height;
    image->indexed=true;image->palette=std::make_unique<std::array<std::uint32_t,256>>();
    image->source_bytes=static_cast<std::size_t>(width)*height+sizeof(*image->palette);
    for(unsigned i=0;i<256;++i)(*image->palette)[i]=gpu_pixel(palette[i]);
    image->pieces.reserve(((width+gpu_source_extent-1)/gpu_source_extent)*((height+gpu_source_extent-1)/gpu_source_extent));
    CpuWorkScope prepare(CpuWork::GpuPrepare,static_cast<std::uint64_t>(width)*height);
    for(int y=0;y<height;y+=gpu_source_extent)for(int x=0;x<width;x+=gpu_source_extent){
      Piece piece;piece.sx=x;piece.sy=y;piece.w=std::min(gpu_source_extent,width-x);piece.h=std::min(gpu_source_extent,height-y);
      const auto bytes=static_cast<std::size_t>(piece.w)*piece.h;
      piece.indices.reset(new std::uint8_t[bytes]);
      stats.source_block_peak=std::max<std::uint64_t>(stats.source_block_peak,bytes);
      gpu_prepare_indices(piece.indices.get(),indices,width,height,x,y,piece.w,piece.h,flip_x,flip_y);
      image->pieces.push_back(std::move(piece));
    }
    image->handle=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,1,1);
    if(!image->handle)return nullptr;
    if(SDL_SetTextureUserData(image->handle,image.get())!=0){SDL_DestroyTexture(image->handle);return nullptr;}
    image->next=images;if(images)images->previous=image.get();images=image.get();
    stats.source_bytes+=image->source_bytes;stats.source_peak=std::max(stats.source_peak,stats.source_bytes);
    stats.indexed_bytes+=image->source_bytes;++stats.source_images;++stats.indexed_images;
    return image.release()->handle;
  }catch(...){++stats.source_failures;SDL_OutOfMemory();return nullptr;}
}
void gpu_image_destroy(SDL_Texture* handle) noexcept {
  if(handle){if(auto* image=static_cast<Image*>(SDL_GetTextureUserData(handle)))forget(image);
    SDL_DestroyTexture(handle);}
}
void gpu_images_release(SDL_Renderer* renderer) noexcept {
  auto* image=images;while(image){auto* next=image->next;if(image->renderer==renderer)forget(image);image=next;}
}
int gpu_image_draw(SDL_Texture* texture,const SDL_Rect* source,const SDL_FRect* destination,SDL_RendererFlip flip) noexcept {
  submit.inc(GpuSubmitSample::Calls);
  if(affinity.floor)submit.inc(GpuSubmitSample::FloorCalls);
  const bool chosen=submit.enabled && (submit.bridge?submit.selected:submit.choose());
  const auto entry=chosen?svcGetSystemTick():0;
  bool emitted=false,failed=true,accepted=false;
  struct Finish {
    bool chosen;bool &emitted,&failed,&accepted;
    ~Finish(){
      if(failed)submit.inc(GpuSubmitSample::Errors);
      else if(!emitted)submit.inc(GpuSubmitSample::Culled);
      if(chosen&&!accepted)submit.inc(GpuSubmitSample::Rejected);
    }
  } finish{chosen,emitted,failed,accepted};
  auto* image=texture?static_cast<Image*>(SDL_GetTextureUserData(texture)):nullptr;
  if(!image||!destination||!std::isfinite(destination->x)||!std::isfinite(destination->y)||
     !std::isfinite(destination->w)||!std::isfinite(destination->h))return SDL_SetError("Invalid GPU draw");
  if(empty_clip||destination->w<=0||destination->h<=0){failed=false;return 0;}
  const SDL_Rect src=source?*source:SDL_Rect{0,0,image->width,image->height};
  if(src.w<=0||src.h<=0){failed=false;return 0;}
  if(src.x<0||src.y<0||src.x>image->width-src.w||src.y>image->height-src.h)return SDL_SetError("GPU source outside image");
  Uint8 r=255,g=255,b=255,a=255;SDL_GetTextureColorMod(texture,&r,&g,&b);SDL_GetTextureAlphaMod(texture,&a);
  const bool fx=(flip&SDL_FLIP_HORIZONTAL)!=0,fy=(flip&SDL_FLIP_VERTICAL)!=0;
  const bool whole=image->pieces.size()==1 && src.x==0 && src.y==0 &&
    src.w==image->width && src.h==image->height;
  submit.inc(whole?GpuSubmitSample::Whole:(image->pieces.size()>1?GpuSubmitSample::Multi:GpuSubmitSample::Partial));
  const bool timed=chosen&&whole;
  const auto metadata=timed?svcGetSystemTick():0;
  for(auto& piece:image->pieces){
    SDL_Rect intersection=src;SDL_FRect dst=*destination;
    if(!whole){
    const SDL_Rect area{piece.sx,piece.sy,piece.w,piece.h};
    if(!SDL_IntersectRect(&area,&src,&intersection))continue;
    const float left=static_cast<float>(intersection.x-src.x)/src.w;
    const float right=static_cast<float>(intersection.x+intersection.w-src.x)/src.w;
    const float top=static_cast<float>(intersection.y-src.y)/src.h;
    const float bottom=static_cast<float>(intersection.y+intersection.h-src.y)/src.h;
    dst={destination->x+(fx?1-right:left)*destination->w,
      destination->y+(fy?1-bottom:top)*destination->h,
      (right-left)*destination->w,(bottom-top)*destination->h};
    }
    if(dst.x+dst.w<=clip.x||dst.y+dst.h<=clip.y||dst.x>=clip.x+clip.w||dst.y>=clip.y+clip.h)continue;
    const auto geometry=timed?svcGetSystemTick():0;
    const auto uploads=submit.count[GpuSubmitSample::Uploads];
    const auto checkpoints=stats.splits;
    if(!room_for_draw()||!place(*image,piece))return SDL_SetError("GPU atlas allocation failed");
    const auto placed=timed?svcGetSystemTick():0;
    const int x=piece.x+intersection.x-piece.sx,y=piece.y+intersection.y-piece.sy;
    Tex3DS_SubTexture sub{static_cast<u16>(intersection.w),static_cast<u16>(intersection.h),
      x/512.0f,1.0f-y/512.0f,(x+intersection.w)/512.0f,1.0f-(y+intersection.h)/512.0f};
    const auto prepared=timed?svcGetSystemTick():0;
    if(!draw_image(pages[piece.page].texture,sub,dst,C2D_Color32(r,g,b,a),fx,fy))return SDL_SetError("GPU vertex buffer exhausted");
    const auto drawn=timed?svcGetSystemTick():0;
    const bool switched=submit.last_page>=0&&submit.last_page!=piece.page;
    if(submit.enabled){
      submit.last_page=piece.page;if(switched)submit.inc(GpuSubmitSample::Switches);
      if(affinity.floor){
        submit.inc(GpuSubmitSample::FloorPieces);
        if(submit.floor_last_page>=0&&submit.floor_last_page!=piece.page)submit.inc(GpuSubmitSample::FloorSwitches);
        submit.floor_last_page=piece.page;
      }
    }
    submit.inc(GpuSubmitSample::Pieces);emitted=true;
    if(timed){
      // Disjoint classes: queue boundary, upload, hit with page switch, plain hit.
      const unsigned kind=stats.splits!=checkpoints?3:submit.count[GpuSubmitSample::Uploads]!=uploads?2:switched?1:0;
      submit.inc(GpuSubmitSample::Sampled);
      submit.add(submit.samples[kind]);
      submit.add(submit.ticks[kind][0],submit.delta(entry,metadata));
      if(submit.bridge)submit.add(submit.ticks[kind][0],submit.delta(submit.bridge_start,entry));
      submit.add(submit.ticks[kind][1],submit.delta(metadata,geometry));
      submit.add(submit.ticks[kind][1],submit.delta(placed,prepared));
      submit.add(submit.ticks[kind][2],submit.delta(geometry,placed));
      submit.add(submit.ticks[kind][3],submit.delta(prepared,drawn));
      accepted=true;
    }
    ++stats.draws;if(whole)++stats.full_sprite_draws;
  }
  failed=false;return 0;
}
void gpu_submit_sample_begin(std::uint64_t boundary_us) noexcept {
  submit.begin(boundary_us);submit.eligible=!affinity.floor;
}
void gpu_submit_sample_end(std::uint64_t boundary_us,bool eligible) noexcept {
  submit.end(boundary_us,eligible&&active&&submit.eligible&&!affinity.floor);
}
void gpu_submit_bridge_begin() noexcept {
  if(!submit.enabled)return;
  submit.bridge=true;submit.selected=submit.choose();
  if(submit.selected)submit.bridge_start=svcGetSystemTick();
}
void gpu_submit_bridge_end() noexcept {submit.bridge=false;submit.selected=false;}
void gpu_submit_floor_begin() noexcept {
  affinity.floor=true;
  if(!submit.enabled)return;
  submit.floor=true;submit.floor_last_page=-1;submit.floor_start=svcGetSystemTick();
}
void gpu_submit_floor_end() noexcept {
  affinity.floor=false;
  if(!submit.enabled||!submit.floor)return;
  submit.add(submit.floor_ticks,submit.delta(submit.floor_start,svcGetSystemTick()));
  submit.inc(GpuSubmitSample::Floors);submit.floor=false;
}
void gpu_submit_sample_log(bool flush) noexcept {
  if(submit.enabled)return;
  buffered_log("gpu-submit-window: begin_us=%llu end_us=%llu",(unsigned long long)submit.begin_us,(unsigned long long)submit.end_us);
  buffered_log("gpu-submit-sample: eligible=%u sampled_calls_only=1 stride=64 bytes=%u overflow=%u clock_rollback=%u tick_hz=%llu floor_ticks=%llu floor_is_upper_bound=1",
    submit.eligible?1U:0U,unsigned(sizeof(submit)),submit.overflow?1U:0U,submit.rollback?1U:0U,
    (unsigned long long)SYSCLOCK_ARM11,(unsigned long long)submit.floor_ticks);
  static const char* names[]={"calls","culled","errors","pieces","whole","multi_excluded","partial_excluded","hits","uploads","page_switches","checkpoint_objects","checkpoint_commands","checkpoint_eviction","sampled","rejected","floor_calls","floors","frames","floor_pieces","floor_switches"};
  for(unsigned i=0;i<GpuSubmitSample::Count;++i)
    buffered_log("gpu-submit-count: name=%s value=%llu",names[i],(unsigned long long)submit.count[i]);
  static const char* kinds[]={"hit","hit_switch","upload","checkpoint"};
  for(unsigned i=0;i<4;++i)buffered_log("gpu-submit-ticks: class=%s bridge=%llu geometry=%llu atlas_queue=%llu c2d=%llu sampled_only=1 samples=%llu",
    kinds[i],(unsigned long long)submit.ticks[i][0],(unsigned long long)submit.ticks[i][1],
    (unsigned long long)submit.ticks[i][2],(unsigned long long)submit.ticks[i][3],(unsigned long long)submit.samples[i]);
  // Aggregate callers synchronously publish after their trailing rows; the
  // standalone default keeps this complete report visible before returning.
  if(flush)runtime_diagnostic_flush();
}
bool gpu_top(RectI view) noexcept {
  if(!in_frame)return false;
  if(objects>=max_objects-32){submit.inc(GpuSubmitSample::ObjectCheckpoint);if(!checkpoint())return false;}
  else if(command_pressure()){submit.inc(GpuSubmitSample::CommandCheckpoint);if(!checkpoint())return false;}
  return screen_image(top_target,view,400,240);
}
bool gpu_bottom(RectI view,const std::uint32_t* rgba,int height) noexcept {
  bool ok=screen_image(bottom_target,{0,0,640,480},320,240);
  const float x=view.x*0.5f,y=view.y*0.5f,w=view.w*0.5f,h=view.h*0.5f;
  ok=C2D_DrawRectSolid(x,y,0,w,1,0xffffffffU)&&ok;
  ok=C2D_DrawRectSolid(x,y+h-1,0,w,1,0xffffffffU)&&ok;
  ok=C2D_DrawRectSolid(x,y,0,1,h,0xffffffffU)&&ok;
  ok=C2D_DrawRectSolid(x+w-1,y,0,1,h,0xffffffffU)&&ok;
  if(rgba&&height>0&&height<=16){
    auto* out=static_cast<std::uint32_t*>(overlay.data);
    gpu_upload_rgba(out,512,0,0,rgba,320,320,height);
    Tex3DS_SubTexture sub{320,static_cast<u16>(height),0,1,320/512.0f,1-height/16.0f};
    C2D_DrawParams params{};params.pos={0,0,320,static_cast<float>(height)};
    C2D_ImageTint tint;C2D_PlainImageTint(&tint,0xffffffffU,1.0f);
    ok=C2D_DrawImage({&overlay,&sub},&params,&tint)&&ok;
  }
  stats.frame_upload_peak=std::max(stats.frame_upload_peak,stats.upload_bytes-stats.frame_upload_start);
  stats.frame_eviction_peak=std::max(stats.frame_eviction_peak,stats.evictions-stats.frame_eviction_start);
  end_job();++stats.frames;return ok;
}
bool gpu_read_pixels(SDL_Surface* surface) noexcept {
  if(!active||!surface||surface->w!=640||surface->h!=480)return false;
  gpu_quiesce();
  const auto* data=static_cast<const std::uint32_t*>(canvas.data);
  for(int y=0;y<480;++y)for(int x=0;x<640;++x){
    const auto colour=gpu_pixel(data[gpu_tile_offset(x,y,1024)]);
    const auto mapped=SDL_MapRGBA(surface->format,colour&255U,(colour>>8U)&255U,(colour>>16U)&255U,colour>>24U);
    auto* dest=static_cast<std::uint8_t*>(surface->pixels)+y*surface->pitch+x*surface->format->BytesPerPixel;
    std::memcpy(dest,&mapped,surface->format->BytesPerPixel);
  }
  return true;
}
void gpu_log_statistics() noexcept {
  if(!active)return;
  // RuntimeObservations owns this report's final flush after display statistics.
  buffered_log("gpu-source: indexed_images=%llu indexed_bytes=%llu block_peak_bytes=%llu allocation_failures=%llu source_block_limit=65536 atlas=skyline-lru",
    (unsigned long long)stats.indexed_images,(unsigned long long)stats.indexed_bytes,
    (unsigned long long)stats.source_block_peak,(unsigned long long)stats.source_failures);
  buffered_log("gpu-hot-paths: clip_requests=%llu clip_skips=%llu full_sprite_draws=%llu frame_upload_peak_bytes=%llu frame_eviction_peak=%llu scope=session",
    (unsigned long long)stats.clip_requests,(unsigned long long)stats.clip_skips,
    (unsigned long long)stats.full_sprite_draws,(unsigned long long)stats.frame_upload_peak,
    (unsigned long long)stats.frame_eviction_peak);
  buffered_log("gpu-work: frames=%llu draws=%llu hits=%llu uploads=%llu upload_bytes=%llu evictions=%llu splits=%llu wait_us=%llu completed_gpu_jobs=%llu gpu_queue_us=%llu cmd_peak_permille=%u source_bytes=%llu source_peak=%llu images=%llu atlas_linear_bytes=3145728 canvas_vram_bytes=2097152 screen_vram_bytes=691200 linear_free=%lu vram_free=%lu",
    (unsigned long long)stats.frames,(unsigned long long)stats.draws,(unsigned long long)stats.hits,
    (unsigned long long)stats.uploads,(unsigned long long)stats.upload_bytes,(unsigned long long)stats.evictions,
    (unsigned long long)stats.splits,(unsigned long long)stats.wait_us,(unsigned long long)stats.gpu_jobs,
    (unsigned long long)stats.gpu_us,(unsigned)(stats.cmd_peak*1000),
    (unsigned long long)stats.source_bytes,(unsigned long long)stats.source_peak,(unsigned long long)stats.source_images,
    (unsigned long)linearSpaceFree(),(unsigned long)vramSpaceFree());
}
} // namespace cth3ds
#endif
