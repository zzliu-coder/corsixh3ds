"""Bounded slow-resource identities at real cold loads; hot cache hits stay direct."""
from sound_lifetime import SoundPatchError

LEGACY_GRAPHICS = '''
-- CORSIXTH_3DS_COLD_RESOURCE_TRACE_R56
do
  local raw, sheet = Graphics.loadRaw, Graphics.loadSpriteTable
  function Graphics:loadRaw(name, ...)
    if not TH3DS or not TH3DS.trace_call or self.cache.raw[name] then
      return raw(self, name, ...)
    end
    return TH3DS.trace_call("raw-image", name, raw, self, name, ...)
  end
  function Graphics:loadSpriteTable(dir, name, ...)
    if not TH3DS or not TH3DS.trace_call or self.cache.tabled[name] then
      return sheet(self, dir, name, ...)
    end
    return TH3DS.trace_call("sprite-sheet", dir .. "/" .. name, sheet, self, dir, name, ...)
  end
end
'''
GRAPHICS = LEGACY_GRAPHICS.replace('  function Graphics:loadRaw(name, ...)\n', '''  -- CORSIXTH_3DS_HOT_CACHE_R58: cached identities bypass nested observers.
  function Graphics:loadRaw(name, ...)
    if TH3DS and self.cache.raw[name] then return self.cache.raw[name] end
''').replace('  function Graphics:loadSpriteTable(dir, name, ...)\n', '''  function Graphics:loadSpriteTable(dir, name, ...)
    if TH3DS and self.cache.tabled[name] then return self.cache.tabled[name] end
''')
APP = '''
-- CORSIXTH_3DS_RESOURCE_READ_TRACE_R56
do
  local read = App.readDataFile
  function App:readDataFile(dir, filename)
    if not TH3DS or not TH3DS.trace_call then return read(self, dir, filename) end
    return TH3DS.trace_call("resource-read", tostring(dir) .. "/" .. tostring(filename),
      read, self, dir, filename)
  end
end
'''

RETAINED_R60_GRAPHICS = GRAPHICS.replace(
    '  -- CORSIXTH_3DS_HOT_CACHE_R58: cached identities bypass nested observers.',
    '  -- CORSIXTH_3DS_HOT_CACHE_R58: hit returns the original cached identity,\n'
    '  -- before nested pcall/span/allocator observers. Cold loads retain full traces.')

def transforms(root):
    for path,fragment in (('CorsixTH/Lua/graphics.lua',GRAPHICS),
                          ('CorsixTH/Lua/app.lua',APP)):
        text=(root/path).read_text()
        if fragment == GRAPHICS:
            # Normalize all known retained wrappers to exactly one owner.
            for known in (GRAPHICS, LEGACY_GRAPHICS, RETAINED_R60_GRAPHICS):
                text=text.replace(known.strip(), '')
            if 'CORSIXTH_3DS_COLD_RESOURCE_TRACE_R56' in text:
                raise SoundPatchError('unknown cold-resource wrapper; cannot normalize safely')
            text=text.rstrip()+'\n'+GRAPHICS
        elif fragment.strip() not in text:
            text=text.rstrip()+'\n'+fragment
        yield path,text
