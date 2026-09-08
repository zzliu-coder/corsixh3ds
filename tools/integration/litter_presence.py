"""Prove the whole index has no litter before doing each staff's local scan."""
from sound_lifetime import replace_exact

def transforms(root):
    name='CorsixTH/Lua/entity_map.lua'
    text=(root/name).read_text()
    if 'CORSIXTH_3DS_LITTER_PRESENCE_R63' not in text:
        text=replace_exact(text,'class "EntityMap"', '''-- CORSIXTH_3DS_LITTER_PRESENCE_R63: derived, weak-keyed and unsaved.
-- A borrowed mutable object list makes the count unknown, conservatively.
local litter_counts = setmetatable({}, {__mode="k"})
class "EntityMap"''','private litter index')
        text=replace_exact(text,'  self.entity_map = {}',
            '  self.entity_map = {}\n  litter_counts[self] = 0','empty index count')
        anchor='      add_entity_to_table(entity, self:_cell(x, y, true).objects)'
        text=replace_exact(text,anchor,anchor+'''
      if entity.id=="litter" and litter_counts[self]~=nil then
        litter_counts[self]=litter_counts[self]+1
      end''','litter insertion count')
        anchor='      remove_entity_from_table(entity, self:peekObjectsAtCoordinate(x, y))'
        text=replace_exact(text,anchor,anchor+'''
      if entity.id=="litter" and litter_counts[self]~=nil then
        litter_counts[self]=litter_counts[self]-1
      end''','litter removal count')
        text=replace_exact(text,'function EntityMap:getObjectsAtCoordinate(x, y)',
            'function EntityMap:getObjectsAtCoordinate(x, y)\n  litter_counts[self] = nil',
            'mutable aliases disable count fast path')
        text=replace_exact(text,'function EntityMap:compact()',
            'function EntityMap:compact()\n  local litter, trusted = 0, true','rebuild derived state on load')
        text=replace_exact(text,'    for y, cell in pairs(self.entity_map[x]) do',
            '''    for y, cell in pairs(self.entity_map[x]) do
      if cell.borrowed then trusted=false end
      for _,object in ipairs(cell.objects)do
        if object.id=="litter" then litter=litter+1 end
      end''','count original ordered index entries')
        start=text.index('function EntityMap:compact()')
        end=text.index('\nend',start)
        text=text[:end]+'\n  litter_counts[self] = trusted and litter or nil'+text[end:]
        text+='''
function EntityMap:hasAnyLitter()
  return litter_counts[self] ~= 0 -- unknown state always takes full query
end
'''
    yield name,text
    name='CorsixTH/Lua/entities/humanoid.lua'
    text=(root/name).read_text()
    marker='  -- R63: a proven globally empty litter set has an empty local result.'
    if marker not in text:
        begin=text.index('function Humanoid:findObjectsInSquare(')
        end=text.index('\nend',begin)
        part=text[begin:end]
        part=replace_exact(part,'  local entity_map = self.world.entity_map',
            '''  local entity_map = self.world.entity_map
  -- R63: a proven globally empty litter set has an empty local result.
  if object_spec=="litter" and entity_map.hasAnyLitter and not entity_map:hasAnyLitter() then
    return result
  end''','no-litter fast path')
        text=text[:begin]+part+text[end:]
    yield name,text
