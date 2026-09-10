-- Real pinned reference/candidate/string/FILE serializers and both readers.
-- The small hospital-shaped graph supplies only class/window seams; no private
-- device save, unknown closure or native map is executed by this host probe.
package.path=assert(os.getenv('CTH3DS_FINGERPRINT_LUA'))..'/?.lua;'..package.path
local H=require('3ds.state_health')
local S=require('3ds.benchmark_stress')
local values={0,-0.0,1,-1,16383,16384,70000,-70000,0.125,-0.125,17.25,
  9007199254740991,9007199254740992,-9007199254740992,0x1.0000000000001p+0,
  0x0.0000000000001p-1022,0x1.fffffffffffffp+1023}
local variants={assert(reference.dump(values,permanent)),assert(candidate.dump(values,permanent)),disk(values)}
assert(variants[1]==variants[2] and variants[2]==variants[3])
local checks=0
for _,bytes in ipairs(variants) do
  for _,reader in ipairs{reference,candidate} do
    local restored=assert(reader.load(bytes,inverse))
    assert(math.type(values[7])=='integer' and math.type(restored[7])=='float')
    assert(tostring(values[7])=='70000' and tostring(restored[7])=='70000.0')
    for i,value in ipairs(values) do
      assert(value==restored[i] and H.scalar(value)==H.scalar(restored[i]))
      checks=checks+1
    end
  end
end
-- This format cannot preserve all 64-bit integer values. The acceptance check
-- must expose a real loss of precision instead of rounding both sides to fit.
for _,value in ipairs{9007199254740993,-9007199254740993,math.maxinteger} do
  for _,writer in ipairs{reference,candidate} do
    for _,reader in ipairs{reference,candidate} do
      local restored=assert(reader.load(assert(writer.dump({value},permanent)),inverse))[1]
      assert(value~=restored and H.scalar(value)~=H.scalar(restored))
    end
  end
end
assert(H.scalar(70000)~=H.scalar(70001))
assert(H.scalar(1.0)~=H.scalar(0x1.0000000000001p+0))
for _,value in ipairs{0/0,math.huge,-math.huge} do
  assert(not pcall(H.scalar,value),'nonfinite state must fail closed')
end

Staff={};Patient={}
class={is=function(entity,expected)
  return (expected==Staff and entity.test_kind=='staff') or
    (expected==Patient and entity.test_kind=='patient')
end}
local function dateText()return '12-01-03T00' end
local function plotCount()return 1 end
local function plotOwner()return 1 end
local function timer()end
for key,fn in pairs{dateText=dateText,plotCount=plotCount,plotOwner=plotOwner,timer=timer} do
  permanent[fn]='fingerprint-'..key;inverse['fingerprint-'..key]=fn
end
local staff={test_kind='staff',humanoid_class='Doctor',ticks=true,tile_x=70,tile_y=71,
  timer_time=70000,timer_function=timer,profile={wage=70000},
  action_queue={{name='walk',must_happen=true,uninterruptible=false},
    {name='idle',must_happen=false,todo_interrupt=true}}}
local hospital={balance=70000,staff={[5]=staff}}
local app={ui={hospital=hospital},world={entities={staff},game_date={tostring=dateText},
  map={th={getPlotCount=plotCount,getPlotOwner=plotOwner}},rooms={
    {hospital=hospital,room_info={id='gp'},x=70000,y=2,width=3,height=4}}}}
local before=S.fingerprint(app)
for _,bytes in ipairs{assert(reference.dump(app,permanent)),assert(candidate.dump(app,permanent)),disk(app)} do
  for _,reader in ipairs{reference,candidate} do
    local restored=assert(reader.load(bytes,inverse))
    local lines={};local native={diagnostic_line=function(line)lines[#lines+1]=line end}
    S.assertFingerprint(restored,before,'unexpected numeric mismatch',native)
    assert(#lines==0)
    local e=restored.world.entities[1]
    local mutations={
      function()restored.ui.hospital.balance=70001 end,
      function()restored.world.entities={} end,
      function()e.ticks=false end,
      function()e.timer_time=e.timer_time+1 end,
      function()e.timer_function=nil end,
      function()table.remove(e.action_queue,1) end,
      function()e.action_queue[1].must_happen=false end,
      function()e.profile.wage=e.profile.wage+1 end,
      function()restored.world.rooms={} end}
    for _,change in ipairs(mutations) do
      change()
      local ok,err=pcall(S.assertFingerprint,restored,before,'actual state changed',native)
      assert(not ok and tostring(err):find('actual state changed',1,true))
      assert(#lines==1 and #lines[1]<=230 and not lines[1]:find('[\r\n]'))
      restored=assert(reader.load(bytes,inverse));e=restored.world.entities[1];lines={}
    end
    restored.ui.hospital.balance=0/0
    assert(not pcall(S.assertFingerprint,restored,before,'invalid state',native))
  end
end
assert(H.fingerprintDifference('same','same')==nil)
local difference=H.fingerprintDifference('abc\nx','abc\ny')
assert(difference:find('line=2 column=1',1,true))
assert(H.fingerprintDifference('abc','abcd'):find('column=4',1,true))
app.ui.hospital.balance=70001
local ok,err=pcall(S.assertFingerprint,app,before,'original state mismatch',{
  diagnostic_line=function()error('diagnostic failure')end})
assert(not ok and tostring(err):find('original state mismatch',1,true))
print('PASS native numeric fingerprint: '..checks..' finite equal-value cases; integer/double 70000 reproduced; real precision loss and hospital timer/action/state mutations rejected')
