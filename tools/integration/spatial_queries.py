"""Read occupied tiles before expensive native room queries; same result order."""
from sound_lifetime import replace_exact

def transforms(root):
    path='CorsixTH/Lua/entities/humanoid.lua'
    text=(root/path).read_text()
    old='''  for x = self.tile_x - size, self.tile_x + size do
    if x >= 1 and x <= width then
      for y = self.tile_y - size, self.tile_y + size do
        if y >= 1 and y <= height and th_map:getRoomId(x, y) == self_room_id then
          for _, obj in ipairs(entity_map:getObjectsAtCoordinate(x, y)) do
            local entry = objs_table[obj.id]
            if entry then entry[#entry + 1] = obj end
          end
        end
      end
    end
  end'''
    new='''  -- CORSIXTH_3DS_OCCUPIED_QUERY_R59
  -- Preserve x/y/list order, bounds and room membership. No persistent cache:
  -- moving objects, litter and changing room walls are visible immediately.
  for x = math.max(1, self.tile_x - size), math.min(width, self.tile_x + size) do
    for y = math.max(1, self.tile_y - size), math.min(height, self.tile_y + size) do
      local same_room
      for _, obj in ipairs(entity_map:getObjectsAtCoordinate(x, y)) do
        local entry = objs_table[obj.id]
        if entry then
          if same_room == nil then same_room = th_map:getRoomId(x, y) == self_room_id end
          if same_room then entry[#entry + 1] = obj end
        end
      end
    end
  end'''
    marker = '-- CORSIXTH_3DS_QUERY_R61'
    if marker not in text:
        if new not in text:text=replace_exact(text,old,new,'occupied real humanoid query')
        begin = text.index('function Humanoid:findObjectsInSquare(')
        end = text.index('\nend', begin) + 4
        text = text[:begin] + QUERY + text[end:]
    yield path,text
    path='CorsixTH/Lua/entities/humanoids/staff.lua'
    text=(root/path).read_text()
    if '-- CORSIXTH_3DS_LITTER_VISITOR_R61' not in text:
        old='''  for _, litter in ipairs(self:findObjectsInSquare(2, "litter")) do
    if litter:anyLitter() then
      self:changeAttribute("happiness", -0.0002)
    else
      self:changeAttribute("happiness", -0.0004)
    end
  end'''
        new='''  self:findObjectsInSquare(2, "litter", apply_litter_happiness)'''
        text=replace_exact(text,old,new,'ordered allocation-free litter visitor')
        text=replace_exact(text,'function Staff:tick()', '''-- CORSIXTH_3DS_LITTER_VISITOR_R61
local function apply_litter_happiness(staff, litter)
  if litter:anyLitter() then
    staff:changeAttribute("happiness", -0.0002)
  else
    staff:changeAttribute("happiness", -0.0004)
  end
end

function Staff:tick()''','staff visitor definition')
    yield path,text

QUERY = '''function Humanoid:findObjectsInSquare(size, object_spec, visitor)
  -- CORSIXTH_3DS_QUERY_R61: same x/y/list order and native room membership.
  -- A visitor is only used by the litter happiness consumer, which cannot
  -- mutate this index or room membership. Other callers keep owned arrays.
  local single = type(object_spec) == "string"
  local result = not visitor and {} or nil
  assert(not visitor or single, "Visitor requires one object type")
  if not single then
    for _, name in ipairs(object_spec) do result[name] = {} end
  end
  local th_map = self.world.map.th
  local self_room_id = th_map:getRoomId(self.tile_x, self.tile_y)
  local width, height = th_map:size()
  local entity_map = self.world.entity_map
  size = (size >= 0) and size or 0
  for x = math.max(1, self.tile_x - size), math.min(width, self.tile_x + size) do
    for y = math.max(1, self.tile_y - size), math.min(height, self.tile_y + size) do
      local same_room
      for _, obj in ipairs(entity_map:peekObjectsAtCoordinate(x, y)) do
        if (single and obj.id == object_spec) or (not single and result[obj.id]) then
          if same_room == nil then same_room = th_map:getRoomId(x, y) == self_room_id end
          if same_room then
            if visitor then visitor(self, obj)
            else
              local entry = single and result or result[obj.id]
              entry[#entry + 1] = obj
            end
          end
        end
      end
    end
  end
  return result
end'''
