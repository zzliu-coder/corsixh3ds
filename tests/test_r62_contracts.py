"""R62 source ownership, unchanged staff output and safe picture preparation."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from support.pinned_upstream import generated_sources, original_sources
from test_playable_path import function_body
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

def method(text, signature):
    begin=text.index(signature)
    return text[begin:text.index('\nend',begin)+4]

class R62Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r62-')
        cls.directory=Path(cls.temp.name)
        cls.generated=generated_sources(cls.directory)
        cls.original=original_sources(cls.directory/'reference')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_fallback_raw_exception_preserves_old_image_and_releases_conversion(self):
        text=(self.generated/'CorsixTH/Src/th_gfx_sdl.cpp').read_text()
        code=r'''
#include <memory>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <stdexcept>
#include <cassert>
static std::size_t live;
void* operator new[](std::size_t n){auto* p=std::malloc(n);if(!p)throw std::bad_alloc();++live;return p;}
void operator delete[](void* p)noexcept{if(p){--live;std::free(p);}}
void operator delete[](void* p,std::size_t)noexcept{operator delete[](p);}
struct SDL_Texture{};
static SDL_Texture first,second;
static unsigned destroyed;
static bool fail;
void SDL_DestroyTexture(SDL_Texture* p){assert(p==&first||p==&second);++destroyed;}
struct palette{};
struct render_target{
 SDL_Texture* create_palettized_texture(int w,int h,const uint8_t*,palette*,uint32_t){
   assert(w==640&&h==480);if(fail)throw std::bad_alloc();return destroyed?&second:&first;
 }
};
constexpr uint32_t thdf_alt32_plain=0;
struct raw_bitmap{
 SDL_Texture* texture{};palette* bitmap_palette{};int width{},height{};render_target* target{};
 void load_from_th_file(const uint8_t*,size_t,int,render_target*,uint32_t);
};
'''
        code += function_body(text,'uint8_t* convertLegacySprite(')+'\n'
        code += function_body(text,'void raw_bitmap::load_from_th_file(')+'\n'
        code += r'''
int main(){static uint8_t data[640*480]{};palette pal;raw_bitmap image;render_target target;
 image.bitmap_palette=&pal;image.load_from_th_file(data,sizeof(data),640,&target,0);
 assert(live==0&&image.texture==&first&&destroyed==0);
 fail=true;for(int n=0;n<20;++n){
   try{image.load_from_th_file(data,sizeof(data),640,&target,0);assert(false);}catch(const std::bad_alloc&){}
   assert(live==0&&image.texture==&first&&image.width==640&&destroyed==0);
 }
 fail=false;image.load_from_th_file(data,sizeof(data),640,&target,0);
 assert(live==0&&destroyed==1);SDL_DestroyTexture(image.texture);assert(destroyed==2);
 std::puts("PASS actual raw loader: 20 failed replacements, zero retained conversion blocks");
}
'''
        source=self.directory/'raw.cpp';source.write_text(code)
        binary=self.directory/'raw'
        subprocess.run([shutil.which('clang++') or 'g++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
            '-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
        result=subprocess.run([str(binary)],capture_output=True,text=True,env=dict(os.environ,
            ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout,end='')

    def test_warm_cache_weak_owners_and_window_failure_before_mutation(self):
        graphics=(self.generated/'CorsixTH/Lua/graphics.lua').read_text()
        bottom=(self.generated/'CorsixTH/Lua/dialogs/bottom_panel.lua').read_text()
        script='Graphics={}\n'+method(graphics,'function Graphics:_retainRaw(')+'\n'
        script+='UIBottomPanel={}\n'+method(bottom,'function UIBottomPanel:addDialog(')+r'''
local gfx=setmetatable({cache={raw=setmetatable({},{__mode='v'})}},{__index=Graphics})
local alive=setmetatable({},{__mode='v'})
local visible={}
for i=1,10 do local bitmap={};gfx.cache.raw[tostring(i)]=bitmap;alive[i]=bitmap
 gfx:_retainRaw(tostring(i),bitmap);if i==1 then visible[1]=bitmap end
end
collectgarbage('collect');assert(alive[1] and alive[8] and alive[9] and alive[10])
for i=2,7 do assert(not alive[i])end
assert(#gfx.raw_recent==3)
gfx:_retainRaw('8',alive[8]);assert(#gfx.raw_recent==3 and gfx.raw_recent[3].name=='8')
visible={};collectgarbage('collect');assert(not alive[1])
local mutations,prepared,constructed,notices=0,false,false,0
TH3DS={set_notice=function()notices=notices+1 end}
UIEditRoom={};UIConfirmDialog=function()error('unused')end
local panel=setmetatable({ui={app={gfx=gfx,_3ds={native=TH3DS}}},updateButtonStates=function()end},{__index=UIBottomPanel})
function panel.ui:getWindow()return nil end
function panel.ui:setEditRoom()assert(prepared);mutations=mutations+1 end
function panel.ui:addWindow(w)assert(prepared and constructed and w.marker)end
function gfx:loadRaw()error('injected resource allocation')end
assert(panel:addDialog('UIResearch')==false and mutations==0 and notices==1)
function gfx:loadRaw(name)assert(name=='Res01V');prepared=true;return {}end
UIResearch=function()assert(prepared);constructed=true;return{marker=true}end
panel:addDialog('UIResearch');assert(mutations==1 and constructed)
print('PASS weak visible owners, bounded warm set, failure before UI mutation, retry publication')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_actual_staff_information_equal_and_copy_on_change(self):
        scripts=[]
        for label,root in [('before',self.original),('after',self.generated)]:
            text=(root/'CorsixTH/Lua/entities/humanoids/staff.lua').read_text()
            scripts.append('Staff={}\n'+method(text,'function Staff:updateDynamicInfo(')+
                '\nlocal '+label+'=Staff.updateDynamicInfo')
        script='\n'.join(scripts)+r'''
class={is=function(s)return s.receptionist end};Receptionist={}
_S={dynamic_info={staff={tiredness='TIRED'}}}
local writes=0
local function staff(receptionist)
 return {receptionist=receptionist,profile={profession='doctor'},hospital={policies={goto_staffroom=0.8}},
  getAttribute=function(self)return self.fatigue or 0 end,
  setDynamicInfo=function(self,k,v)writes=writes+1;self.dynamic_info=self.dynamic_info or {};self.dynamic_info[k]=v end}
end
for _,receptionist in ipairs{false,true}do
 local a,b=staff(receptionist),staff(receptionist)
 for n=1,120 do
  local change=n%7==0
  for _,s in ipairs{a,b}do
   s.dynamic_text=change and 'NEW' or 'OLD';s.fatigue=n/120
   s.hospital.policies.goto_staffroom=n<60 and 0.8 or 0.9
  end
  before(a);after(b)
  local aa,bb=a.dynamic_info,b.dynamic_info
  assert(aa.progress==bb.progress and aa.dividers[1]==bb.dividers[1])
  for i=1,3 do assert(aa.text[i]==bb.text[i])end
 end
 local old=b.dynamic_info.text;local divider=b.dynamic_info.dividers
 after(b);assert(old==b.dynamic_info.text and divider==b.dynamic_info.dividers)
 b.dynamic_text='REPLACED';after(b);assert(old~=b.dynamic_info.text and old[2]~='REPLACED')
end
print('PASS actual staff information values and snapshot ownership')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)
