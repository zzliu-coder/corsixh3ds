"""Reduce repeated staff UI allocations; sample real work without skipping ticks."""
from sound_lifetime import replace_exact

def transforms(root):
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
    yield name,text
