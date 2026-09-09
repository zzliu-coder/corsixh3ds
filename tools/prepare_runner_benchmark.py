#!/usr/bin/env python3
"""Prepare bound R63 config for the existing runner. Never connects or uploads."""
import argparse
import hashlib
import json
from pathlib import Path

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):digest.update(block)
    return digest.hexdigest()

def prepare(args):
    base=args.installed_tree.resolve()
    rows=[]
    for path in sorted((base/'Lua').rglob('*.lua')):
        if path.is_symlink(): raise ValueError('Lua symlink forbidden')
        rows.append(path.relative_to(base/'Lua').as_posix()+'|'+sha(path)+'\n')
    if not rows: raise ValueError('empty Lua tree')
    if not 1000<=args.warmup_ms<=60000 or not 1000<=args.sample_ms<=60000:
        raise ValueError('warmup/sample must be 1000..60000 milliseconds')
    if not 0<=args.stress_ms<=1320000:raise ValueError('stress must be 0..1320000 milliseconds')
    receipt=args.assets_receipt_sha256
    if len(receipt)!=64 or any(c not in '0123456789abcdef' for c in receipt):
        raise ValueError('asset installation receipt SHA256 required')
    fields={'adapter':'corsixth-r63-v1','profile':args.profile,'stress_ms':str(args.stress_ms),
        'warmup_ms':str(args.warmup_ms),'sample_ms':str(args.sample_ms),
        'assets_receipt_sha256':receipt,'lua_tree_sha256':hashlib.sha256(''.join(sorted(rows)).encode()).hexdigest(),
        'player_config_sha256':sha(base/'config.txt')}
    # Require an installed small integration receipt in addition to the complete
    # Lua tree. Large music/archive bytes retain the original installation proof.
    integration=Path(args.integration_receipt)
    if integration.is_absolute() or '..' in integration.parts: raise ValueError('receipt must be relative to installed tree')
    fields['verify_0']=sha(base/integration)+'|sdmc:/3ds/corsixth/'+integration.as_posix()
    if args.profile in ('matrix','expanded-zh-on'):
        fields['expanded_sha256']=sha(base/'Benchmark/expanded.sav')
    if args.recovery:
        fields['recovery_sha256']=sha(base/'Benchmark/r62-recovery.sav')
    args.out.mkdir(parents=True,exist_ok=False)
    config=args.out/'config.bin'
    config.write_text(''.join(k+'='+v+'\n' for k,v in sorted(fields.items())))
    # Input remains a verified healthy save; copies are owned by runner.prepare.
    input_path=base/'Benchmark/input.sav'
    receipt_path=args.out/'preparation.json'
    receipt_path.write_text(json.dumps({'config':str(config.resolve()),'config_sha256':sha(config),
        'input':str(input_path),'input_sha256':sha(input_path),'assets_full_reverified':False,
        'lua_files':len(rows),'profile':args.profile,'command':[
            'python3','PATH/TO/old3ds-runner/host/runner.py','--host','DEVICE_IP','run',
            '--artifact','CANDIDATE.3dsx','--config',str(config.resolve()),'--input',str(input_path),
            '--launcher-sha','VERIFIED_LAUNCHER_SHA256','--out',str(args.out.resolve()/'runs'),
            '--timeout',str(300+(args.warmup_ms+args.sample_ms)*(4 if args.profile=='matrix' else 1)//1000+args.stress_ms//1000)
        ]},indent=2)+'\n')
    return receipt_path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-tree',type=Path,required=True)
    parser.add_argument('--integration-receipt',required=True)
    parser.add_argument('--assets-receipt-sha256',required=True)
    parser.add_argument('--profile',choices=['zh-on','expanded-zh-on','matrix'],default='zh-on')
    parser.add_argument('--warmup-ms',type=int,default=30000)
    parser.add_argument('--sample-ms',type=int,default=60000)
    parser.add_argument('--stress-ms',type=int,default=0)
    parser.add_argument('--recovery',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    print(prepare(parser.parse_args()))

if __name__=='__main__':main()
