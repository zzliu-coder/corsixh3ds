"""Real assembled entry points, bounded lifetimes and private-media-free tests."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from test_playable_path import generated_sources
import test_lua_runtime as lua_tests

ROOT=Path(__file__).resolve().parents[2]

def make_outline_font(path, chars):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    chars=set(map(ord,chars))|set(range(32,127))
    names=['.notdef']+['u%x'%c for c in sorted(chars)]
    fb=FontBuilder(1000,isTTF=True);fb.setupGlyphOrder(names)
    fb.setupCharacterMap({c:'u%x'%c for c in chars})
    glyphs={}
    for name in names:
        p=TTGlyphPen(None);p.moveTo((50,0));p.lineTo((50,700));p.lineTo((550,700));p.lineTo((550,0));p.closePath()
        glyphs[name]=p.glyph()
    fb.setupGlyf(glyphs);fb.setupHorizontalMetrics({n:(600,50) for n in names})
    fb.setupHorizontalHeader(ascent=800,descent=-200)
    fb.setupNameTable({'familyName':'TestOutline','styleName':'Regular','uniqueFontIdentifier':'TestOutline','fullName':'TestOutline','psName':'TestOutline'})
    fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    fb.setupPost();fb.setupMaxp();fb.save(str(path))

class MediaTests(unittest.TestCase):
    def strict_runtime(self):
        # Exact upstream global-variable policy, not the independent Lua C API
        # checker. Do not supply a global IS_3DS that the game never declares.
        path=ROOT/'tests/fixtures/strict.lua.pinned'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            'f8619b09e2f2056c6afacd57288f5136c2f10afa5cbc080cc9b5d0c74f6fb10d')
        return 'dofile('+repr(str(path))+')\nassert(rawget(_G,"IS_3DS")==nil)\n'

    def test_actual_graphics_font_entry_under_upstream_strict(self):
        for platform in ('true','false','absent'):
            with self.subTest(platform=platform):
                script='local platform='+('nil' if platform=='absent' else platform)+'\n'+r'''
local allocations=0
package.preload.th3ds=function()
 if platform==nil then error('platform module unavailable')end
 return {is_platform=function()return platform end}
end
package.preload.TH=function()return {freetype_font=function()
 allocations=allocations+1
 return {setFace=function(self,data)assert(data=='outline')end,
   setFontOptions=function(self,sheet,options)self.options=options end,
   clearCache=function()end}
end}end
function class(name)_G[name]={};return function()end end
'''
                script+='package.loaded["3ds.media"]=dofile('+repr(str(ROOT/'lua/3ds/media.lua'))+')\n'
                script+='dofile('+repr(str(self.upstream/'CorsixTH/Lua/graphics.lua'))+')\n'
                script+=self.strict_runtime()+r'''
local gfx=setmetatable({app={config={ui_scale=1}},th_charset=1,ttf_font_data='outline',
 cache={language_fonts={}},reload_functions_last={},load_info={}},{__index=Graphics})
local sheet,options={},{}
local font=gfx:loadLanguageFont('unicode',sheet,options)._proxy
assert(allocations==1 and options.ttf_height==nil and options.ttf_width==nil)
assert(font.options.ttf_height==(platform and 14 or nil))
assert(font.options.ttf_width==(platform and 0 or nil))
assert(gfx:loadLanguageFont('unicode',sheet,{})._proxy==font and allocations==1)
local heading=gfx:loadLanguageFont('unicode',sheet,{ttf_height=20})._proxy
assert(heading~=font and heading.options.ttf_height==20 and allocations==2)
assert(gfx:loadLanguageFont('unicode',sheet,{ttf_height=20})._proxy==heading)
assert(allocations==2 and rawget(_G,'IS_3DS')==nil)
'''
                lua_tests.LuaRuntimeTests().run_lua(script)

    def test_actual_sound_window_and_persistent_voice_setting(self):
        script=r'''
local function panel()
 local p={}
 function p:setLabel(v)self.label=v;return self end
 function p:setTooltip()return self end
 function p:setVisible(v)self.visible=v;return self end
 function p:setAutoClip()return self end
 function p:setToggleState(v)self.toggled=v;return self end
 function p:enable(v)self.enabled=v;return self end
 function p:makeButton()self.button=panel();return self.button end
 p.makeToggleButton=p.makeButton
 return p
end
UIResizable={}
function UIResizable:UIResizable(ui)self.ui=ui end
function UIResizable:setDefaultPosition()end
function UIResizable:addBevelPanel()return panel()end
function UIResizable:addWindow(w)self.last_window=w end
function class(name)return function(base)_G[name]=setmetatable({},{__index=base})end end
local function strings()return setmetatable({},{__index=function(_,key)return tostring(key)end})end
_S={audio_window=strings(),customise_window=strings(),menu_options_volume=strings(),
    tooltip={audio_window=strings()}}
Colours={}
UIDropdown=function(...)return {close=function(self)self.closed=true end}end
'''
        script+='package.loaded["3ds.media"]=dofile('+repr(str(ROOT/'lua/3ds/media.lua'))+')\n'
        script+='dofile('+repr(str(self.upstream/'CorsixTH/Lua/dialogs/resizables/sound_setting.lua'))+')\n'
        script+=self.strict_runtime()
        script+=r'''
local installed=false
package.loaded.lfs={attributes=function(path)if installed and path=="ROOT/Voices/Sound-CN.dat"then return "file"end end}
local app={is_3ds=true,config={audio=true,play_sounds=true,play_announcements=true,play_music=true,
 sound_volume=.5,announcement_volume=.5,music_volume=.5,language="Chinese (simplified)"},
 gfx={loadMenuFont=function()return {}end},
 getFullPath=function()return "ROOT/"end,
 fs={_getFilePath=function(_,path)if path=="Sound/Data/Sound-0.dat"then return path end end},
 audio={getMidiApiList=function()return {}end,getMidiPortList=function()return {}end,
 initSpeech=function()return true end},saveConfig=function()end}
local ui={app=app}
local function create(mode)
 local w=setmetatable({},{__index=UISoundSettings});w:UISoundSettings(ui,mode)
 w:closeAllDropdowns()
 for _,b in ipairs{w.sound_volume_button,w.announcement_volume_button,w.music_volume_button}do
  w:dropdownVolume(true,b);assert(b.toggled and w.volume_dropdown)
  local old=w.volume_dropdown;w:closeAllDropdowns();assert(old.closed and not b.toggled)
 end
 return w
end
local missing=create("menu");assert(not missing.voice_panel.button.enabled)
assert(missing.voice_panel.label:find("missing"))
installed=true;local available=create("game");assert(available.voice_panel.button.enabled)
available:buttonVoiceLanguage();assert(app.config.speech_language=="zh")
available:buttonVoiceLanguage();assert(app.config.speech_language=="en")
-- Hidden MIDI callbacks are harmless on handheld; the desktop path still
-- constructs and opens the original controls without a platform global.
available:dropdownMidiApi(true);available:dropdownMidiPort(true)
assert(not available.midi_api_dropdown and not available.midi_port_dropdown)
app.is_3ds=nil
for _,mode in ipairs{'menu','game'}do
 local desktop=create(mode);assert(not desktop.voice_panel and desktop.midi_api_button)
 desktop:dropdownMidiApi(true);assert(desktop.midi_api_dropdown)
 desktop:dropdownMidiPort(true);assert(desktop.midi_port_dropdown and not desktop.midi_api_dropdown)
 desktop:closeAllDropdowns();assert(not desktop.midi_port_dropdown)
end
assert(rawget(_G,'IS_3DS')==nil)
'''
        lua_tests.LuaRuntimeTests().run_lua(script)
        config=(self.upstream/'CorsixTH/Lua/config_finder.lua').read_text()
        self.assertIn('speech_language = [[en]]',config)
        self.assertEqual(config.count("param(config_values, 'speech_language')"),1)

    def test_independent_voice_selection_and_failed_switch_rollback(self):
        lua_tests.LuaRuntimeTests().run_lua('local M=dofile('+repr(str(ROOT/'lua/3ds/media.lua'))+')\n'+r'''
local installed=false
package.loaded.lfs={attributes=function(path)if installed and path=="ROOT/Voices/Sound-CN.dat"then return "file"end end}
local app={config={language='Chinese (simplified)'},getFullPath=function()return "ROOT/"end,
 fs={_getFilePath=function(_,path)if path=="Sound/Data/Sound-0.dat"then return path end end}}
local changes,writes=0,0
app.saveConfig=function()writes=writes+1 end
app.audio={initSpeech=function(self)changes=changes+1;self.bank=M.speechFile(app);return true end}
assert(M.speechFile(app,'Sound-1.dat')=='Sound-EN.dat')
assert(not M.setSpeech(app,'zh') and changes==0 and writes==0)
installed=true;assert(M.setSpeech(app,'zh') and app.audio.bank=='Sound-CN.dat')
app.config.language='English';assert(M.speechFile(app)=='Sound-CN.dat')
assert(M.setSpeech(app,'en') and app.audio.bank=='Sound-EN.dat')
app.audio.initSpeech=function()error('injected bad sound archive')end
assert(not M.setSpeech(app,'zh') and app.config.speech_language=='en')
package.loaded.lfs.attributes=function(path)
 for _,v in ipairs(M.voices)do if path=='ROOT/Voices/'..v.file then return 'file' end end
end
app.audio.initSpeech=function()return true end
app.config.speech_language='zh'
local ui_language=app.config.language
for _,code in ipairs{'en','fr','de','it','es','sv','zh'}do
 assert(M.cycleSpeech(app) and app.config.speech_language==code)
 assert(app.config.language==ui_language)
 assert(M.speechPath(app,M.speechFile(app)):match('^ROOT/Voices/'))
end
local options={ttf_color=123};local body=M.fontOptions(options)
assert(body.ttf_height==14 and body.ttf_width==0 and options.ttf_height==nil)
local heading=M.fontOptions({ttf_height=20});assert(heading.ttf_height==20)
''')
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-media-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory=Path(cls.temp.name)
        cls.upstream=generated_sources(cls.directory)
        lua_tests.LuaRuntimeTests.setUpClass()

    def test_config_and_music_ownership(self):
        lua_tests.LuaRuntimeTests().run_lua('local M=dofile('+repr(str(ROOT/'lua/3ds/media.lua'))+')\n'+r'''
local config={language='简体中文',play_music=true}
M.configure(config,'ROOT/',function(path)
 if path=='ROOT/CorsixTH-SC-subset.ttf' then return 'file' end
 if path=='ROOT/Music' then return 'directory' end
end)
assert(config.language=='简体中文' and config.play_music)
assert(config.unicode_font=='ROOT/CorsixTH-SC-subset.ttf' and config.audio_music=='ROOT/Music')
M.configure(config,'ROOT/',function()end)
assert(not config.play_music and config.audio_music==nil)
local live,loads,stops,playing=0,0,0,nil
local api={}
function api.loadMusicFile(path)
 if path=='bad.wav' then return nil,'injected file failure' end
 assert(live==0);live=live+1;loads=loads+1;return {file=path}
end
function api.stopMusic()stops=stops+1;playing=nil end
function api.freeMusic(m)assert(not m.closed);m.closed=true;live=live-1 end
function api.playMusic(m)if m.file=='fail-play.wav' then return nil,'injected play failure' end;playing=m;return true end
function api.setMusicVolume(v)assert(v>=0 and v<=1)end
local a={app={config={play_music=true,music_volume=.5}},background_playlist={
 {filename_music='a.wav'}, {filename_music='b.wav'}, {filename_music='bad.wav'},
 {filename_music='fail-play.wav'}, {filename='old.xmi'}},notifyJukebox=function()end}
for i=1,40 do assert(M.play(a,1+(i%2),api));assert(live==1 and a.background_music==playing) end
a.background_paused=true;a.old_bg_music_volume=.4
M.release(a,api);assert(live==0 and not a.background_music and not a.background_paused)
assert(a.app.config.music_volume==.4 and a.old_bg_music_volume==nil)
for i=3,5 do assert(M.play(a,i,api)==false);assert(live==0 and a.background_playlist[i].enabled==false) end
a.app.config.play_music=false;local before=loads;M.play(a,1,api);assert(loads==before)
M.release(a,api);assert(live==0)
''')
        app=(self.upstream/'CorsixTH/Lua/app.lua').read_text()
        audio=(self.upstream/'CorsixTH/Lua/audio.lua').read_text()
        native=(self.upstream/'CorsixTH/Src/sdl_audio.cpp').read_text()
        self.assertNotIn('self.config.language="English"',app)
        self.assertNotIn('self.config.play_music = false',app)
        self.assertIn('require("3ds.media").play(self, index, SDL.audio, TH3DS)',audio)
        self.assertIn('Mix_LoadMUSType_RW(stream, MUS_WAV, 1)',native)
        self.assertIn('SDL_FlushEvent(SDL_USEREVENT_MUSIC_OVER)',native)
        self.assertLess(native.index('music* owner = luaT_stdnew<music>',native.index('int l_load_music_file')),
                        native.index('SDL_RWops* stream = SDL_RWFromFile'))

    def test_actual_freetype_layout_lifetime_and_cache(self):
        root=self.upstream/'CorsixTH/Src'
        header=(root/'th_gfx_font.h').read_text().replace('#include "th_gfx_sdl.h"','').replace('#include "config.h"','')
        strings_header=(root/'th_strings.h').read_text().replace('#include "config.h"','')
        strings=(root/'th_strings.cpp').read_text().replace('#include "config.h"','').replace('#include "th_strings.h"','')
        font=(root/'th_gfx_font.cpp').read_text()
        font=font[font.index('FT_Library freetype_font::'):]
        backend=(root/'th_gfx_sdl.cpp').read_text()
        backend=backend[backend.index('bool freetype_font::is_monochrome()'):]
        code=(ROOT/'tests/runtime_support/font_cache_probe.cpp').read_text()
        for key,value in [('HEADER',header),('STRINGS_HEADER',strings_header),('STRINGS',strings),('FONT',font),('BACKEND',backend)]:
            code=code.replace('// INSERT_'+key,value)
        source=self.directory/'font.cpp';source.write_text(code)
        # Use a deterministic synthetic outline font by default; private real
        # subset is an explicitly selected additional local run.
        path=os.environ.get('CTH3DS_TEST_FONT')
        if not path:
            path=str(self.directory/'synthetic.ttf')
            make_outline_font(path,'主题医院医生护士保存患者就诊与音乐')
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2','freetype2'],text=True))
        binary=self.directory/'font-probe'
        subprocess.run([shutil.which('clang++') or 'c++','-std=c++17','-O2','-fsanitize=address,undefined',
            '-fno-omit-frame-pointer','-I'+str(ROOT/'include'),str(source),*flags,'-o',str(binary)],check=True)
        result=subprocess.run([str(binary),path],text=True,capture_output=True,
            env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS real FreeType',result.stdout)
        print(result.stdout,end='')

    def test_private_media_preparation_and_bilingual_package(self):
        import wave
        from prepare_media import prepare
        from test_package_sd_script import PackageSdScriptTests
        from validate_sd_tree import validate_sd_tree, ValidationError, write_boot_contract
        with tempfile.TemporaryDirectory(prefix='cth-media-package-') as temp:
            root=Path(temp)
            fixture=PackageSdScriptTests()
            environment,game=fixture.make_environment(root)
            runtime=root/'external/CorsixTH/CorsixTH'
            language=runtime/'Lua/languages/simplified_chinese.lua'
            language.write_text('Language("简体中文", "Chinese (simplified)")\nInherit("english")\nFont("unicode")\nstaff={doctor="医生"}\n')
            # The real upstream directory also contains these static utf8
            # wrappers, even when only the Chinese closure is packaged.
            (language.parent/'french.lua').write_text('Language(utf8 "Français", "French", "fr")\nInherit("english")\n')
            (language.parent/'iberic_portuguese.lua').write_text('Language(utf8 "Português", "Portuguese", "pt")\nInherit("english")\n')
            source=root/'media';(source/'Music').mkdir(parents=True)
            make_outline_font(source/'CorsixTH-SC-subset.ttf','简体中文医生')
            with wave.open(str(source/'Music/CANDY.wav'),'wb') as wav:
                wav.setparams((1,2,22050,0,'NONE','not compressed'));wav.writeframes(bytes(4410))
            # Prepared speech remains separate from original game/Sound data.
            from media_runtime.check_voices import bank,wav as voice_wav
            (source/'Voices').mkdir()
            (source/'Voices/Sound-CN.dat').write_bytes(bank(voice_wav(140,22050,16),voice_wav(141,22050,16)))
            stage=root/'prepared'
            report=prepare(source,stage,runtime)
            self.assertEqual(report,prepare(source,stage,runtime))
            self.assertEqual(report['missing_characters'],0)
            with self.assertRaises(ValueError):prepare(source,root/'bad-track',runtime,['../CANDY.wav'])
            language.write_text(language.read_text()+'\nmissing="龘"\n')
            with self.assertRaisesRegex(ValueError,'missing required'):prepare(source,root/'missing-font',runtime)
            language.write_text(language.read_text().replace('\nmissing="龘"\n',''))
            environment['CTH3DS_DIST_DIR']=str(root/'dist')
            result=subprocess.run([str(ROOT/'scripts/package_sd.sh'),'--asset-mode','loose',
                '--language','Chinese (simplified)','--theme-hospital',str(game),'--private-media',str(stage)],
                env=environment,cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            package=root/'dist/sd-card/3ds/corsixth'
            self.assertEqual(validate_sd_tree(package)['result'],'PASS')
            self.assertIn('speech_language = "zh"',(package/'config.txt').read_text())
            self.assertTrue((package/'Voices/Sound-CN.dat').is_file())
            self.assertEqual({p.name for p in (package/'Lua/languages').glob('*.lua')},
                {'english.lua','original_strings.lua','simplified_chinese.lua'})
            (package/'Music/CANDY.wav').write_bytes(b'changed')
            with self.assertRaisesRegex(ValidationError,'private media hash'):
                write_boot_contract(package,asset_mode='loose',candidate_commit='1'*40,candidate_tree='2'*40)
            (package/'CorsixTH-SC-subset.ttf').unlink()
            with self.assertRaisesRegex(ValidationError,'required file is missing'):
                write_boot_contract(package,asset_mode='loose',candidate_commit='1'*40,candidate_tree='2'*40)

    def test_actual_sdl_mixer_streams_and_releases(self):
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2','SDL2_mixer'],text=True))
        binary=self.directory/'music-probe'
        subprocess.run([shutil.which('clang++') or 'c++','-std=c++17','-O2','-fsanitize=address,undefined',
            '-fno-omit-frame-pointer',str(ROOT/'tests/runtime_support/music_stream_probe.cpp'),*flags,'-o',str(binary)],check=True)
        result=subprocess.run([str(binary)],text=True,capture_output=True,
            env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS real SDL_mixer',result.stdout)
        print(result.stdout,end='')

if __name__=='__main__':unittest.main()
