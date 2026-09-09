"""Select the ordinary Lua reader only for the platform App resource branch."""
from sound_lifetime import replace_exact

OLD = '  local data = assert(self.fs:readContents(dir .. pathsep .. filename))'
NEW = '''  -- CORSIXTH_3DS_RESOURCE_READ_R70: provider and meta-directories retain their reader.
  local path = dir .. pathsep .. filename
  local data
  if IS_3DS and not self.fs.provider then
    data = assert(require("3ds.resource_read").read(self.fs, path))
  else
    data = assert(self.fs:readContents(path))
  end'''


def transforms(root):
    name = 'CorsixTH/Lua/app.lua'
    text = (root / name).read_text()
    if NEW not in text:
        text = replace_exact(text, OLD, NEW, 'platform ordinary resource reader')
    yield name, text
