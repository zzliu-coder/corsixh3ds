#include "test_framework.hpp"
#include "cth3ds/input_queue.hpp"
#include "cth3ds/hid_snapshot.hpp"
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/framebuffer_scaler.hpp"
#include "cth3ds/render_work.hpp"
#include <array>
#include <vector>
using namespace cth3ds;

TEST(input_age_percentile_preserves_long_tail_and_no_samples) {
  InputQueue q;EXPECT_EQ(q.statistics().age_p95_upper_us(),0U);
  RawInputSnapshot sample;
  for(unsigned i=0;i<100;++i){sample.timestamp_us=i*1000;sample.touching=i%2;
    q.push(sample);EXPECT_TRUE(q.pop(sample,sample.timestamp_us+(i<95?55000:400000)));}
  EXPECT_EQ(q.statistics().age_p95_upper_us(),60000U);
  EXPECT_EQ(q.statistics().max_age_us,400000U);
}

TEST(queue_retains_taps_and_edges_during_400ms_draw) {
  InputQueue q; RawInputSnapshot s;
  for (unsigned i=0; i<=50; ++i) {
    s.timestamp_us=i*8000U; s.touching=(i>=10 && i<20);
    s.touch={static_cast<int>(i),80}; q.push(s);
  }
  InputMapperConfig c; c.overview_controls=true; InputMapper mapper(c);
  int downs=0, ups=0; Vec2i position{};
  while(q.pop(s,400000)) {
    EXPECT_TRUE(mapper.dispatch_mixed(s,.008F,[]{return InputContext::World;},[&](const Action& a) {
      if(a.type==ActionType::PointerMove)position=a.position;
      if(a.type==ActionType::PointerDown){++downs;EXPECT_EQ(position.x,10);}
      if(a.type==ActionType::PointerUp)++ups;
      return true;
    }));
  }
  EXPECT_EQ(downs,1); EXPECT_EQ(ups,1);
  EXPECT_EQ(q.statistics().touch_down,1U); EXPECT_EQ(q.statistics().touch_up,1U);
  EXPECT_EQ(q.statistics().overflows,0U);
}

TEST(queue_bounded_overflow_requires_cancellation) {
  InputQueue q; RawInputSnapshot s;
  for(unsigned i=0;i<300;++i){s.timestamp_us=i*8000U;s.touching=(i%2)==1;q.push(s);}
  EXPECT_TRUE(q.size()<=InputQueue::capacity);
  EXPECT_EQ(q.statistics().overflows,1U);
  EXPECT_TRUE(q.take_cancellation()); EXPECT_FALSE(q.take_cancellation());
  q.discard(); EXPECT_EQ(q.size(),0U); EXPECT_TRUE(q.take_cancellation());
}

TEST(hid_snapshot_reads_signed_circle_and_rejects_invalid_sections) {
  std::array<std::uint32_t,128> mem{}; RawInputSnapshot s;
  EXPECT_FALSE(read_hid_snapshot(mem.data(),1,s));
  mem[4]=1;mem[46]=1;mem[14]=button_mask(Button::A)|button_mask(Button::DLeft);
  mem[17]=static_cast<std::uint32_t>(static_cast<std::uint16_t>(-90))|(120U<<16U);
  mem[52]=123U|(220U<<16U);mem[53]=1;
  EXPECT_TRUE(read_hid_snapshot(mem.data(),900,s));
  EXPECT_EQ(s.held,button_mask(Button::A)|button_mask(Button::DLeft));
  EXPECT_EQ(s.circle_x,-90);EXPECT_EQ(s.circle_y,120);
  EXPECT_TRUE(s.touching);EXPECT_EQ(s.touch.x,123);EXPECT_EQ(s.touch.y,220);
  mem[4]=8;EXPECT_FALSE(read_hid_snapshot(mem.data(),1,s));
  mem[4]=1;mem[1]=0x80000000U;EXPECT_FALSE(read_hid_snapshot(mem.data(),1,s));
  EXPECT_FALSE(read_hid_snapshot(nullptr,1,s));
}

TEST(overview_controls_have_independent_map_view_cursor_and_shortcuts) {
  auto actions=[](InputContext context,std::uint32_t held,int circle) {
    InputMapperConfig c;c.overview_controls=true;InputMapper mapper(c);
    RawInputSnapshot s;s.timestamp_us=10000;s.held=held;s.circle_x=circle;
    std::vector<Action> result;
    EXPECT_TRUE(mapper.dispatch_mixed(s,.016F,[&]{return context;},[&](const Action& a){result.push_back(a);return true;}));
    return result;
  };
  auto a=actions(InputContext::World,button_mask(Button::DRight),0);
  EXPECT_TRUE(a.empty());
  a=actions(InputContext::World,0,156);EXPECT_EQ(a[0].type,ActionType::MoveViewport);
  a=actions(InputContext::Menu,0,156);EXPECT_EQ(a[0].type,ActionType::MoveViewport);
  a=actions(InputContext::World,button_mask(Button::R)|button_mask(Button::DRight),0);
  EXPECT_TRUE(a.empty());
  a=actions(InputContext::World,button_mask(Button::R)|button_mask(Button::Start),0);
  EXPECT_EQ(a.size(),1U);EXPECT_EQ(a[0].type,ActionType::OpenSaveSlots);
  a=actions(InputContext::World,button_mask(Button::R)|button_mask(Button::Select),0);
  EXPECT_EQ(a[0].type,ActionType::ShowHelp);
  a=actions(InputContext::TextInput,button_mask(Button::A),0);EXPECT_EQ(a[0].type,ActionType::TextKeyboard);
  a=actions(InputContext::World,button_mask(Button::L),0);EXPECT_EQ(a[0].type,ActionType::ToggleView);
  a=actions(InputContext::World,button_mask(Button::Select),0);EXPECT_EQ(a[0].type,ActionType::SpeedCycle);
  a=actions(InputContext::World,button_mask(Button::Y),0);EXPECT_EQ(a[0].type,ActionType::ToggleWalls);
  a=actions(InputContext::PlaceObject,button_mask(Button::B),0);EXPECT_EQ(a[0].type,ActionType::Cancel);
  a=actions(InputContext::PlaceObject,button_mask(Button::X),0);EXPECT_EQ(a[0].type,ActionType::RotateObject);
}

TEST(wide_view_has_exact_nearest_pixels_with_padding_and_edges) {
  std::vector<std::uint32_t> source(644U*480U),dest(404U*240U,0xdeadbeefU);
  for(std::size_t i=0;i<source.size();++i)source[i]=static_cast<std::uint32_t>(i);
  EXPECT_TRUE(scale_rgba_view(source.data(),640,480,644,{160,192,480,288},dest.data(),400,240,404));
  for(unsigned y=0;y<240;++y) {
    for(unsigned x=0;x<400;++x)EXPECT_EQ(dest[y*404+x],source[(192+y*288/240)*644+160+x*480/400]);
    EXPECT_EQ(dest[y*404+400],0xdeadbeefU);
  }
  EXPECT_FALSE(scale_rgba_view(source.data(),640,480,644,{161,192,480,288},dest.data(),400,240,404));
}

TEST(stylus_owns_cursor_and_drag_suspends_circle_view_in_all_contexts) {
  for(auto context:{InputContext::World,InputContext::BuildRoom,InputContext::PlaceObject,
                    InputContext::Menu,InputContext::Dialog,InputContext::TextInput}) {
    InputMapperConfig c;c.overview_controls=true;InputMapper mapper(c);
    RawInputSnapshot s;s.timestamp_us=8000;s.circle_x=156;s.circle_y=156;
    s.touching=true;s.touch={100,80};
    int moved=0,downs=0,ups=0;
    auto consume=[&](const Action& a) {
      EXPECT_FALSE(a.type==ActionType::CursorStep || a.type==ActionType::PanCamera);
      if(a.type==ActionType::MoveViewport)++moved;
      if(a.type==ActionType::PointerDown)++downs;
      if(a.type==ActionType::PointerUp)++ups;
      return true;
    };
    EXPECT_TRUE(mapper.dispatch_mixed(s,.008F,[&]{return context;},consume));
    s.timestamp_us+=8000;s.touch={120,80};
    EXPECT_TRUE(mapper.dispatch_mixed(s,.008F,[&]{return context;},consume));
    EXPECT_EQ(moved,0);EXPECT_EQ(downs,1);
    s.timestamp_us+=8000;s.touching=false;
    EXPECT_TRUE(mapper.dispatch_mixed(s,.008F,[&]{return context;},consume));
    EXPECT_EQ(ups,1);EXPECT_EQ(moved,1);
  }
}

TEST(flip_in_place_matches_coordinate_reference_all_orientations) {
  for(int w:{1,2,3,16,17})for(int h:{1,2,3,16,17})for(unsigned flags=0;flags<4;++flags){
    std::vector<std::uint32_t> p(static_cast<std::size_t>(w*h));
    for(std::size_t i=0;i<p.size();++i)p[i]=static_cast<std::uint32_t>(i);
    flip_rgba_in_place(p.data(),w,h,(flags&1)!=0,(flags&2)!=0);
    for(int y=0;y<h;++y)for(int x=0;x<w;++x) {
      const int sx=(flags&1)?w-1-x:x,sy=(flags&2)?h-1-y:y;
      EXPECT_EQ(p[static_cast<std::size_t>(y*w+x)],static_cast<std::uint32_t>(sy*w+sx));
    }
  }
}
