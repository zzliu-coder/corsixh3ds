"""Narrow runner entry and private write routes; independent idempotent patch."""
from .common import Change, IntegrationError

def patch_runner_adapter(root):
    edits = {
        'CorsixTH/Lua/config_finder.lua': [
            ('local function save_config(path, values)', '''local function save_config(path, values)
  local ok,native=pcall(require,"th3ds")
  local run=ok and native.runner_context and native.runner_context()
  if run then
    local stream=assert(io.open(run.root.."save/config.txt","w"))
    local written,err=stream:write(config_contents(values))
    local closed,close_err=stream:close()
    assert(written,err);assert(closed,close_err);return true
  end'''),
            ('local function load_hotkeys(path, res)', '''local function load_hotkeys(path, res)
  local ok,native=pcall(require,"th3ds")
  local run=ok and native.runner_context and native.runner_context()
  if run then path=run.root.."save/hotkeys.txt" end'''),
            ('local function save_hotkeys(path, values)', '''local function save_hotkeys(path, values)
  local ok,native=pcall(require,"th3ds")
  local run=ok and native.runner_context and native.runner_context()
  if run then
    local stream=assert(io.open(run.root.."save/hotkeys.txt","w"))
    local written,err=stream:write(hotkeys_contents(values))
    local closed,close_err=stream:close()
    assert(written,err);assert(closed,close_err);return true
  end'''),
            ('local function load_config(path, res)', '''local function load_config(path, res)
  local ok,native=pcall(require,"th3ds")
  local run=ok and native.runner_context and native.runner_context()
  if run then path=run.root.."save/config.txt" end''')],
        'CorsixTH/SrcUnshared/main.cpp': [
            ('int main(int argc, char** argv) {', '''int main(int argc, char** argv) {
#ifdef CORSIXTH_3DS
  const int runner_mode=cth3ds::runner_start(argc,argv);
  if(runner_mode<0)return 1;
  if(runner_mode>0)argc=1;
#endif'''),
            ('#ifdef WITH_UPDATE_CHECK\n  curl_global_cleanup();\n#endif\n  return 0;', '''#ifdef WITH_UPDATE_CHECK
  curl_global_cleanup();
#endif
#ifdef CORSIXTH_3DS
  cth3ds::runner_process_exit();
#endif
  return 0;''')],
        'CorsixTH/Lua/app.lua': [
            ('function App:getConfigPath()', '''function App:getConfigPath()
  local run=IS_3DS and TH3DS.runner_context()
  if run then return run.root.."save/config.txt" end'''),
            ('function App:initUserDirectories()', '''function App:initUserDirectories()
  local run=IS_3DS and TH3DS.runner_context()
  if run then
    self.user_level_dir=run.root.."artifacts/"
    self.user_campaign_dir=run.root.."artifacts/"
    self.user_log_dir=run.root.."artifacts/"
    return
  end'''),
            ('function App:initScreenshotsDir()', '''function App:initScreenshotsDir()
  local run=IS_3DS and TH3DS.runner_context()
  if run then self.screenshot_dir=run.root.."artifacts/";return true end'''),
            ('function App:writeToFileOrTmp(file, mode)', '''function App:writeToFileOrTmp(file, mode)
  local run=IS_3DS and TH3DS.runner_context()
  if run then
    assert(file:sub(1,#run.root)==run.root,"runner write escaped private directory")
    local stream,err=io.open(file,mode or "w")
    return stream,stream~=nil,err
  end'''),
            ('function App:initSavegameDir()', '''function App:initSavegameDir()
  local run=IS_3DS and TH3DS.runner_context()
  if run then self.savegame_dir=run.root.."save/";return true end'''),
            ('function App:saveConfig()', '''function App:saveConfig()
  local run=IS_3DS and TH3DS.runner_context()
  if run then
    require('config_finder').save_config(run.root.."save/config.txt",self.config)
    return
  end''')],
    }
    changes=[]
    for relative,pairs in edits.items():
        path=root/relative
        text=path.read_text()
        for old,new in pairs:
            if new in text: continue
            if text.count(old)!=1: raise IntegrationError('runner adapter anchor: '+relative)
            text=text.replace(old,new,1)
        if text!=path.read_text():
            path.write_text(text);changes.append(Change(relative,'runner-adapter'))
    return changes
