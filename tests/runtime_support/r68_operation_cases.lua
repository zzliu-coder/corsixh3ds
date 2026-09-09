-- Inserted into the real serializer / FILE / atomic-commit fixture.
scenario("r68-generated-stream-diagnostics-own-current-record",function()
  -- The actual pinned helper collects twice, pauses within callback and always restarts.
  local weak=setmetatable({},{__mode="k"});local finalized=0
  do local key=setmetatable({},{__gc=function()finalized=finalized+1 end});weak[key]=true end
  local token={}
  local ok,raw=pause_gc_and_use_weak_keys(function()
    assert(not collectgarbage("isrunning") and next(weak)==nil and finalized==1)
    error(token,0)
  end)
  assert(not ok and raw==token and collectgarbage("isrunning"))
  local line,observe=native.diagnostic_line,native.observe_memory
  local phases={"weak-gc-before","weak-gc-after","prepare-before","prepare-after","dump-before","permanent-before","permanent-after",
    "writer-before","writer-after","dump-after","afterSave-before","afterSave-after","close-before","close-after"}
  for _,phase in ipairs(phases)do
    local app=fresh();local operation
    native.observe_memory=function(site,current,...)
      if current==phase then operation=app._3ds.operations.current;assert(operation);error("observation failed")end
      return observe(site,current,...)
    end
    assert(app:save(target));local result=app._3ds.operations.last
    assert(result==operation and result.committed and result.ready and result.diagnostic_count==1)
    assert(app._3ds.operations.current==nil and result.parent==nil)
    assert(collectgarbage("isrunning"))
    assert(reference.load(read(target),inverse_permanents()).world.money==777)
    native.observe_memory=observe
  end
  local app=fresh();local report_record
  native.diagnostic_line=function(message)
    if message:find("save-stream:",1,true)then
      report_record=app._3ds.operations.current;assert(report_record and not report_record.committed)
      error("closed-file report failed")
    end
  end
  assert(app:save(target))
  assert(app._3ds.operations.last==report_record and report_record.committed and report_record.ready)
  assert(report_record.diagnostic_count==1 and app._3ds.operations.current==nil)
  native.diagnostic_line=line
end)

scenario("r68-generated-stream-raw-writer-and-cleanup-errors",function()
  local persist=package.loaded.persist;local writer=persist.dump_file
  local line,block=native.diagnostic_line,native.operation_block
  local tostring_calls=0
  local token=setmetatable({},{__tostring=function()tostring_calls=tostring_calls+1;error("tostring forbidden")end})
  for _,spec in ipairs({{value=false},{},{value=token},{value="native wrapper primary"}})do
    for _,cleanup_failure in ipairs({false,true})do
      local app=fresh();assert(app:save(target));local old=read(target)
      local primary=spec.value;local blocks=0
      R68AfterSave=function(map)AfterSave(map);if cleanup_failure then error(token,0)end end
      app.map.afterSave=R68AfterSave
      persist.dump_file=function(...)
        local accepted=writer(...);assert(accepted==true) -- actual native FILE writer executes first
        error(primary,0)
      end
      native.operation_block=function()blocks=blocks+1 end
      native.diagnostic_line=function()error("secondary sink")end
      local before=cleaned
      local ok,value=pcall(app.save,app,target)
      assert(not ok and read(target)==old and cleaned==before+1)
      if type(primary)=="string" then assert(value:find(primary,1,true) and value:find("stack traceback:",1,true))
      else assert(rawequal(value,primary) and type(value)==type(primary))end
      local result=app._3ds.operations.last
      assert(not result.committed and result.ready==not cleanup_failure and result.diagnostic_count>0)
      assert(blocks==(cleanup_failure and 1 or 0) and tostring_calls==0)
      assert(app._3ds.operations.current==nil and result.parent==nil)
      persist.dump_file=writer;native.diagnostic_line=line
    end
  end
  -- A successful writer with failed afterSave has a mandatory failure of its own.
  local app=fresh();assert(app:save(target));local old=read(target);local blocks=0
  R68AfterSave=function(map)AfterSave(map);error(false,0)end
  app.map.afterSave=R68AfterSave
  native.operation_block=function()blocks=blocks+1 end
  local ok,value=pcall(app.save,app,target)
  assert(not ok and value==false and blocks==1 and read(target)==old)
  assert(app._3ds.operations.last.cleanup_count==1 and not app._3ds.operations.last.ready)
  assert(not pcall(app._3ds.benchmarkTick,app._3ds))
  native.operation_block=block
end)

scenario("r68-current-restored-through-preload-and-reentrant-report",function()
  local app=fresh();assert(app:save(target))
  local observe=native.observe_memory;local load_record,preload_record
  native.observe_memory=function(site,phase,...)
    local current=app._3ds.operations.current
    if site=="reload" and phase=="before" then load_record=current end
    if site=="save" and phase=="writer-before" then
      preload_record=current;assert(current.parent==load_record)
    end
    if site=="reload" and phase=="loaded" then assert(current==load_record)end
    return observe(site,phase,...)
  end
  assert(app:load(target));assert(load_record and preload_record)
  assert(app._3ds.operations.last==load_record and load_record.parent==nil and preload_record.parent==nil)
  assert(app._3ds.operations.current==nil)
  native.observe_memory=observe
  local line=native.diagnostic_line
  native.diagnostic_line=function(message)
    if message:find("save-stream:",1,true)then app:save(target)end
  end
  assert(app:save(target)) -- nested diagnostic callback is rejected and recorded; no duplicate commit
  assert(app._3ds.operations.last.diagnostic_count==1 and app._3ds.operations.current==nil)
  native.diagnostic_line=line
  app._3ds.operations.writer=function()error(false,0)end
  local loaded,primary=app:load(target)
  assert(not loaded and primary==false and app._3ds.operations.current==nil)
end)

scenario("r68-no-adapter-generated-stream-cleanup-and-raw-error",function()
  local app=fresh();app._3ds=nil
  local persist=package.loaded.persist;local writer=persist.dump_file
  local line,block=native.diagnostic_line,native.operation_block
  native.diagnostic_line=function()error("optional direct report")end
  assert(SaveGameFile(target..".tmp"))
  local blocks=0;native.operation_block=function()blocks=blocks+1 end
  R68AfterSave=function(map)AfterSave(map);error("cleanup secondary")end
  app.map.afterSave=R68AfterSave
  persist.dump_file=function(... )assert(writer(...));error(false,0)end
  local before=cleaned;local ok,value=pcall(SaveGameFile,target..".tmp")
  assert(not ok and value==false and cleaned==before+1 and blocks==1)
  persist.dump_file=writer;native.diagnostic_line,native.operation_block=line,block
end)

scenario("r68-reader-observations-keep-real-publication",function()
  local observe=native.observe_memory
  for _,phase in ipairs({"parse-before","parse-after","afterLoad-before","afterLoad-after"})do
    local app=fresh();assert(app:save(target));app.world.money=321
    native.observe_memory=function(site,current,...)
      if site=="reload" and current==phase then error("load observation only")end
      return observe(site,current,...)
    end
    assert(app:load(target) and app.world.money==777)
    local result=app._3ds.operations.last
    assert(result.ready and result.completed and result.diagnostic_count==1 and result.parent==nil)
    assert(app._3ds.operations.current==nil)
    native.observe_memory=observe
  end
end)

scenario("r68-reader-raw-primary-survives-backup-and-report",function()
  local persist=package.loaded.persist;local reader=persist.load
  local line=native.diagnostic_line;local calls=0
  local token=setmetatable({},{__tostring=function()calls=calls+1;error("invalid tostring")end})
  for _,spec in ipairs({{value=false},{},{value=token}})do
    local app=fresh();assert(app:save(target));assert(app:save(target))
    local reads=0;local original_world=app.world
    persist.load=function(...)
      local state=reader(...);assert(state);reads=reads+1
      if reads==1 then error(spec.value,0)else error("secondary backup error",0)end
    end
    native.diagnostic_line=function()error("report secondary")end
    local accepted,primary=app:load(target)
    assert(not accepted and rawequal(primary,spec.value) and reads==2 and app.world==original_world)
    assert(app._3ds.operations.last.ready and app._3ds.operations.last.error_type==type(spec.value))
    local decoded,raw=LoadGame(read(target))
    assert(not decoded and type(raw)=="string") -- subsequent injected secondary stays a string
    persist.load=reader;native.diagnostic_line=line
  end
  assert(calls==0)
  local original_open=io.open
  for _,fault in ipairs({"read","close"})do
    for _,spec in ipairs({{value=false},{},{value=token}})do
      local app=fresh();assert(app:save(target));local data=read(target);local paths=0
      io.open=function(path,mode)
        if mode=="rb" and (path==target or path==target..".bak")then
          paths=paths+1;local primary=spec.value
          if paths>1 then primary="secondary file error"end
          return {read=function()if fault=="read" then return nil,primary end;return data end,
            close=function()if fault=="close" then return nil,primary end;return true end}
        end
        return original_open(path,mode)
      end
      local accepted,primary=app:load(target)
      io.open=original_open
      assert(not accepted and rawequal(primary,spec.value) and paths==2 and calls==0)
    end
  end
end)

scenario("r68-publication-failure-menu-facts-and-original-error",function()
  local line,block=native.diagnostic_line,native.operation_block
  local tostring_calls=0
  local token=setmetatable({},{__tostring=function()tostring_calls=tostring_calls+1;error("bad tostring")end})
  for _,mode in ipairs({"safe-menu","throws","incomplete"})do
    for _,spec in ipairs({{value=false},{},{value=token}})do
      local app=fresh();assert(app:save(target));local menus,blocked=0,0
      R68AfterLoad=function()error(spec.value,0)end;app.afterLoad=R68AfterLoad
      R68MainMenu=function(self)
        menus=menus+1
        if mode=="throws" then error("menu secondary")end
        if mode=="safe-menu" then MainMenu(self)end
      end
      app.loadMainMenu=R68MainMenu
      native.diagnostic_line=function()error("report secondary")end
      native.operation_block=function()blocked=blocked+1 end
      local accepted,primary=app:load(target);local result=app._3ds.operations.last
      assert(not accepted and rawequal(primary,spec.value) and menus==1 and result.publication_failed)
      assert(result.recovered_menu==(mode=="safe-menu") and result.ready==(mode=="safe-menu"))
      assert(blocked==(mode=="safe-menu" and 0 or 1) and tostring_calls==0)
      assert(app._3ds.operations.current==nil)
      if mode~="safe-menu" then assert(not pcall(app._3ds.benchmarkTick,app._3ds))end
      native.diagnostic_line=line
    end
  end
  -- Direct API without an adapter still blocks unsafe publication and keeps raw identity.
  local app=fresh();local data=SaveGame();app._3ds=nil
  app.afterLoad=function()error(token,0)end
  app.loadMainMenu=function()error("menu secondary")end
  local blocked=0;native.operation_block=function()blocked=blocked+1 end
  local accepted,primary=LoadGame(data)
  assert(not accepted and primary==token and blocked==1 and tostring_calls==0)
  native.diagnostic_line,native.operation_block=line,block
end)

scenario("r68-real-load-ui-and-commandline-no-second-menu",function()
  UIInformation=function(_,message)return message end
  local line,notice=native.diagnostic_line,native.set_notice
  for _,consumer in ipairs({"ui","commandline"})do
    local app=fresh();assert(app:save(target));local windows,menus=0,0
    R68AddWindow=function()windows=windows+1 end
    app.ui.app=app;app.ui.addWindow=R68AddWindow;app.video.setBlueFilterActive=Noop
    app.command_line={load="roundtrip.sav"}
    local token=setmetatable({},{__tostring=function()error("must not stringify")end})
    app._3ds.operations.reader=function()return false,token end
    app.loadMainMenu=function()menus=menus+1;error("unexpected extra menu")end
    native.diagnostic_line=function()error("sink unavailable")end
    local function invoke()
      if consumer=="ui" then return UILoadGame.choiceMade({ui=app.ui},target)end
      return R68CommandlineLoad(app)
    end
    assert(pcall(invoke) and windows==1 and menus==0 and app._3ds.operations.last.reported)
    -- A later implementation throwing the same object cannot borrow old reported=true.
    app.load=function()error(token,0)end
    assert(pcall(invoke) and windows==2 and menus==0)
    native.diagnostic_line=line
  end
  native.set_notice=notice
end)

scenario("r68-committed-save-survives-diagnostics",function()
  local app=fresh();assert(app:save(target));local old=read(target)
  local real_commit,observe,flush=native.atomic_commit,native.observe_memory,native.flush_observations
  local commits=0
  native.atomic_commit=function(...)commits=commits+1;return real_commit(...)end
  native.observe_memory=function(site,phase,...)
    if site=="save" and phase=="committed" then error("post-commit observation")end
    return observe(site,phase,...)
  end
  native.flush_observations=function()error("post-commit flush")end
  app.world.money=812;assert(app:save(target))
  local result=app._3ds.operations.last
  assert(result.committed and result.ready and result.diagnostic_count==2)
  assert(commits==1 and read(target)~=old and read(target..".bak")==old)
  native.atomic_commit,native.observe_memory,native.flush_observations=real_commit,observe,flush
  app.world.money=0;assert(app:load(target) and app.world.money==812)
end)

scenario("r68-primary-values-survive-double-fault",function()
  local line,observe=native.diagnostic_line,native.observe_memory
  local metamethods=0
  local token=setmetatable({},{__tostring=function()metamethods=metamethods+1;error("bad tostring")end})
  for _,primary in ipairs({false,47,token,"writer-primary"})do
    local app=fresh();assert(app:save(target));local old=read(target)
    app._3ds.operations.writer=function()error(primary,0)end
    native.diagnostic_line=function()error("failed diagnostic sink")end
    native.observe_memory=function(_,phase)if phase=="failed" then error("observe failed")end end
    local ok,value=pcall(app.save,app,target)
    assert(not ok)
    if type(primary)=="string" then
      assert(value:find(primary,1,true) and value:find("stack traceback:",1,true))
    else assert(rawequal(value,primary) and type(value)==type(primary))end
    local result=app._3ds.operations.last
    assert(not result.committed and result.ready and result.diagnostic_count>=2)
    assert(result.error_type==type(primary) and read(target)==old and metamethods==0)
    native.diagnostic_line,native.observe_memory=line,observe
  end
end)

scenario("r68-commit-refusal-keeps-primary-backup",function()
  local app=fresh();assert(app:save(target));app.world.money=442;assert(app:save(target))
  local old,older=read(target),read(target..".bak")
  local commit=native.atomic_commit;local count=0
  native.atomic_commit=function()count=count+1;return false,"injected commit refusal"end
  local ok,value=pcall(app.save,app,target)
  assert(not ok and value:find("injected commit refusal",1,true) and count==1)
  assert(read(target)==old and read(target..".bak")==older and not app._3ds.operations.last.committed)
  native.atomic_commit=commit
end)

scenario("r68-mandatory-cleanup-locks-direct-input-benchmark-exit",function()
  local finish,block=native.end_critical_io,native.operation_block
  local app=fresh();assert(app:save(target));local commits,blocked=0,0
  local commit=native.atomic_commit
  native.atomic_commit=function(...)commits=commits+1;return commit(...)end
  native.operation_block=function()blocked=blocked+1 end
  native.end_critical_io=function()finish();error("critical release uncertain")end
  app.world.money=913
  local ok,value=pcall(app.save,app,target)
  assert(not ok and value:find("SAVE COMMITTED",1,true))
  local result=app._3ds.operations.last
  assert(result.committed and not result.ready and result.cleanup_count==1 and commits==1 and blocked==1)
  local persisted=assert(reference.load(read(target),inverse_permanents()))
  assert(persisted.world.money==913)
  local calls=0;app._3ds.benchmark={tick=function()calls=calls+1 end}
  app.exit=function()calls=calls+1 end
  for _,invoke in ipairs({function()app:save(target)end,function()app:load(target)end,
    function()app._3ds:saveAndExit()end,function()app._3ds:prepareInput()end,
    function()app._3ds:handleAction{type="none"}end,function()app._3ds:benchmarkTick()end})do
    assert(not pcall(invoke))
  end
  assert(calls==0 and commits==1 and app._3ds.operations.last==result)
  native.end_critical_io,native.operation_block,native.atomic_commit=finish,block,commit
end)

scenario("r68-writer-primary-plus-mandatory-failure",function()
  local app=fresh();local primary={}
  local finish,block=native.end_critical_io,native.operation_block
  native.operation_block=function()end
  native.end_critical_io=function()finish();error("cleanup secondary")end
  app._3ds.operations.writer=function()error(primary)end
  local ok,value=pcall(app.save,app,target)
  assert(not ok and value==primary)
  local result=app._3ds.operations.last
  assert(not result.committed and not result.ready and result.error_type=="table" and result.cleanup_count==1)
  native.end_critical_io,native.operation_block=finish,block
end)

scenario("r68-boundary-prevents-writer",function()
  local boundary,block=native.operation_boundary,native.operation_block
  local app=fresh();local writers,blocks=0,0
  app._3ds.operations.writer=function()writers=writers+1;return true end
  native.operation_boundary=function()error("clock boundary rejected")end
  native.operation_block=function()blocks=blocks+1 end
  assert(not pcall(app.save,app,target))
  assert(writers==0 and blocks==1 and not app._3ds.operations.last.ready)
  native.operation_boundary,native.operation_block=boundary,block
end)

scenario("r68-resource-end-locks-after-commit",function()
  local app=fresh();local events={}
  local resource,block=native.resource_event,native.operation_block
  native.operation_block=function()end
  native.resource_event=function(event)
    events[#events+1]=event
    if event=="save-end" then return false,"resource end rejected"end
    return true
  end
  app._3ds.capabilities.resource_events=true
  local ok,value=pcall(app.save,app,target)
  assert(not ok and value:find("SAVE COMMITTED",1,true))
  assert(events[1]=="save-begin" and events[2]=="save-end" and #events==2)
  assert(app._3ds.operations.last.committed and not app._3ds.operations.last.ready)
  native.resource_event,native.operation_block=resource,block
end)

scenario("r68-load-errors-keep-false-nil-identity",function()
  for _,spec in ipairs({{kind="throw",value=false},{kind="return",value=false},
    {kind="throw"},{kind="return"},{kind="throw",value={}}})do
    local app=fresh();assert(app:save(target))
    app._3ds.afterLoadOperation=function()
      if spec.kind=="throw" then error(spec.value,0)end
      return false,spec.value
    end
    local ok,value=app:load(target)
    assert(ok==false and rawequal(value,spec.value))
    assert(app._3ds.operations.last.error_type==type(spec.value))
    assert(not app._3ds.operations.last.ready and app._3ds.operations.blocked)
    assert(not pcall(app._3ds.benchmarkTick,app._3ds))
  end
end)

scenario("r68-span-failure-bounded-abandon-reusable",function()
  local finish,abandon=native.span_end,native.span_abandon
  local app=fresh();local abandoned=0
  native.span_end=function()error("end observation failed")end
  native.span_abandon=function(token)
    assert(native.spans[token]);native.spans[token]=nil;abandoned=abandoned+1;return true
  end
  assert(app:save(target))
  assert(abandoned==2 and app._3ds.operations.last.ready and app._3ds.operations.last.diagnostic_count==2)
  native.span_end,native.span_abandon=finish,abandon
  assert(app:save(target))
end)

scenario("r68-real-save-ui-committed-deduplicated-type-safe",function()
  local line=native.diagnostic_line
  for _,primary in ipairs({false,setmetatable({},{__tostring=function()error("unexpected tostring")end})})do
    local app=fresh();local windows=0
    app.ui.app=app;app.ui.addWindow=function()windows=windows+1 end
    UIInformation=function(_,message)return message end
    app._3ds.operations.writer=function()error(primary,0)end
    native.diagnostic_line=function()error("diagnostic sink unavailable")end
    local window={ui=app.ui,close=function()end}
    assert(pcall(UISaveGame.doSave,window,target))
    assert(windows==1 and app._3ds.operations.last.reported)
    -- Previous last cannot suppress an unrelated later save implementation.
    app.save=function()error(primary,0)end
    assert(pcall(UISaveGame.doSave,window,target) and windows==2)
    native.diagnostic_line=line
  end
  local app=fresh();local windows=0
  R68AddWindow=function()windows=windows+1 end
  app.ui.app=app;app.ui.addWindow=R68AddWindow
  local flush=native.flush_observations
  native.flush_observations=function()error("post-commit flush")end
  assert(pcall(UISaveGame.doSave,{ui=app.ui,close=function()end},target))
  assert(app._3ds.operations.last.committed and windows==0)
  native.flush_observations=flush
end)
