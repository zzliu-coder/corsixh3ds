"""Reduce repeated staff UI allocations; sample real work without skipping ticks."""
from sound_lifetime import replace_exact

def reception_binding(text):
    marker='CORSIXTH_3DS_RECEPTION_IDENTITY_R65'
    if marker in text:
        return text
    anchor='local action_staff_reception_idle_phase = permanent"action_staff_reception_idle_phase"'
    hook='''-- CORSIXTH_3DS_RECEPTION_IDENTITY_R65: bind the actual permanent closure
-- before any saved action is inspected. App/benchmark load order is irrelevant.
local native_ok, reception_native = pcall(require, "th3ds")
local IS_3DS = native_ok and reception_native.is_platform()
if IS_3DS then
  require("3ds.state_health").bindReceptionInterrupt(action_staff_reception_interrupt)
end

'''
    return replace_exact(text,anchor,hook+anchor,'bind formal reception interrupt identity')

def transforms(root):
    # Older 41-file test inventories omit this unmodified upstream module.
    # Full product assemblies contain it; the dedicated R65 test requires it.
    name='CorsixTH/Lua/humanoid_actions/staff_reception.lua'
    if (root/name).is_file():
        yield name,reception_binding((root/name).read_text())
    name='CorsixTH/Lua/entities/humanoids/staff.lua'
    text=(root/name).read_text()
    if 'CORSIXTH_3DS_STAFF_INFO_R62' not in text:
        old='''  self:setDynamicInfo('text', {
    self.profile.profession,
    dynamic_text,
    fatigue_text,
  })
  if self.hospital then
    self:setDynamicInfo('dividers', {self.hospital.policies["goto_staffroom"]})
  end'''
        new='''  -- CORSIXTH_3DS_STAFF_INFO_R62: equal content reuses its table. Changed
  -- content still publishes a new table so any reader's old snapshot is safe.
  local info = self.dynamic_info
  local lines = info and info.text
  if not lines or lines[1] ~= self.profile.profession or
      lines[2] ~= dynamic_text or lines[3] ~= fatigue_text then
    self:setDynamicInfo('text', {self.profile.profession, dynamic_text, fatigue_text})
  end
  if self.hospital then
    local divider = self.hospital.policies["goto_staffroom"]
    local dividers = info and info.dividers
    if not dividers or dividers[1] ~= divider then
      self:setDynamicInfo('dividers', {divider})
    end
  end'''
        text=replace_exact(text,old,new,'staff unchanged dynamic content')
        text=replace_exact(text,'function Staff:tick()\n', '''-- Sample every sixteenth staff tick. Counter is outside the saved World.
local staff_profile_iteration = 0
function Staff:tick()
  staff_profile_iteration = (staff_profile_iteration + 1) % 16
  local mark = staff_profile_iteration == 0 and TH3DS and TH3DS.cpu_phase
  local phase = mark and mark()
''','staff split timing')
        begin=text.index('function Staff:tick()')
        end=text.index('\nend',begin)+4
        method=text[begin:end]
        for anchor,label in (
            ('  Entity.tick(self)','sample_staff_base'),
            ('  self:checkIfWaitedTooLongForRaise()','sample_staff_rest'),
            ('  -- seeing litter will make you unhappy. If it is pee or puke it is worse','sample_staff_attributes'),
            ('  self:findObjectsInSquare(2, "litter", apply_litter_happiness)','sample_staff_litter'),
            ('  self:updateSpeed()','sample_staff_speed'),
        ):
            method=replace_exact(method,anchor,anchor+'\n  if mark then phase = mark("'+label+'", phase) end',label)
        text=text[:begin]+method+text[end:]
    # Use the already attached platform, as World:onTick does. Staff is loaded
    # under upstream strict.lua; TH3DS is a module-local name in other files.
    text=text.replace('  local mark = staff_profile_iteration == 0 and TH3DS and TH3DS.cpu_phase',
        '  local native = staff_profile_iteration == 0 and TheApp and TheApp._3ds and TheApp._3ds.native\n'
        '  local mark = native and native.cpu_phase')
    if 'CORSIXTH_3DS_STAFF_ROTATION_R63' not in text:
        old='''-- Sample every sixteenth staff tick. Counter is outside the saved World.
local staff_profile_iteration = 0
function Staff:tick()
  staff_profile_iteration = (staff_profile_iteration + 1) % 16
  local native = staff_profile_iteration == 0 and TheApp and TheApp._3ds and TheApp._3ds.native
  local mark = native and native.cpu_phase'''
        new='''-- CORSIXTH_3DS_STAFF_ROTATION_R63: World rotates the sampled ordinal
-- each real entity pass. No game RNG and no persistent entity/world fields.
function Staff:tick()
  local platform = TheApp and TheApp._3ds
  local sampler = platform and platform.staff_sampler
  local mark
  if sampler then
    sampler.ordinal = sampler.ordinal + 1
    if sampler.ordinal % 16 == sampler.offset then mark = sampler.mark end
  end'''
        text=replace_exact(text,old,new,'rotate staff sampling across stable entity order')
    if 'CORSIXTH_3DS_STAFF_COST_R64' not in text:
        text=replace_exact(text,'function Staff:updateSpeed()','''-- CORSIXTH_3DS_STAFF_COST_R64: captures are assigned after the method
-- definitions below. Overrides retain the original virtual call sequence.
local speed_crack_up, speed_very_tired, speed_get_attribute
function Staff:updateSpeed()''','staff speed original method identities')
        text=replace_exact(text,'''    if self:isCrackUpTired() then
      level = level - 2
    elseif self:isVeryTired() then
      level = level - 1
    end''','''    if self.isCrackUpTired == speed_crack_up and self.getAttribute == speed_get_attribute then
      local fatigue = self:getAttribute("fatigue") * 1000
      local gbv = self.world.map.level_config.gbv
      if fatigue >= gbv.CrackUpTired then
        level = level - 2
      elseif self.isVeryTired == speed_very_tired then
        if fatigue >= gbv.VeryTired then level = level - 1 end
      elseif self:isVeryTired() then
        level = level - 1
      end
    elseif self:isCrackUpTired() then
      level = level - 2
    elseif self:isVeryTired() then
      level = level - 1
    end''','staff speed single fatigue read')
        anchor='''function Staff:isCrackUpTired()
  return self:getAttribute("fatigue") * 1000 >= self.world.map.level_config.gbv.CrackUpTired
end'''
        text=replace_exact(text,anchor,anchor+'''
speed_crack_up, speed_very_tired = Staff.isCrackUpTired, Staff.isVeryTired
speed_get_attribute = Humanoid.getAttribute''','staff speed capture original methods')
        text=replace_exact(text,'''  if self:getAttribute("fatigue") >= self.hospital.policies["goto_staffroom"] and
      not class.is(self:getRoom(), StaffRoom) then''','''  local needs_rest = self:getAttribute("fatigue") >= self.hospital.policies["goto_staffroom"]
  local checked_room = needs_rest and self:getRoom()
  if needs_rest and not class.is(checked_room, StaffRoom) then''','staff rest room lookup')
        text=replace_exact(text,'''    if self.waiting_for_staffroom then
      self:changeAttribute("happiness", -0.001)
    end

    local room = self:getRoom()''','''    local room = checked_room
    if self.waiting_for_staffroom then
      self:changeAttribute("happiness", -0.001)
      room = self:getRoom()
    elseif self.getRoom ~= Humanoid.getRoom then
      -- A virtual room lookup may have effects of its own.
      room = self:getRoom()
    end''','staff rest reuse only uninterrupted base lookup')
    yield name,text
