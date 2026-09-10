"""Pinned real language loader/name display; no private assets or device claims."""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import zlib

import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from handheld_ui import transform, transform_chinese, transform_staff_name


class ChineseCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp = tempfile.TemporaryDirectory(prefix='cth-chinese-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.source = Path(cls.temp.name)
        fixture = json.loads((ROOT/'tests/fixtures/localization_upstream.json').read_text())
        assert fixture['commit'] == '56bd5d00f76331c7f76d7b696726a7926303ca0c'
        cls.original = json.loads(zlib.decompress(base64.b64decode(fixture['sources_zlib_base64'])))
        for name, text in cls.original.items():
            assert hashlib.sha256(text.encode()).hexdigest() == fixture['sha256'][name]
            if name == 'languages/simplified_chinese.lua':
                text = transform_chinese(text)
            if name == 'staff_profile.lua':
                text = transform_staff_name(text)
            target = cls.source/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

    def run_lua(self, body):
        # Execute the full pinned Strings module and Strings:load/_loadPrivate.
        # Original LANG.DAT is intentionally absent: no-op original_strings is
        # the only catalogue seam. All modern English additions and Chinese
        # content run with real shadow tables, merge semantics and read guards.
        script = 'local source='+repr(str(self.source))+'\n'+r'''
package.preload.lfs=function()return {}end
package.preload.TH=function()return {}end
strict_declare_global=function()end;destrict=function(f)return f end
permanent=function(_,v)if v~=nil then return v end;return function(x)return x end end
dofile(source..'/class.lua')
dofile(source..'/strings.lua')
local app={is_3ds=true,config={language='chinese (simplified)'},good_install_folder=true}
local strings=Strings(app)
strings.language_to_chunk={};strings.language_chunks={};strings.languages_with_arabic_numerals={}
for _,name in ipairs({'english','simplified_chinese'})do
 local path=source..'/languages/'..name..'.lua'
 local chunk=function(env)return assert(loadfile(path,'t',env))()end
 strings.language_to_chunk[name]=chunk;strings.language_chunks[chunk]=path
end
strings.language_to_chunk.original_strings=function()end
strings.language_to_chunk['chinese (simplified)']=strings.language_to_chunk.simplified_chinese
local errors={};print=function(s)errors[#errors+1]=s end
local en=strings:load('english',true)
local zh=strings:load('Chinese (simplified)',true)
assert(#errors==0,table.concat(errors,'\n'))
''' + body
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_real_loader_missing_english_and_placeholder_contract(self):
        self.run_lua(r'''
local permitted={['vip_names.6']=true} -- original fictional proper name
local untranslated={}
local checked=0
local function scan(eng,chi,path)
 for key,value in pairs(eng)do
  local p=path=='' and tostring(key)or(path..'.'..tostring(key))
  if type(value)=='table'then scan(value,chi and chi[key],p)
  elseif type(value)=='string'and value:match('[A-Za-z][A-Za-z]')then
   local translated=chi and chi[key]
   if (translated==nil or translated==value)and not permitted[p] then untranslated[#untranslated+1]=p end
   if type(translated)=='string'and translated~=value then
    -- Numbered placeholders may be reordered. Preserve printf argument order.
    checked=checked+1
   end
  end
 end
end
scan(en,zh,'')
table.sort(untranslated)
assert(#untranslated==0,table.concat(untranslated,'\n'))
assert(checked>250)
assert(zh.adviser.warnings.cannot_afford_machine=='更换%2%至少需要银行存款 $%1%！')
assert(en.adviser.warnings.cannot_afford_machine:match('You need at least'))
assert(zh.tooltip.staff_list.close~=nil) -- neighbouring upstream entries survive merges
assert(zh.subtitles.emerg007=='员工请注意：大头症病人即将抵达。')
assert(en.subtitles.emerg007:match('Bloaty Head'))
''')

    def test_addition_keys_and_formats_against_real_english(self):
        # Load only the addition through the same language-table merge rules.
        self.run_lua('local additions='+repr(str(ROOT/'resources/translations/simplified_chinese.lua'))+'\n'+r'''
local original=strings.language_to_chunk.simplified_chinese
strings.language_to_chunk.additions=function(env)return assert(loadfile(additions,'t',env))()end
strings.language_chunks[strings.language_to_chunk.additions]=additions
local translated=strings:load('additions',true)
local count=0
local function tokens(s)
 local numbered={};s=s:gsub('%%(%d+)%%',function(n)numbered[#numbered+1]=n;return ''end)
 table.sort(numbered);s=s:gsub('%%%%','')
 local ordered={};for v in s:gmatch('%%[cdeEfgGiouXxsq]')do ordered[#ordered+1]=v end
 return table.concat(numbered,',')..'|'..table.concat(ordered,',')
end
local function scan(t,e,p)
 for k,v in pairs(t)do
  local path=p..'.'..k
  assert(e and e[k]~=nil,'unknown translation key '..path)
  if type(v)=='table'then scan(v,e[k],path)
  else assert(type(e[k])=='string',path);assert(tokens(v)==tokens(e[k]),'format mismatch '..path)
   assert(utf8.len(v),'invalid UTF-8 '..path);count=count+1
  end
 end
end
scan(translated,en,'');assert(count==313,count)
''')

    def test_old_and_new_staff_names_preserve_fields_and_language_switch(self):
        self.run_lua(r'''
_S=zh;dofile(source..'/staff_profile.lua')
local world={app=app}
local random=math.random;math.random=function()error('display used RNG')end
for _,initial in ipairs({'尔','伯','奇','桑'})do
 local p=setmetatable({world=world,initial=initial,name='派特克利夫',name_seed=39,name_lang='Chinese (simplified)'},StaffProfile._metatable)
 local fields={};for k,v in pairs(p)do fields[k]=v end
 for _,language in ipairs({'chinese (simplified)','Chinese (simplified)','cHiNeSe (SiMpLiFiEd)','简体中文','ZH(S)'})do
  app.config.language=language
  assert(p:getFullName()=='派特克利夫') -- restored profile, no new-field requirement
  assert(app.config.language==language) -- UI spelling is never written back
 end
 app.config.language='English';assert(p:getFullName()==initial..'. 派特克利夫')
 app.config.language='Chinese (simplified)'
 app.is_3ds=false;assert(p:getFullName()==initial..'. 派特克利夫');app.is_3ds=true
 for k,v in pairs(p)do assert(fields[k]==v)end
 for k,v in pairs(fields)do assert(p[k]==v)end
end
local p=setmetatable({world=world,initial='A',name='Smith'},StaffProfile._metatable)
assert(p:getFullName()=='A. Smith')
math.random=random
local fresh=StaffProfile(world,'Doctor','医生');fresh.initial='尔';fresh.name='派特克利夫'
assert(fresh:getFullName()=='派特克利夫')
-- Worst pinned compound name fits the unchanged 142-pixel list column at
-- the selected 14-pixel body size even at a conservative 14px/CJK advance.
local longest=0
for _,a in pairs(zh.humanoid_name_starts)do for _,b in pairs(zh.humanoid_name_ends)do
 longest=math.max(longest,assert(utf8.len(a..b)))
end end
assert(longest*14<=142,longest)
local list=assert(io.open(source..'/dialogs/fullscreen/staff_management.lua')):read('*a')
assert(list:find('staff.profile:getFullName()',1,true))
''')

    def test_transform_repeated_generation_and_media_labels(self):
        original = self.original['languages/simplified_chinese.lua']
        transformed = transform_chinese(original)
        self.assertEqual(transform_chinese(transformed), transformed)
        profile = transform_staff_name(self.original['staff_profile.lua'])
        self.assertEqual(transform_staff_name(profile), profile)
        test_lua_runtime.LuaRuntimeTests().run_lua(r'''
local m=require('3ds.media');local app={config={language='chinese (simplified)',speech_language='fr'}}
-- Captured device config uses lowercase; the previous predicate fails here.
assert(not (app.config.language=='Chinese (simplified)'))
for _,language in ipairs({'chinese (simplified)','Chinese (simplified)','cHiNeSe (SiMpLiFiEd)','简体中文','CHI(S)'})do
 app.config.language=language
 assert(m.voiceLabel(app)=='法语');assert(m.uiText(app,'voice_language')=='播报语音')
 assert(app.config.language==language)
end
app.config.language='English';assert(m.voiceLabel(app)=='French');assert(m.uiText(app,'voice_language')=='Voice language')
''')
        # Upgrade previously generated mixed-case-only name and save-slot
        # consumers as well as clean upstream; repeated application is exact.
        old_profile=profile.replace('require("3ds.media").isChinese(app)',
                                    'app.config.language == "Chinese (simplified)"')
        self.assertEqual(transform_staff_name(old_profile),profile)
        save_original=(ROOT/'tests/fixtures/save_game.lua.pinned').read_text()
        save=transform(save_original)
        self.assertEqual(transform(save),save)
        old_save=save.replace('(require("3ds.media").isChinese(ui.app) and "存档槽 " or "Save slot ")',
            '((ui.app.config and ui.app.config.language == "Chinese (simplified)") and "存档槽 " or "Save slot ")')
        self.assertEqual(transform(old_save),save)
        expression=re.search(r':setLabel\((\(require\("3ds.media"\).*?slot)\)',save).group(1)
        test_lua_runtime.LuaRuntimeTests().run_lua('local label=function(ui,slot)return '+expression+' end\n'+r'''
local ui={app={config={language='chinese (simplified)'}}}
for _,language in ipairs({'chinese (simplified)','Chinese (simplified)','cHiNeSe (SiMpLiFiEd)'})do
 ui.app.config.language=language
 for slot=1,3 do assert(label(ui,slot)=='存档槽 '..slot)end
 assert(ui.app.config.language==language)
end
ui.app.config.language='English';for slot=1,3 do assert(label(ui,slot)=='Save slot '..slot)end
''')


if __name__ == '__main__':
    unittest.main()
