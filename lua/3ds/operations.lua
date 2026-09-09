-- Save/load owns file facts and mandatory cleanup. Observations consume those
-- facts and cannot change them. This module retains no App/world singleton.
local Operations = {}
Operations.__index = Operations

local function describe(value)
  if type(value)=="string" then return value:sub(1,240) end
  return "non-string Lua error ("..type(value)..")"
end

local function preserve_error(value)
  if type(value)=="string" and debug and debug.traceback then
    return debug.traceback(value,2)
  end
  return value
end

local function note(result, kind, site, value)
  local count=kind.."_count"
  result[count]=math.min(65535,result[count]+1)
  if not result[kind.."_first"] then
    result[kind.."_first"]=site..": "..describe(value)
  end
end

function Operations:guard()
  if self.blocked then error(self.blocked,0) end
end

function Operations:diagnostic(result, site, callback, ...)
  if not callback then return true end
  local ok,value=pcall(callback,...)
  if not ok then note(result,"diagnostic",site,value) end
  return ok,value
end

function Operations:mandatory(result, site, callback, ...)
  local ok,value=pcall(callback,...)
  if not ok then note(result,"cleanup",site,value) end
  return ok,value
end

function Operations:cleanupFailure(result, site, value)
  note(result,"cleanup",site,value)
end

function Operations:release(result)
  self.current=result.parent
  result.parent=nil
end

function Operations:endSpan(result, token, success)
  if not token then return end
  local ok=self:diagnostic(result,"span_end",self.platform.native.span_end,token,success)
  if not ok then
    local abandon=self.platform.native.span_abandon
    local abandoned,accepted=pcall(function()return abandon and abandon(token)end)
    if not abandoned or accepted~=true then
      note(result,"cleanup","span_abandon",abandoned and "token not reclaimed" or accepted)
    end
  end
end

function Operations:baseline(result, phase)
  local native=self.platform.native
  local begun,token=self:diagnostic(result,"gc_span_begin",native.span_begin,"gc")
  self:mandatory(result,"gc",collectgarbage,"collect")
  if begun then self:endSpan(result,token,true) end
  if phase=="gc-after" then
    self:mandatory(result,"gc_boundary",native.operation_boundary)
  end
  self:diagnostic(result,phase,native.observe_memory,result.site,phase,result.method,"Operation")
end

function Operations:checkpoint(result, phase)
  self:diagnostic(result,"checkpoint",self.platform.native.checkpoint,
    "save_load",phase,result.filename,0,0)
end

function Operations:notify(result, message, failed)
  self:diagnostic(result,"notice",self.platform.native.set_notice,message,failed)
end

function Operations:report(result, message)
  local ok,shown=self:diagnostic(result,"showError",self.platform.showError,self.platform,message)
  result.reported=ok and shown==true
end

function Operations:publish(result)
  if result.diagnostic_count==0 and result.cleanup_count==0 then return end
  local message="operation-result: method="..result.method.." committed="..tostring(result.committed)..
    " ready="..tostring(result.ready).." diagnostic_count="..result.diagnostic_count..
    " cleanup_count="..result.cleanup_count.." first="..(result.cleanup_first or result.diagnostic_first)
  local callback=self.platform.native.diagnostic_line
  local ok=callback and self:diagnostic(result,"result_log",callback,message)
  if not ok then self:diagnostic(result,"result_print",print,message) end
end

function Operations:finish(result, token, success)
  local platform,native=self.platform,self.platform.native
  if self.blocked and result.cleanup_count==0 then note(result,"cleanup","nested_operation",self.blocked) end
  self:mandatory(result,"operation_boundary",native.operation_boundary)
  self:diagnostic(result,"observe_result",native.observe_memory,result.site,
    result.committed and "committed" or (result.completed and "loaded" or "failed"),result.method,"Operation")
  self:baseline(result,"gc-after")
  if result.method=="load" then self:mandatory(result,"scene",platform.syncScene,platform) end
  self:endSpan(result,token,success and result.cleanup_count==0)
  self:diagnostic(result,"flush",native.flush_observations)
  result.ready=result.cleanup_count==0
  if not result.ready then
    self.blocked=(result.committed and "SAVE COMMITTED; " or "OPERATION FAILED; ")..
      "UNSAFE TO CONTINUE: "..result.cleanup_first
    -- Native stops simulation even when an upstream UI catches our error and
    -- the player sends no further HID input. Normal clock semantics unchanged.
    if native.operation_block then
      local ok,err=pcall(native.operation_block)
      if not ok then note(result,"cleanup","operation_block",err) end
    end
  end
  self.last=result -- only bounded strings/scalars, never the original error graph
end

function Operations:start(method, filename, preload)
  self:guard()
  assert(not self.current or (preload and method=="save" and self.current.method=="load"),"operation already active")
  assert(type(filename)=="string" and filename~="","invalid "..method.." path")
  local result={method=method,site=method=="save" and "save" or "reload",
    filename=filename,committed=false,completed=false,ready=true,diagnostic_count=0,cleanup_count=0,parent=self.current}
  self.current=result
  local begun,token=self:diagnostic(result,"span_begin",self.platform.native.span_begin,method)
  local ok,err=self:mandatory(result,"operation_boundary",self.platform.native.operation_boundary)
  self:diagnostic(result,"observe_before",self.platform.native.observe_memory,result.site,"before",method,"Operation")
  if method=="load" then self:baseline(result,"gc-before") end
  return result,begun and token or nil,ok,err
end

function Operations:save(instance, filename, preload)
  local result,token,boundary,boundary_error=self:start("save",filename,preload)
  local platform,native=self.platform,self.platform.native
  local critical,transaction=false,false
  local starting
  self:checkpoint(result,"save-begin")
  local ok,err=xpcall(function()
    if not boundary then error(boundary_error,0) end
    starting="save-begin"
    platform:resourceEvent("save-begin",filename,true); transaction=true
    starting="begin_critical_io"
    native.begin_critical_io(); critical=true
    starting=nil
    local gfx=instance.gfx
    if gfx and type(gfx.trimRawWarm)=="function" then gfx:trimRawWarm() end
    if native.prepare_save then native.prepare_save() end
    assert(self.writer(instance,filename..".tmp")==true,"save writer did not confirm success")
    local committed,detail=native.atomic_commit(filename..".tmp",filename,true)
    if committed~=true then result.rejected=true;error("save commit: "..describe(detail),0) end
    result.committed=true;result.completed=true
  end,preserve_error)
  if not ok and starting then note(result,"cleanup",starting,err) end
  if critical then self:mandatory(result,"end_critical_io",native.end_critical_io) end
  if transaction then self:mandatory(result,"save-end",platform.resourceEvent,platform,"save-end",filename,ok) end
  self:finish(result,token,ok)
  if not ok then
    result.error_type=type(err);result.error_summary=describe(err)
    self:report(result,"SAVE FAILED: "..describe(err))
    self:checkpoint(result,"save-failed")
    self:publish(result)
    self:release(result)
    error(err,0) -- preserve primary value even when cleanup/diagnostics also fail
  end
  if not result.ready then
    self:report(result,self.blocked)
    self:publish(result)
    self:release(result)
    error(self.blocked,0)
  end
  self:notify(result,"SAVE OK",false)
  self:checkpoint(result,"save-complete")
  self:publish(result)
  self:release(result)
  return true
end

function Operations:load(instance, filename)
  local result,token,boundary,boundary_error=self:start("load",filename)
  local platform=self.platform
  local transaction=false
  local starting=false
  local ok,accepted,detail=xpcall(function()
    if not boundary then error(boundary_error,0) end
    if result.cleanup_count>0 then return false,"load preparation failed" end
    local requested=filename:gsub("\\","/"):match("([^/]+)$") or ""
    requested=requested:lower()
    local recovery_name="recovery-before-load.sav"
    if requested==recovery_name or requested==recovery_name..".bak" or requested==recovery_name..".tmp" then
      recovery_name="recovery-before-load-alt.sav"
    end
    local recovery=instance.savegame_dir..recovery_name
    instance._3ds_preload_recovery=nil
    if instance.world then
      local saved,value=pcall(self.save,self,instance,recovery,true)
      if not saved then error(value,0) end
      if value~=true then return false,"preload recovery save refused" end
      instance._3ds_preload_recovery=recovery
    end
    self:checkpoint(result,"load-begin")
    starting=true
    platform:resourceEvent("load-begin",filename,true);transaction=true;starting=false
    local loaded,reason=self.reader(instance,filename)
    if loaded~=true then return false,reason end
    result.completed=true
    return true
  end,preserve_error)
  if not ok and starting then note(result,"cleanup","load-begin",accepted) end
  local success=ok and accepted==true
  if transaction then self:mandatory(result,"load-end",platform.resourceEvent,platform,"load-end",filename,success) end
  if success then
    local repaired,repair_result,repair_error=xpcall(platform.afterLoadOperation,preserve_error,platform,instance,filename,result)
    if not repaired or repair_result~=true then
      success=false
      if repaired then detail=repair_error else detail=repair_result end
      result.raised=not repaired
      note(result,"cleanup","after_load",detail)
    end
  end
  self:finish(result,token,success)
  if not success then
    local primary
    if ok then primary=detail else primary=accepted end
    result.error_type=type(primary);result.error_summary=describe(primary)
    result.raised=result.raised or not ok
    self:report(result,"LOAD FAILED: "..describe(primary))
    self:checkpoint(result,"load-failed")
    self:publish(result)
    self:release(result)
    return false,primary
  end
  if not result.ready or self.blocked then
    self:report(result,self.blocked)
    self:publish(result)
    self:release(result)
    return false,self.blocked
  end
  self:checkpoint(result,"load-complete")
  self:notify(result,"LOAD COMPLETE",false)
  self:publish(result)
  self:release(result)
  return true
end

return {new=function(platform, writer, reader)
  assert(type(writer)=="function" and type(reader)=="function","save/load originals missing")
  return setmetatable({platform=platform,writer=writer,reader=reader},Operations)
end}
