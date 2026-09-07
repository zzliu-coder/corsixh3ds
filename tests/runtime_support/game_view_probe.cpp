// Tests the compiled production component with real SDL surfaces and HID mapping.
// Window submission, physical LCD/HID timing and the game loop remain device gates.
#include <SDL.h>
#include <cassert>
#include <cstdio>
#include <type_traits>
#include <vector>
#include "runtime/game_view.hpp"
#include "cth3ds/hid_snapshot.hpp"
#include "cth3ds/input_mapper.hpp"

using namespace cth3ds;
static_assert(sizeof(GameView) <= 64, "view state must stay bounded and buffer-free");
static_assert(std::is_trivially_destructible<GameView>::value, "view must not own canvas/window resources");

int main() {
  auto* top = SDL_CreateRGBSurfaceWithFormat(0,400,240,32,SDL_PIXELFORMAT_RGBA8888);
  auto* source = SDL_CreateRGBSurfaceWithFormat(0,640,480,32,SDL_PIXELFORMAT_ABGR8888);
  // Deliberately padded lower rows: copying the view must not touch padding.
  std::vector<std::uint32_t> bottom_pixels(324*240, 0xabcdef01U);
  auto* bottom = SDL_CreateRGBSurfaceWithFormatFrom(bottom_pixels.data(),320,240,32,324*4,SDL_PIXELFORMAT_RGBA8888);
  assert(top && source && bottom);
  auto* pixels = static_cast<std::uint32_t*>(source->pixels);
  for (int i=0;i<640*480;++i) pixels[i]=0xff000000U+static_cast<std::uint32_t>(i);
  GameView v;
  Vec2i pointer{320,240};
  auto present = [&] {
    assert(GameView::valid_output(source,top,400,240));
    assert(GameView::valid_output(source,bottom,320,240));
    v.follow(pointer);
    assert(v.copy_top(source,top));
    assert(v.copy_bottom(source,bottom));
  };
  v.set_context(InputContext::World);present();
  assert(v.bounds().x==120 && v.bounds().y==120);
  InputMapperConfig c;c.overview_controls=true;InputMapper mapper(c);
  RawInputSnapshot s;s.timestamp_us=8000;s.circle_x=156;s.circle_y=-156;
  InputContext context=InputContext::World;
  auto read=[&]{v.set_context(context);return context;};
  auto dispatch=[&](const Action& a){
    if(a.type==ActionType::MoveViewport)v.move(a.vector,pointer);
    if(a.type==ActionType::ToggleView)v.toggle();
    return true;
  };
  assert(mapper.dispatch_mixed(s,.1F,read,dispatch));
  const auto moved=v.bounds();assert(moved.x>120 && moved.y>120);
  for(int i=0;i<20;++i)present();
  assert(v.bounds().x==moved.x && v.bounds().y==moved.y);
  s.circle_x=s.circle_y=0;
  std::uint32_t hid[128]{};hid[4]=hid[46]=1;
  for(auto ctx:{InputContext::World,InputContext::BuildRoom,InputContext::PlaceObject,
                InputContext::Menu,InputContext::Dialog,InputContext::TextInput}) {
    context=ctx;read();assert(v.bounds().w==400);
    for(int toggle=0;toggle<2;++toggle) {
      hid[14]=0;assert(read_hid_snapshot(hid,s.timestamp_us+8000,s));
      assert(mapper.dispatch_mixed(s,.008F,read,dispatch));
      hid[14]=button_mask(Button::L);assert(read_hid_snapshot(hid,s.timestamp_us+8000,s));
      assert(mapper.dispatch_mixed(s,.008F,read,dispatch));
      assert(v.bounds().w==(toggle==0?480:400) && v.bounds().h==(toggle==0?288:240));
      present();
      const auto b=v.bounds();
      auto* output=static_cast<const std::uint32_t*>(top->pixels);
      for(int y=0;y<240;++y)for(int x=0;x<400;++x) {
        const auto word=pixels[(b.y+y*b.h/240)*640+b.x+x*b.w/400];
        assert(output[y*400+x]==__builtin_bswap32(word));
      }
      for(int y=0;y<240;++y)for(int x=0;x<324;++x) {
        const bool horizontal=(y==b.y/2 || y==b.y/2+b.h/2-1) && x>=b.x/2 && x<b.x/2+b.w/2;
        const bool vertical=(x==b.x/2 || x==b.x/2+b.w/2-1) && y>=b.y/2 && y<b.y/2+b.h/2;
        const auto expected=x>=320?0xabcdef01U:(horizontal||vertical?0xffffffffU:__builtin_bswap32(pixels[y*2*640+x*2]));
        assert(bottom_pixels[static_cast<std::size_t>(y*324+x)]==expected);
      }
    }
  }
  v.set_context(InputContext::World);v.toggle();assert(v.bounds().w==480);
  v.set_context(InputContext::Dialog);assert(v.bounds().w==400);
  v.set_context(InputContext::World);assert(v.bounds().w==480);
  v.toggle();pointer={10,10};present();assert(v.bounds().x==0 && v.bounds().y==0);
  v.move({300,300},pointer);present();assert(v.bounds().x==240 && v.bounds().y==240);
  assert(v.activation_needs_focus(ActionType::Confirm,pointer));
  assert(!v.activation_needs_focus(ActionType::PanCamera,pointer));
  v.focus(10,10);present();assert(!v.activation_needs_focus(ActionType::Confirm,pointer));
  for(int i=0;i<20;++i)v.move({.25F,.25F},pointer);
  assert(v.bounds().x==5 && v.bounds().y==5);present();assert(v.bounds().x==5);
  v.move({-1000,-1000},pointer);present();assert(v.bounds().x==0 && v.bounds().y==0);
  // Only displacement beyond the visible-canvas border pans the world.
  for(auto context:{InputContext::World,InputContext::BuildRoom,InputContext::PlaceObject}) {
    v=GameView{};
    v.set_context(context);v.inspect(320,240,pointer);
    auto remaining=v.move({130,150},pointer);
    if(v.bounds().x!=240 || v.bounds().y!=240 || remaining.x!=10 || remaining.y!=30)
      std::fprintf(stderr,"context %u bounds %d,%d %dx%d remainder %.3f,%.3f\n",
        unsigned(context),v.bounds().x,v.bounds().y,v.bounds().w,v.bounds().h,remaining.x,remaining.y);
    assert(v.bounds().x==240 && v.bounds().y==240 && remaining.x==10 && remaining.y==30);
    remaining=v.move({-5,-7},pointer);assert(remaining.x==0 && remaining.y==0);
    remaining=v.move({-245,-250},pointer);
    assert(v.bounds().x==0 && v.bounds().y==0 && remaining.x==-10 && remaining.y==-17);
    remaining=v.move({-2,9},pointer);assert(remaining.x==-2 && remaining.y==0);
  }
  for(auto context:{InputContext::Menu,InputContext::Dialog,InputContext::TextInput}) {
    v.set_context(context);v.inspect(600,400,pointer);v.follow(pointer);
    assert(v.bounds().x==240 && v.bounds().y==240); // focus never moves the pen
    const auto remaining=v.move({1000,1000},pointer);
    assert(remaining.x==0 && remaining.y==0);
  }
  assert(!GameView::valid_output(nullptr,top,400,240));
  assert(!GameView::valid_output(source,nullptr,400,240));
  const auto pitch=source->pitch;source->pitch=2559;
  assert(!GameView::valid_output(source,top,400,240));source->pitch=pitch;
  const auto format=top->format->format;top->format->format=SDL_PIXELFORMAT_RGB565;
  assert(!GameView::valid_output(source,top,400,240));top->format->format=format;
  // Equal formats must keep words unchanged as well as the byte-swapped path.
  top->format->format=source->format->format;present();
  assert(static_cast<const std::uint32_t*>(top->pixels)[0]==pixels[v.bounds().y*640+v.bounds().x]);
  SDL_FreeSurface(top);SDL_FreeSurface(source);SDL_FreeSurface(bottom);
  std::puts("PASS compiled GameView: HID L, persistent white frame, top/bottom pixels, formats, padding, focus");
}
