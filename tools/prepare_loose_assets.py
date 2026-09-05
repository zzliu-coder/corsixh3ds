#!/usr/bin/env python3
"""Prepare the original English consumer paths in an owned staging tree.

Inputs are read-only. Whole-bank RNC expansion is host-only, using the pinned
upstream CLI; the device receives the same DAT format, never a new container.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from th3ds_assets import build_language_bundle, _find_case_insensitive
from th3ds_sound import parse_sound_archive
from th3ds_resource import ResourceError

PIN = '56bd5d00f76331c7f76d7b696726a7926303ca0c'
LIMIT = 3 * 1024 * 1024

def digest(data):
    return hashlib.sha256(data).hexdigest()

def parse_original_sound(data):
    """Validate actual DAT indices, keeping exact aliases and reserved slot 0.

    The strict shared parser receives a deduplicated table view. This view is
    never deployed; source indices and bytes remain the game's original ones.
    Conflicting aliases and partial overlaps remain hard errors.
    """
    if len(data)<238:
        raise ResourceError('sound bank header truncated')
    u32=lambda offset:struct.unpack_from('<I',data,offset)[0]
    h=u32(len(data)-4)
    if h+234>len(data)-4: raise ResourceError('sound header outside file')
    t,n=u32(h+50),u32(h+58)
    if not n or n%32 or n//32>4096 or t+n>len(data)-4 or (t<h+234 and h<t+n):
        raise ResourceError('sound table bounds/count invalid')
    first=int(data[t:t+18]==bytes(18))
    unique=[];mapping=[];known={}
    for i in range(first,n//32):
        e=data[t+i*32:t+(i+1)*32]
        key=(e[:18].split(bytes(1))[0].lower(),u32(t+i*32+18),u32(t+i*32+26))
        if key not in known:
            known[key]=len(unique);unique.append(e)
        mapping.append((i,known[key]))
    view=bytearray(data)
    view[t:t+len(unique)*32]=b''.join(unique)
    struct.pack_into('<I',view,h+58,len(unique)*32)
    validated=parse_sound_archive(bytes(view))
    return [validated[k] for _,k in mapping],[i for i,_ in mapping],first

def prepare(runtime: Path, game: Path, stage: Path, language='English', upstream=None):
    if language.casefold() not in ('english', 'en'):
        raise ResourceError('First playable candidate requires English')
    for source in (runtime, game):
        if stage.resolve() == source.resolve() or stage.resolve() in source.resolve().parents or source.resolve() in stage.resolve().parents:
            raise ResourceError('staging must be separate from input trees')
    closure = build_language_bundle(runtime / 'Lua/languages', 'English', game)
    sound = _find_case_insensitive(game, 'SOUND/DATA/SOUND-0.DAT')
    if sound is None:
        raise ResourceError('missing SOUND/DATA/SOUND-0.DAT')
    original = sound.read_bytes()
    data = original
    rnc_tool = None
    if data[:3] == b'RNC':
        if upstream is None:
            raise ResourceError('RNC bank requires pinned upstream host CLI')
        head = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
        if head != PIN:
            raise ResourceError('RNC tool upstream commit mismatch')
        with tempfile.TemporaryDirectory(prefix='loose-rnc-', dir=stage.parent) as temp:
            temp = Path(temp)
            sources = ['tools/rnc/rnc_decode_cli.cpp', 'libs/rnc/rnc.cpp']
            for name in sources + ['libs/rnc/rnc.h']:
                expected = subprocess.check_output(['git', '-C', str(upstream), 'show', f'{PIN}:{name}'])
                if (upstream / name).read_bytes() != expected:
                    raise ResourceError('RNC tool source differs from pin: ' + name)
            cli = temp / 'rnc_decode'
            subprocess.run(['c++', '-std=c++17', '-O2', '-I'+str(upstream/'libs/rnc'), *[str(upstream/s) for s in sources], '-o', str(cli)], check=True)
            rnc_tool = {'upstream': PIN, 'source_sha256': {s:digest((upstream/s).read_bytes()) for s in sources}}
            subprocess.run([str(cli), str(sound), str(temp/'decoded.dat')], check=True)
            data = (temp/'decoded.dat').read_bytes()
    sounds, source_indices, first_index = parse_original_sound(data)
    if len(sounds) > 4096:
        raise ResourceError('sound metadata count exceeds 4096')
    # Native repeats this using Mix_QuerySpec and SDL_BuildAudioCVT; these
    # package estimates bind the default mixer configuration (22050 S16 stereo).
    metadata = len(sounds) * 128 + 8192
    rows = []
    for index, item in zip(source_indices,sounds):
        frames = len(item.pcm) // (item.channels * (item.bits_per_sample // 8))
        converted = ((frames * 22050 + item.sample_rate - 1)//item.sample_rate + 64) * 4
        if not item.pcm or converted + metadata + 32 > LIMIT:
            raise ResourceError(f'required clip exceeds PCM+metadata limit: {item.name}')
        rows.append({'index':index, 'name':item.name, 'source_pcm_bytes':len(item.pcm), 'converted_upper_bytes':converted, 'duration_ms':frames*1000//item.sample_rate})
    language_dir = stage/'Lua/languages'
    if language_dir.is_symlink():
        raise ResourceError('staged language directory may not be symlink')
    language_dir.mkdir(parents=True, exist_ok=True)
    selected = {Path(name).name:payload for name,payload in closure.files if name.endswith('.lua')}
    for path in language_dir.glob('*.lua'):
        path.unlink()
    for name,payload in selected.items():
        (language_dir/name).write_bytes(payload)
    staged_sound = _find_case_insensitive(stage/'game', 'SOUND/DATA/SOUND-0.DAT')
    if staged_sound is None or staged_sound.is_symlink():
        raise ResourceError('loose game staging must contain a regular SOUND-0.DAT')
    staged_sound.write_bytes(data)
    report = {'schema':'corsixth.loose-assets.v1','language':closure.selected,
              'language_files':{k:digest(v) for k,v in selected.items()},
              'original_string_ids':list(closure.original_ids),
              'sound_source_sha256':digest(original),'sound_staged_sha256':digest(data),
              'sound_source_bytes':len(original),'sound_staged_bytes':len(data),
              'rnc_tool':rnc_tool,'sound_count':len(sounds)+first_index,'reserved_zero_slot':bool(first_index),'metadata_upper_bytes':metadata,
              'pcm_limit_bytes':LIMIT,'mixer':{'frequency':22050,'format':'S16','channels':2},
              'sounds':rows,'device':'NOT_PROVEN'}
    (stage/'loose-assets.json').write_text(json.dumps(report, indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser()
    for name in ('runtime','game','stage','upstream'):
        p.add_argument('--'+name, type=Path, required=name!='upstream')
    p.add_argument('--language',default='English')
    a=p.parse_args()
    try:
        report=prepare(a.runtime,a.game,a.stage,a.language,a.upstream)
        print(json.dumps({'sound_count':report['sound_count'],'language_files':report['language_files']}))
    except (ResourceError, OSError, subprocess.CalledProcessError) as e:
        p.exit(2, str(e)+'\n')
if __name__=='__main__':
    main()
