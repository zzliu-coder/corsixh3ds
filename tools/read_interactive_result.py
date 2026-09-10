#!/usr/bin/env python3
"""Read a retained private interactive run locally. Never submits or retries jobs."""
import argparse
import hashlib
import json
from pathlib import Path
import re

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fields(path):
    data=path.read_bytes()
    if len(data)>16384 or b'\r' in data or b'\0' in data:raise ValueError('invalid KV size or bytes')
    result={}
    for line in data.decode('utf-8').splitlines():
        key,separator,value=line.partition('=')
        if not separator or not re.fullmatch('[a-z_0-9]+',key) or key in result:raise ValueError('invalid KV field')
        result[key]=value
    return result

def inspect(root):
    root=Path(root)
    manifest=fields(root/'manifest.kv');config=fields(root/'config.bin')
    if manifest.get('version')!='1' or config.get('interactive')!='r74-v1':raise ValueError('wrong interactive protocol')
    identity={key:manifest[key] for key in ('run_id','artifact_sha256','config_sha256','input_sha256')}
    identity['manifest_sha256']=digest(root/'manifest.kv')
    for filename,key in [('program.3dsx','artifact_sha256'),('config.bin','config_sha256'),('input.bin','input_sha256')]:
        if digest(root/filename)!=identity[key]:raise ValueError(filename+' identity mismatch')
    result=fields(root/'result.kv');receipt=fields(root/'receipt.kv');launch=fields(root/'launch.kv')
    for record in (result,receipt,launch):
        if record.get('version')!='1':raise ValueError('unknown record version')
        if any(record.get(k)!=v for k,v in identity.items()):raise ValueError('result/receipt/launch identity mismatch')
    if result.get('workload')!='corsixth-r74-interactive-v1' or result.get('phase')!='complete':
        raise ValueError('wrong workload or incomplete result')
    if result.get('outcome') not in ('FAIL','NOT_PROVEN'):raise ValueError('interactive PASS forbidden')
    if receipt.get('status')!='COMPLETED' or receipt.get('result_sha256')!=digest(root/'result.kv'):
        raise ValueError('launcher completion not bound to result')
    if receipt.get('outcome')!=result['outcome'] or receipt.get('launch_boot')!=launch.get('launch_boot'):
        raise ValueError('launcher outcome/boot mismatch')
    if not launch.get('launch_boot') or not receipt.get('return_boot') or receipt['return_boot']==launch['launch_boot']:
        raise ValueError('launcher reentry unproven')
    acceptance=root/'save/Acceptance.sav'
    acceptance_sha=digest(acceptance) if acceptance.is_file() else None
    log=root/'artifacts/boot.log'
    if not log.is_file():raise ValueError('private boot log missing')
    # Raw data is retained. A normal exit / frame count cannot prove HOME, sound,
    # touch, or simulation continuity. Human confirmation stays a separate gate.
    return {'outcome':result['outcome'],'reason':result['reason'],'identity':identity,
        'human_confirmation':'required','product_acceptance':'NOT_PROVEN',
        'original_save_protection':'NOT_PROVEN','boot_log_sha256':digest(log),
        'acceptance_save':{'present':acceptance_sha is not None,'current_sha256':acceptance_sha,
            'modified_from_input':acceptance_sha!=identity['input_sha256'] if acceptance_sha is not None else None},
        'save_files':{p.name:{'size':p.stat().st_size,'sha256':digest(p)}
                      for p in sorted((root/'save').glob('*.sav'))},
        'source_result':result,'source_receipt':receipt}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    args=parser.parse_args();print(json.dumps(inspect(args.run),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
