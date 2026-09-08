"""Observe the seven existing World phases without changing their schedule."""
from sound_lifetime import replace_exact

def transforms(root):
    path='CorsixTH/Lua/world.lua'
    text=(root/path).read_text()
    begin=text.index('function World:onTick()')
    end=text.index('\nend',begin)+4
    method=text[begin:end]
    marker='-- CORSIXTH_3DS_WORLD_PHASES_R56'
    if marker not in method:
        method=replace_exact(method,'  if self.tick_timer == 0 then',
            '''  if self.tick_timer == 0 then
    -- CORSIXTH_3DS_WORLD_PHASES_R56
    local native = TheApp and TheApp._3ds and TheApp._3ds.native
    local mark = native and native.cpu_phase
    local phase = mark and mark()''','World phase begin')
        sites=(
          ('    self.game_date = new_game_date','world_calendar'),
          ('      self.anims:tick()','world_animations'),
          ('      self.current_tick_entity = nil','world_entities'),
          ('          0.25 + self.hospitals[1].heating.radiator_heat * 0.3)','world_map'),
          ('      self.dispatcher:onTick()','world_dispatch'),
        )
        for anchor,name in sites:
            method=replace_exact(method,anchor,anchor+'\n      if mark then phase = mark("'+name+'", phase) end',name)
        for anchor,name in (('      for _, entity in ipairs(self.entities) do','world_hospitals'),
                            ('      self.dispatcher:onTick()','world_ui')):
            method=replace_exact(method,anchor,'      if mark then phase = mark("'+name+'", phase) end\n'+anchor,name)
        text=text[:begin]+method+text[end:]
    if '-- CORSIXTH_3DS_ENTITY_SAMPLE_R58' not in text:
        text=replace_exact(text,'function World:onTick()', '''-- CORSIXTH_3DS_ENTITY_SAMPLE_R58
-- One in sixteen real update passes, outside persisted World state. The other
-- fifteen retain the direct entity call. Classification never changes order.
local entity_profile_iteration = 0
function World:onTick()''','entity sample counter')
        text=replace_exact(text,'    local phase = mark and mark()', '''    local phase = mark and mark()
    entity_profile_iteration = (entity_profile_iteration + 1) % 16
    local sample_entities = mark and entity_profile_iteration == 0''','entity sample cadence')
        text=replace_exact(text,'          entity:tick()', '''          if sample_entities then
            local kind = Staff and class.is(entity, Staff) and "sample_entity_staff"
              or Patient and class.is(entity, Patient) and "sample_entity_patient"
              or Object and class.is(entity, Object) and "sample_entity_object"
              or "sample_entity_other"
            local began = mark()
            entity:tick()
            mark(kind, began)
          else
            entity:tick()
          end''','real entity sample')
    yield path,text
