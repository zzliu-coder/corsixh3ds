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
    marker = '-- CORSIXTH_3DS_QUERY_R62'
    if marker not in text:
        if new not in text and '-- CORSIXTH_3DS_QUERY_R61' not in text:
            text=replace_exact(text,old,new,'occupied real humanoid query')
        begin = text.index('function Humanoid:findObjectsInSquare(')
        end = text.index('\nend', begin) + 4
        text = text[:begin] + QUERY + text[end:]
    yield path,text

QUERY = '''function Humanoid:findObjectsInSquare(size, object_spec, visitor)
  -- CORSIXTH_3DS_QUERY_R62: same x/y/list order and native room membership.
  -- A visitor is only used by the litter happiness consumer, which cannot
  -- mutate this index or room membership. Other callers keep owned arrays.
  local single = type(object_spec) == "string"
  local result = not visitor and {} or nil
  assert(not visitor or single, "Visitor requires one object type")
  if not single then
    for _, name in ipairs(object_spec) do result[name] = {} end
  end
  local th_map = self.world.map.th
  local entity_map = self.world.entity_map
  local rows = entity_map.entity_map
  local width, height = entity_map.width, entity_map.height
  if not rows then width, height = th_map:size() end
  local self_room_id
  size = (size >= 0) and size or 0
  for x = math.max(1, self.tile_x - size), math.min(width, self.tile_x + size) do
    local row = rows and rows[x]
    for y = math.max(1, self.tile_y - size), math.min(height, self.tile_y + size) do
      local cell = row and row[y]
      local objects = cell and cell.objects
      if not rows then objects = entity_map:peekObjectsAtCoordinate(x, y) end
      local same_room
      for i = 1, objects and #objects or 0 do
        local obj = objects[i]
        if (single and obj.id == object_spec) or (not single and result[obj.id]) then
          if self_room_id == nil then self_room_id = th_map:getRoomId(self.tile_x, self.tile_y) end
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
