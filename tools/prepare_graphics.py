#!/usr/bin/env python3
"""Expand four measured cold RNC assets on the host, at their original paths.

No runtime lookup layer or new format. The pinned engine already accepts these
uncompressed DAT bytes. Original game files are read-only; output/tool caches
are reused only after source and result SHA-256 checks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

PIN='56bd5d00f76331c7f76d7b696726a7926303ca0c'
ASSETS=('DATA/VSPR-0.DAT','QDATA/RES01V.DAT','QDATA/POL01V.DAT','QDATA/REP01V.DAT')
SOURCES=('tools/rnc/rnc_decode_cli.cpp','libs/rnc/rnc.cpp','libs/rnc/rnc.h')

def sha(data):return hashlib.sha256(data).hexdigest()

def expected_size(data):
    if data[:3]!=b'RNC':return len(data)
    if len(data)<18 or data[3] not in (1,2):raise ValueError('invalid RNC header')
    expanded,packed=struct.unpack_from('>II',data,4)
    if not 0<expanded<=0xffffff or packed+18!=len(data):raise ValueError('invalid RNC lengths')
    return expanded

def prepare(game,stage,cache,upstream):
    game,stage,cache,upstream=(Path(p).resolve() for p in (game,stage,cache,upstream))
    for writable in (stage,cache):
        if writable==game or game in writable.parents or writable in game.parents:
            raise ValueError('output/cache must be separate from source game')
    source_hashes={}
    for name in SOURCES:
        expected=subprocess.check_output(['git','-C',str(upstream),'show',PIN+':'+name])
        actual=(upstream/name).read_bytes()
        if actual!=expected:raise ValueError('decoder source differs from fixed upstream: '+name)
        source_hashes[name]=sha(actual)
    compiler=shutil.which('c++');assert compiler,'host C++ compiler missing'
    compiler_id=subprocess.check_output([compiler,'--version'],text=True)
    key=sha(json.dumps([source_hashes,compiler_id,'-std=c++17 -O2'],sort_keys=True).encode())
    tool_dir=cache/key;tool_dir.mkdir(parents=True,exist_ok=True)
    cli=tool_dir/'rnc_decode';tool_record=tool_dir/'decoder.json'
    valid=cli.is_file() and tool_record.is_file()
    if valid:
        valid=json.loads(tool_record.read_text()).get('sha256')==sha(cli.read_bytes())
    if not valid:
        with tempfile.TemporaryDirectory(prefix='compile-',dir=tool_dir) as d:
            result=Path(d)/'rnc_decode'
            subprocess.run([compiler,'-std=c++17','-O2','-I'+str(upstream/'libs/rnc'),
                str(upstream/SOURCES[0]),str(upstream/SOURCES[1]),'-o',str(result)],check=True)
            os.replace(result,cli)
        tool_record.write_text(json.dumps({'sha256':sha(cli.read_bytes()),'sources':source_hashes})+'\n')
    rows=[]
    for name in ASSETS:
        source=game/name
        if source.is_symlink():raise ValueError('source symlink refused: '+name)
        data=source.read_bytes();size=expected_size(data);source_hash=sha(data)
        entry=tool_dir/(source_hash+'.dat');record=tool_dir/(source_hash+'.json')
        reused=False
        if entry.is_file() and record.is_file():
            metadata=json.loads(record.read_text());decoded=entry.read_bytes()
            reused=(metadata.get('source_sha256')==source_hash and len(decoded)==size and
                    metadata.get('sha256')==sha(decoded))
        if not reused:
            with tempfile.TemporaryDirectory(prefix='decode-',dir=tool_dir) as d:
                target=Path(d)/'decoded.dat'
                if data[:3]==b'RNC':subprocess.run([str(cli),str(source),str(target)],check=True)
                else:target.write_bytes(data)
                decoded=target.read_bytes()
                if len(decoded)!=size:raise ValueError('decoded size mismatch: '+name)
                os.replace(target,entry)
            record.write_text(json.dumps({'source_sha256':source_hash,'sha256':sha(decoded)})+'\n')
        target=stage/'game'/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_symlink():raise ValueError('output symlink refused: '+name)
        if not target.exists() or sha(target.read_bytes())!=sha(decoded):shutil.copy2(entry,target)
        rows.append({'path':'game/'+name,'source_sha256':source_hash,'sha256':sha(decoded),
                     'source_bytes':len(data),'size':len(decoded),'cache_reused':reused})
    result={'schema':'cth3ds-preexpanded-graphics-v1','upstream':PIN,'decoder_key':key,
            'files':rows,'runtime_path':'original DAT path; existing raw-or-RNC loader',
            'hardware_startup_gain':'NOT_PROVEN'}
    stage.mkdir(parents=True,exist_ok=True)
    (stage/'preexpanded-graphics.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('game','stage','cache','upstream'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();print(json.dumps(prepare(a.game,a.stage,a.cache,a.upstream),indent=2))
