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
    if new not in text:text=replace_exact(text,old,new,'occupied real humanoid query')
    yield path,text
