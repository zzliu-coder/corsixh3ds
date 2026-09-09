// Included inside the real production-backend delayed-queue probe main.
// Fresh atlas for each scenario; warm=3 fills every page before floor ownership.
for(int warm:{0,3}){
  gpu_shutdown();assert(gpu_initialize());
  const unsigned fixed_allocations=allocations;
  const bool sampling=std::getenv("R67_SAMPLE")!=nullptr;
  if(sampling)gpu_submit_sample_begin(100);
  std::vector<SDL_Texture*> textures;
  assert(gpu_begin());assert(gpu_clear(0xff183048U));
  for(int i=0;i<warm;++i){
    std::vector<u32> data(512*512,0xff010203U+unsigned(i));
    auto* t=gpu_image_create(renderer,512,512,data.data());assert(t);textures.push_back(t);
    draw(t,{0,0,512,512},{float(i*30),0,30,30},0);
  }
  // First nonfloor occupies a partial page; first floor prefers a spare page.
  std::vector<u32> wall(73*91,0x90404040U);
  auto* wall_tex=gpu_image_create(renderer,73,91,wall.data());assert(wall_tex);
  textures.push_back(wall_tex);draw(wall_tex,{0,0,73,91},{0,0,73,91},0);
  for(int i=0;i<32;++i){
    const int w=97+(i%4)*61,h=83+(i%3)*67;
    std::vector<std::uint8_t> data(w*h);
    for(int j=0;j<w*h;++j)data[j]=static_cast<std::uint8_t>(j+i*19);
    auto* t=gpu_image_create_indexed(renderer,w,h,data.data(),palette,i&1,i&2);
    assert(t);textures.push_back(t);
    {
      GpuSubmitFloorScope floor;
      SDL_Rect scissor{3,5,620,460};gpu_clip(&scissor);
      draw(t,{0,0,w,h},{float((i*37)%420),float((i*29)%300),float(w),float(h)},i&3);
      // Adjacent transparent shadow belongs to exactly the same floor pass.
      draw(wall_tex,{0,0,73,91},{float((i*37)%420+4),float((i*29)%300+6),73,91},i&3);
    }
    gpu_clip(nullptr);
    draw(wall_tex,{0,0,73,91},{float(i*11),100,73,91},(i+1)&3);
  }
  // Hit old pieces after multi-page overflow to exercise generation rebuilds.
  {GpuSubmitFloorScope floor;
    for(int i=0;i<12;++i){
      auto* t=textures[textures.size()-32+unsigned(i)];
      int w=0,h=0;SDL_QueryTexture(t,nullptr,nullptr,&w,&h);
      draw(t,{0,0,w,h},{float(i*21),120,float(w),float(h)},i&3);
    }
  }
  assert(gpu_top({100,80,400,240}));assert(gpu_bottom({100,80,400,240},nullptr,0));
  gpu_quiesce();assert(gpu_read_pixels(out));
  // Read all canvas/LCD pixels as well as the per-paint ordered trace.
  for(unsigned i=0;i<640*480;++i)r67_hash(r67_pixels,static_cast<u32*>(out->pixels)[i]);
  for(const auto& screen:lcd)for(auto byte:screen)r67_hash(r67_pixels,byte);
  assert(allocations==fixed_allocations); // zero extra GPU textures/targets
  gpu_submit_sample_end(200,true);gpu_submit_sample_log();
  for(auto* t:textures)gpu_image_destroy(t);
  // Scope ownership must work with sampling disabled and across sample begin/end.
  gpu_submit_floor_begin();gpu_submit_sample_begin(300);gpu_submit_sample_end(301,true);
  gpu_submit_floor_end();
  gpu_submit_sample_log();
}
std::printf("R67 pixels=%llu layout=%llu\n",r67_pixels,r67_layout);
