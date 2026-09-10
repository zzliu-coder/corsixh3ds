#!/usr/bin/env python3
"""Prepare bound R63 config for the existing runner. Never connects or uploads."""
import argparse
import hashlib
import json
from pathlib import Path

CONTINUITY_SHA='17b74375444d153599873bf25255b0d6a817343382eed1ebab6d3d89dce3a808'
CAPACITY_ASSETS={
    'LEVEL.L1':'c792571dfaeee2b44fca9f3d5100e3baf878580657d471c10f24ba23ff032253',
    'LEVEL.L12':'e0c70a7c5d7034b63063901487b94c7b2924b6cf972c7a773f70175e89b407d8',
    'FULL00.SAM':'03ef32ce27867196ac5991025de59d658254e3287cf4c9dd73a7c3824bddfd2b',
    'FULL12.SAM':'38beafde190313e57034bc8295a07660921c4d7c67568850a57a3f6c4cc27f0b'}

def capacity_fields(args,base):
    if not (getattr(args,'capacity',False) or getattr(args,'busy_capacity',False)): return {}
    if args.profile!='expanded-zh-on' or args.recovery or not 0<args.stress_ms<=180000:
        raise ValueError('capacity requires expanded-zh-on, stress 1..180000, and no recovery')
    def bound(relative,expected):
        path=base/relative
        if not path.resolve().is_relative_to(base) or any((base/Path(*path.relative_to(base).parts[:i])).is_symlink()
                for i in range(1,len(path.relative_to(base).parts)+1)):
            raise ValueError('capacity dependency escapes installed tree or uses symlink')
        if sha(path)!=expected: raise ValueError('capacity dependency identity mismatch: '+relative)
    bound('Benchmark/continuity.sav',CONTINUITY_SHA)
    bound('Benchmark/expanded.sav','f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7')
    fields={'capacity':'r74-v1' if getattr(args,'busy_capacity',False) else 'r73-v1',
            'continuity_sha256':CONTINUITY_SHA}
    for i,(name,digest) in enumerate(CAPACITY_ASSETS.items(),1):
        relative='game/LEVELS/'+name
        bound(relative,digest)
        fields['verify_'+str(i)]=digest+'|sdmc:/3ds/corsixth/'+relative
    return fields

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):digest.update(block)
    return digest.hexdigest()

def prepare(args):
    base=args.installed_tree.resolve()
    interactive=getattr(args,'interactive',False)
    interactive_input=getattr(args,'interactive_input',None)
    if interactive:
        if (args.profile!='zh-on' or args.stress_ms!=0 or args.recovery or
            getattr(args,'capacity',False) or getattr(args,'busy_capacity',False) or
            interactive_input is None):
            raise ValueError('interactive requires zh-on, explicit healthy input, zero stress and no capacity/recovery')
        if not interactive_input.is_file() or interactive_input.is_symlink():
            raise ValueError('interactive input must be a regular non-symlink save')
    elif interactive_input is not None:
        raise ValueError('interactive input requires interactive mode')
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
    fields.update(capacity_fields(args,base))
    if interactive: fields['interactive']='r74-v1'
    args.out.mkdir(parents=True,exist_ok=False)
    config=args.out/'config.bin'
    config.write_text(''.join(k+'='+v+'\n' for k,v in sorted(fields.items())))
    # Input remains a verified healthy save; copies are owned by runner.prepare.
    input_path=interactive_input.resolve() if interactive else base/'Benchmark/input.sav'
    receipt_path=args.out/'preparation.json'
    receipt_path.write_text(json.dumps({'config':str(config.resolve()),'config_sha256':sha(config),
        'input':str(input_path),'input_sha256':sha(input_path),'assets_full_reverified':False,
        'lua_files':len(rows),'profile':args.profile,'command':[
            'python3','PATH/TO/old3ds-runner/host/runner.py','--host','DEVICE_IP','run',
            '--artifact','CANDIDATE.3dsx','--config',str(config.resolve()),'--input',str(input_path),
            '--launcher-sha','VERIFIED_LAUNCHER_SHA256','--out',str(args.out.resolve()/'runs'),
            '--timeout',str(1800 if interactive else 300+(args.warmup_ms+args.sample_ms)*(4 if args.profile=='matrix' else 1)//1000+args.stress_ms//1000
                +(545 if getattr(args,'capacity',False) or getattr(args,'busy_capacity',False) else 0)
                +(300 if getattr(args,'busy_capacity',False) else 0))
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
    parser.add_argument('--capacity',action='store_true',help='R73 bounded continuity and normal level 12 loading; requires expanded profile and stress 1..180000')
    parser.add_argument('--busy-capacity',action='store_true',help='R74 capacity: real hiring to 43 staff, two normal work windows and private save UI/reload, then R73 level/return checks')
    parser.add_argument('--interactive',action='store_true',help='Prepare private ordinary play; result requires human confirmation, never PASS. Does not submit.')
    parser.add_argument('--interactive-input',type=Path,help='Explicit healthy save copied by runner into private save/Acceptance.sav')
    parser.add_argument('--out',type=Path,required=True)
    print(prepare(parser.parse_args()))

if __name__=='__main__':main()
