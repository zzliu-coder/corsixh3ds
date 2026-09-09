"""Sparse occupied cells, with explicit borrowed reads and legacy mutable getters."""
from sound_lifetime import replace_exact

METHODS = '''
-- CORSIXTH_3DS_SPARSE_ENTITY_INDEX_R61
-- Read-only empty results never enter the saved World graph. Legacy get*
-- callers receive a unique live array, retained even if subsequently emptied.
local empty_entities = setmetatable({}, {
  __newindex = function() error("EntityMap peek result is read-only") end,
  __metatable = false,
})

function EntityMap:_cell(x, y, create)
  assert(x >= 1 and y >= 1 and x <= self.width and y <= self.height,
    "Coordinate requested is out of the entity map bounds")
  local row = self.entity_map[x]
  local cell = row[y]
  if not cell and create then
    cell = {humanoids = {}, objects = {}}
    row[y] = cell
  end
  return cell
end

function EntityMap:peekHumanoidsAtCoordinate(x, y)
  local cell = self:_cell(x, y, false)
  return cell and cell.humanoids or empty_entities
end

function EntityMap:peekObjectsAtCoordinate(x, y)
  local cell = self:_cell(x, y, false)
  return cell and cell.objects or empty_entities
end

function EntityMap:compact()
  -- Run on the decoded World before afterLoad mutates entities. Reuse occupied
  -- cells/lists in place, preserving ordering and aliases; no second index.
  for x = 1, self.width do
    for y, cell in pairs(self.entity_map[x]) do
      if not cell.borrowed and #cell.humanoids == 0 and #cell.objects == 0 then
        self.entity_map[x][y] = nil
      end
    end
  end
end
'''

def transforms(root):
    path = 'CorsixTH/Lua/entity_map.lua'
    text = (root/path).read_text()
    if 'CORSIXTH_3DS_SPARSE_ENTITY_INDEX_R61' not in text:
        text = replace_exact(text, '''    for y = 1, self.height do
      self.entity_map[x][y] = {humanoids = {}, objects = {}}
    end
''', '    -- R61: occupied cells are created by writes only.\n', 'sparse constructor')
        # Separate writes from allocation-free borrowed queries. Keep the old
        # public mutable get APIs for extensions and callers holding an alias.
        for kind, field in (('Humanoids', 'humanoids'), ('Objects', 'objects')):
            text = text.replace('self:get'+kind+'AtCoordinate(', 'self:peek'+kind+'AtCoordinate(')
            text = replace_exact(text,
                'add_entity_to_table(entity, self:peek'+kind+'AtCoordinate(x, y))',
                'add_entity_to_table(entity, self:_cell(x, y, true).'+field+')',
                'owned entity insertion')
            text = replace_exact(text,
                '  return self.entity_map[x][y]["'+field+'"]',
                '  local cell = self:_cell(x, y, true)\n  cell.borrowed = true\n  return cell.'+field,
                'legacy mutable entity alias')
        start = text.index('function EntityMap:removeEntity(')
        end = text.index('\nend', start)
        text = text[:end] + '''
  if x and y and entity then
    local row = self.entity_map[x]
    local cell = row and row[y]
    if cell and not cell.borrowed and #cell.humanoids == 0 and #cell.objects == 0 then
      self.entity_map[x][y] = nil
    end
  end''' + text[end:]
        text += METHODS
    yield path, text
