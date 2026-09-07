"""Bounded slow-resource identities at real cold loads; hot cache hits stay direct."""

GRAPHICS = '''
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

def transforms(root):
    for path,fragment in (('CorsixTH/Lua/graphics.lua',GRAPHICS),
                          ('CorsixTH/Lua/app.lua',APP)):
        text=(root/path).read_text()
        if fragment.strip() not in text:
            text=text.rstrip()+'\n'+fragment
        yield path,text
