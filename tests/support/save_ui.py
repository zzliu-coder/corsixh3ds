"""Unchanged pinned UI infrastructure plus the final generated save module.

The compact ordinary assembly fixture intentionally has only 44 patch inputs.
These unchanged infrastructure chunks are separately pinned and hash checked;
the save and load modules always come from the current full patch pipeline.
"""
import base64
import hashlib
import json
from pathlib import Path
import zlib
import handheld_ui

ROOT = Path(__file__).resolve().parents[2]


def install_ui_infrastructure(generated):
    fixture = json.loads((ROOT/'tests/fixtures/save_ui_modules.json').read_text())
    assert fixture['commit'] == '56bd5d00f76331c7f76d7b696726a7926303ca0c'
    sources = json.loads(zlib.decompress(base64.b64decode(fixture['sources'])))
    assert sources.keys() == fixture['sha256'].keys()
    for name, source in sources.items():
        data = source.encode()
        assert hashlib.sha256(data).hexdigest() == fixture['sha256'][name]
        transform_name={'window.lua':'transform_textbox',
                        'dialogs/resizables/new_game.lua':'transform_player'}.get(name)
        transform=getattr(handheld_ui,transform_name,None) if transform_name else None
        if transform is not None:
            source=transform(source)
            assert transform(source)==source
            data=source.encode()
        target = generated/'CorsixTH/Lua'/name
        if target.exists():
            assert target.read_bytes() == data
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return generated/'CorsixTH/Lua'


def loader_source(generated):
    root = install_ui_infrastructure(generated)
    return ('local loadSaveUi = dofile('+repr(str(ROOT/'tests/runtime_support/save_ui_loader.lua'))+')\n'
            'local saveUi = loadSaveUi('+repr(str(root)) + ', {\n'
            ' information=function(...) return UIInformation(...) end})\n')
