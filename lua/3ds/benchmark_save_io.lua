-- R75 opt-in, private-run-only writer A/B. The same paused frame owns all four
-- atomic saves. Byte equality is verified after host readback, never inferred.
local IO={};IO.__index=IO
local Health=require("3ds.state_health")
local Activity=require("3ds.recovery_activity")
local Stress=require("3ds.benchmark_stress")
local capacities={16384,65536,65536,16384}
local function pack(values)
  local rows={}
  for k,v in pairs(values)do rows[#rows+1]=k.."="..tostring(v):gsub("[\r\n]"," "):sub(1,96) end
  table.sort(rows);local row=table.concat(rows,";")
  assert(#row<=1024,"save IO field overflow");return row
end
function IO:snapshot(stage)
  -- The immutable checkpoint retains detailed scene/resource values. Do not
  -- copy these three IO-only snapshots into every later capacity result: the
  -- native final envelope remains 128 fields / 12000 bytes.
  self.c:snapshot(stage)
  self.b.results["capacity_"..stage]=nil
  self.b.results["capacity_"..stage.."_memory"]=nil
end
function IO.new(capacity)
  local b=capacity.b
  assert(b.run.capacity=="r75-v1" and type(b.run.save_io_input_sha256)=="string"
    and #b.run.save_io_input_sha256==64 and not b.run.save_io_input_sha256:find("[^0-9a-f]"),
    "unbound save IO input")
  local r=b.results
  r.save_io_outcome="NOT_PROVEN";r.save_io_bytes_outcome="NOT_PROVEN"
  r.save_io_input_sha256=b.run.save_io_input_sha256
  r.save_io_order="16384,65536,65536,16384"
  r.save_io_scope="same paused frame; whole atomic operation; byte equality needs host readback"
  return setmetatable({c=capacity,b=b,phase="begin"},IO)
end
function IO:report(partial)
  if not Activity.active then return end
  local report=Activity.report()
  Activity.stop() -- bounded scalar report only; release all weak observers first
  self.b.results.save_io_activity=pack{outcome=report.outcome,count=report.count,
    updated=report.updated,action_covered=report.action_covered,partial=partial==true}
  if report.outcome=="FAIL" then self.failed=true;self.b.results.save_io_outcome="FAIL" end
  assert(report.outcome~="FAIL","save IO observed entity failure")
end
function IO:tick()
  local c,b=self.c,self.b
  c:check()
  if self.phase=="begin" then
    c:load(b.root.."input.sav")
    self:snapshot("save_io_loaded")
    local cohort={};local total=0
    for index,e in ipairs(b.app.world.entities)do
      if class.is(e,Staff) then
        total=total+1
        if #cohort<64 then cohort[#cohort+1]={index=index,kind=e.humanoid_class} end
      end
    end
    assert(#cohort>0,"save IO requires a staffed input hospital")
    b.results.save_io_activity_scope="first "..#cohort.." of "..total.." staff"
    Activity.start(b.app.world,cohort)
    c:normal("save_io_work",30000);self.phase="work";return false
  end
  assert(self.phase=="work","save IO phase replay")
  if b.native.clock_ms()<b.deadline then return false end
  c:advanced();self:report(false);self:snapshot("save_io_worked")
  b.app.world:setSpeed("Pause")
  assert(b.app.world:getCurrentSpeed()=="Pause","save IO pause rejected")
  Health.assertActive(b.app)
  local fingerprint=Stress.fingerprint(b.app)
  local progress=b:progress()
  self.phase="saving" -- failure cannot replay this batch
  for i,bytes in ipairs(capacities)do
    c:check()
    assert(b.app.world:getCurrentSpeed()=="Pause","save IO resumed during batch")
    local file=b.app.savegame_dir.."r75-io-"..i..".sav"
    local before=b.native.memory();local started=b.native.clock_ms()
    assert(b.app._3ds.operations:save(b.app,file,false,bytes)==true,"save IO atomic save failed")
    local ended=b.native.clock_ms();local after=b.native.memory()
    local result=b.app._3ds.operations.last
    assert(result and result.method=="save" and result.committed and result.completed and result.ready,
      "save IO lacks successful operation result")
    local now=b:progress()
    assert(now.world==progress.world and now.hours==progress.hours and now.frames==progress.frames,
      "save IO batch advanced simulation/presentation")
    assert(Stress.fingerprint(b.app)==fingerprint,"save IO batch changed hospital state")
    assert(ended>=started,"save IO clock reversed")
    local row=pack{capacity=bytes,file="r75-io-"..i..".sav",elapsed_ms=ended-started,
      heap_before=before.heap_available_estimate,heap_after=after.heap_available_estimate,
      heap_low=after.heap_available_low_water,linear_before=before.linear_free,linear_after=after.linear_free,
      committed=1,ready=1,frame=now.frames,world_completed=now.world}
    b.results["save_io_sample_"..i]=row
    b:recoveryLine("save-io-ab: sample="..i.." capacity="..bytes.." elapsed_ms="..(ended-started)
      .." committed=1 ready=1 file=r75-io-"..i..".sav")
    b:recoveryLine("save-io-memory: sample="..i.." heap_before="..tostring(before.heap_available_estimate)
      .." heap_after="..tostring(after.heap_available_estimate).." heap_low="..tostring(after.heap_available_low_water)
      .." linear_before="..tostring(before.linear_free).." linear_after="..tostring(after.linear_free))
  end
  c:load(b.app.savegame_dir.."r75-io-4.sav")
  assert(Stress.fingerprint(b.app)==fingerprint,"save IO roundtrip changed hospital state")
  Health.assertActive(b.app)
  b.results.save_io_roundtrip="PASS"
  b.results.save_io_outcome="HOST_READBACK_REQUIRED"
  self:snapshot("save_io_reloaded")
  self.phase="complete";c.phase="begin";return true
end
function IO:close()
  if Activity.active then self:report(true) end
  if self.phase~="complete" then self.b.results.save_io_outcome=self.failed and "FAIL" or "NOT_PROVEN" end
end
return IO
