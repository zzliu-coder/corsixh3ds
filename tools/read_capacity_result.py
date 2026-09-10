"""Read-only manifest-bound R73/R74/R75 capacity evidence consumer.

Retains historical capacity acceptance checks; adds R75 same-byte writer A/B.
JSON stdout only: no file writes, network, repair, or automatic PASS promotion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

SHA='17b74375444d153599873bf25255b0d6a817343382eed1ebab6d3d89dce3a808'
STAGES=('continuity_before','continuity_loaded','reception_before_save','reception_reloaded',
        'busy_before','busy_loaded','busy_reloaded','busy_complete',
        'level_before','level_loaded','level_ran','level_reloaded','expanded_returned','complete')
NATIVE={'version','run_id','artifact_sha256','config_sha256','input_sha256','manifest_sha256',
        'checkpoint_sequence','snapshot_complete'}
TERMINAL={'phase','outcome','reason','workload','assets_full_reverified','assets_receipt_sha256'}

IO_STAGES=('save_io_loaded','save_io_worked','save_io_reloaded')
IDENTITY=('version','run_id','artifact_sha256','config_sha256','input_sha256')
HASH=re.compile(r'[0-9a-f]{64}\Z')

def sha(data):return hashlib.sha256(data).hexdigest()
def packed(value):
    out={}
    for item in value.split(';'):
        key,sep,val=item.partition('=')
        if not sep or key in out:raise ValueError('invalid packed field')
        out[key]=val
    return out
def kv(data):
    if not data or len(data)>16384 or not data.endswith(b'\n'):raise ValueError('KV length/termination')
    out={}
    for line in data.decode().splitlines():
        key,sep,value=line.partition('=')
        if not sep or not re.fullmatch('[a-z_0-9]{1,64}',key) or key in out or '\0' in value or '\r' in value or len(value.encode())>1024:
            raise ValueError('KV field bound or duplicate')
        out[key]=value
    return out
def lua_bound(fields):
    if len(fields)>128 or sum(len(k.encode())+len(v.encode())+2 for k,v in fields.items())>12000:
        raise ValueError('Lua 128/12000 field budget')
def positive(row,*keys):return all(re.fullmatch(r'[0-9]+',row.get(k,'')) and int(row[k])>0 for k in keys)

def _capacity(directory,canonical):
    directory=Path(directory);errors=[];missing=[];checks=[];result={};config={};mf={}
    stages_expected=STAGES;protocol='unknown';checkpoint_cap=22
    def read(name,required=True):
        p=directory/name
        if not p.is_file():
            if required:missing.append(name)
            return {}
        return kv(p.read_bytes())
    try:
        mf=read('manifest.kv');config=read('config.bin');result=read('result.kv',False)
        if not result:missing.append('result.kv')
        protocol=config.get('capacity')
        if protocol not in ('r73-v1','r74-v1','r75-v1') or config.get('continuity_sha256')!=SHA:raise ValueError('capacity config SHA binding')
        stages_expected=tuple(s for s in STAGES if protocol!='r73-v1' or not s.startswith('busy_'))
        if protocol=='r75-v1':stages_expected=IO_STAGES+stages_expected
        checkpoint_cap=22 if protocol=='r75-v1' else 19 if protocol=='r74-v1' else 15
        if mf.get('config_sha256')!=sha((directory/'config.bin').read_bytes()):raise ValueError('config manifest SHA')
        if result:lua_bound({k:v for k,v in result.items() if k not in NATIVE|TERMINAL})
        files=sorted((directory/'artifacts').glob('progress-*.kv'))
        if len(files)>checkpoint_cap:raise ValueError('capacity recipe checkpoint cap')
        for i,path in enumerate(files,1):
            f=kv(path.read_bytes());lua_bound({k:v for k,v in f.items() if k not in NATIVE})
            if path.name!=f'progress-{i:04d}.kv' or f.get('checkpoint_sequence')!=str(i) or f.get('snapshot_complete')!='1':raise ValueError('checkpoint sequence/completion')
            if any(f.get(k)!=mf.get(k) for k in ('version','run_id','artifact_sha256','config_sha256','input_sha256')) or f.get('manifest_sha256')!=sha((directory/'manifest.kv').read_bytes()):raise ValueError('checkpoint identity SHA')
            if f.get('phase')=='capacity':
                stage=f.get('capacity_stage','')
                if stage not in stages_expected or any('capacity_'+stage+s not in f for s in ('','_memory')):
                    raise ValueError('capacity checkpoint missing current snapshot')
            checks.append(f)
        if any((directory/'artifacts').glob('progress*.tmp')):missing.append('partial checkpoint')
    except (ValueError,OSError,UnicodeError) as exc:errors.append(str(exc))
    stages=[f.get('capacity_stage') for f in checks if f.get('phase')=='capacity']
    if stages!=list(stages_expected):missing.append('fourteen ordered capacity boundaries')
    if result.get('capacity_stage')!='complete':missing.append('capacity complete terminal')
    for stage in stages_expected:
        if stage in IO_STAGES:continue
        for suffix in ('','_memory'):
            key='capacity_'+stage+suffix
            if key not in result:missing.append(key)
            elif checks and key in checks[-1] and result[key]!=checks[-1][key]:errors.append('terminal/checkpoint divergence '+key)
    for name in (('r73-continuity.sav','r73-level12.sav') if protocol=='r73-v1' else ('r73-continuity.sav','r74-busy.sav','r73-level12.sav')):
        if not (directory/'save'/name).is_file():missing.append('private save '+name)
    if result and result.get('capacity_input_sha256')!=SHA:errors.append('result continuity SHA mismatch')
    if result.get('capacity_continuity_roundtrip')!='PASS':missing.append('continuity roundtrip')
    level='NOT_PROVEN';returned='NOT_PROVEN';reception='NOT_PROVEN'
    work={};addresses={}
    # Coverage is phase-local: a lost healthy cohort deliberately omits the
    # second reception window and still runs the normal level/return phases.
    for phase,duration in (('reception_1',180000),('reception_2',180000),('level_run',60000),('return_run',5000)):
        try:
            row=packed(result['capacity_'+phase+'_work'])
            work[phase]=positive(row,'world','hours','frames') and float(row.get('elapsed_ms','0'))>=duration
            if not work[phase]:errors.append('no complete simulation/presentation '+phase)
        except (ValueError,KeyError) as exc:
            work[phase]=False;missing.append('capacity work '+phase+': '+str(exc))
    try:
        for key in ('capacity_level_loaded','capacity_level_ran','capacity_level_reloaded'):
            row=packed(result[key])
            if (row.get('level'),row.get('difficulty'))!=('12','full'):errors.append('actual level mismatch')
        before=packed(result['capacity_level_before']);loaded=packed(result['capacity_level_loaded'])
        # tostring addresses are historical strings. After old strong roots
        # are cleared, GC can recycle a world address; live producer assertions
        # compare actual objects/weak references and remain authoritative.
        addresses={k:{'before':before.get(k),'loaded':loaded.get(k),'same_text':before.get(k)==loaded.get(k)} for k in ('world','map')}
        if result.get('capacity_level_outcome')=='PASS' and work['level_run'] and (directory/'save/r73-level12.sav').is_file():level='PASS'
    except (ValueError,KeyError) as exc:missing.append('level evidence: '+str(exc))
    try:
        initial=packed(result['capacity_continuity_before']);back=packed(result['capacity_expanded_returned'])
        if any(not initial.get(k) or initial[k]!=back.get(k) for k in ('level','difficulty','rooms')):
            errors.append('expanded return scene differs')
        if result.get('capacity_return_outcome')=='PASS' and work['return_run']:returned='PASS'
    except (ValueError,KeyError) as exc:missing.append('return evidence: '+str(exc))
    try:
        windows=[packed(result['capacity_reception_'+str(i)]) for i in (1,2)]
        cohort=all(w.get('updated')==w.get('count')=='17' and w.get('identity')=='PASS' and w.get('partial')=='false' for w in windows)
        services=packed(result.get('capacity_patient_services',''))
        logs=list((directory/'artifacts').rglob('boot.log'))
        events=set();activity={}
        if len(logs)==1:
            lines=logs[0].read_text(errors='strict').splitlines();parts={}
            for line in lines:
                if 'capacity-activity: ' in line:
                    f=dict(re.findall(r'(\w+)=(\S+)',line.split('capacity-activity: ',1)[1]))
                    key=(f.get('window'),f.get('source'))
                    if key in activity:raise ValueError('duplicate capacity activity')
                    activity[key]=f
                    if int(f.get('failures','0')):errors.append('capacity entity failure')
                if 'capacity-service: ' not in line:continue
                f=dict(re.findall(r'(\w+)=(\S+)',line.split('capacity-service: ',1)[1]));key=tuple(f.get(k) for k in ('window','event','source'))
                d=parts.setdefault(key,{})
                for k,v in f.items():
                    if k not in ('window','event','source') and k in d:raise ValueError('duplicate capacity service field')
                    d[k]=v
            for (window,event,source),d in parts.items():
                if d.get('head')=='Patient' and d.get('same')=='true' and d.get('passed_after')=='true' and d.get('id') and d.get('owner') and 'action' in d and 'next' in d and 'tail' in d and int(d.get('after','0'))>int(d.get('before','0')):
                    events.add(source)
        source_ids={str(i) for i in range(9,25)}|{'45'}
        cohort=cohort and all((str(w),s) in activity and int(activity[str(w),s].get('ticks','0'))>0 for w in (1,2) for s in source_ids)
        if cohort and work['reception_1'] and work['reception_2'] and positive(services,'15','20') and {'15','20'}<=events and result.get('capacity_reception_outcome')=='PASS':reception='PASS'
    except (ValueError,KeyError,OSError,UnicodeError) as exc:missing.append(str(exc))
    busy='NOT_REQUESTED';busy_work={}
    if protocol!='r73-v1':
        busy='NOT_PROVEN'
        busy_work={}
        try:
            if result.get('capacity_protocol')!=protocol:raise ValueError('result busy protocol mismatch')
            for phase,duration in (('busy_recruit',1),('busy_1',60000),('busy_2',60000)):
                row=packed(result['capacity_'+phase+'_work'])
                valid=positive(row,'world','hours','entities','frames','elapsed_us')
                valid=valid and int(row['elapsed_ms'])>=duration and row['nominal_timer_us']=='18000'
                valid=valid and row['world_tick_rate']=='3' and row['hours_per_tick']=='1'
                valid=valid and row['failed_steps']=='0'
                valid=valid and all(re.fullmatch(r'[0-9]+',row.get(k,'')) for k in
                    ('debt_before_us','debt_after_us','dropped_us','rebases','budget_exits','completed_steps'))
                busy_work[phase]={'valid':bool(valid),'raw':row}
                if not valid:raise ValueError('busy normal work boundary invalid '+phase)
            cohorts=[]
            for window in (1,2):
                row=packed(result['capacity_busy_'+str(window)+'_activity'])
                count=int(row['count'])
                if not 40<=count<=45 or row['updated']!=row['count'] or row['identity']!='PASS' or row['partial']!='false':
                    raise ValueError('busy activity count/identity incomplete')
                if row['outcome']=='FAIL':raise ValueError('busy observed entity failure')
                cohorts.append(count)
            observations={1:{},2:{}}
            logs=list((directory/'artifacts').rglob('boot.log'))
            if len(logs)!=1:raise KeyError('one raw busy activity log required')
            for line in logs[0].read_text(errors='strict').splitlines():
                if 'capacity-busy: ' not in line:continue
                row=dict(re.findall(r'(\w+)=(\S+)',line.split('capacity-busy: ',1)[1]))
                window=int(row['window']);key=row['source']
                if window not in observations or key in observations[window]:raise ValueError('duplicate busy activity identity')
                observations[window][key]=row
                if not positive(row,'ticks') or row['failures']!='0' or row['partial_timer']!='0':
                    raise ValueError('busy employee has no healthy completed work')
            if any(len(observations[w])!=cohorts[w-1] for w in (1,2)):raise KeyError('busy employee rows incomplete')
            if set(observations[1])!=set(observations[2]):raise ValueError('busy reloaded cohort mismatch')
            for stage in ('busy_loaded','busy_reloaded','busy_complete'):
                if not 40<=int(packed(result['capacity_'+stage])['staff'])<=45:raise ValueError('busy snapshot population')
            entry='UISaveGame.confirmName/trySave/doSave'
            if result.get('capacity_busy_save_entry')!=entry or result.get('capacity_busy_save_ui')!='PASS':
                raise KeyError('real private save UI completion')
            if result.get('capacity_busy_roundtrip')!='PASS' or not (directory/'save/r74-busy.sav').is_file():
                raise KeyError('private busy save/reload')
            if result.get('capacity_busy_hospital')=='PASS':busy='PASS'
        except ValueError as exc:
            errors.append('busy hospital: '+str(exc))
        except (KeyError,OSError,UnicodeError) as exc:
            missing.append('busy hospital: '+str(exc))
    terminal=result.get('outcome')
    failed=terminal=='FAIL' or result.get('capacity_failure_outcome')=='FAIL' or canonical.get('game_outcome')=='FAIL'
    binding=canonical.get('identity')=='PASS' and canonical.get('launcher_roundtrip')=='PASS'
    if not binding:missing.append('canonical identity/runner return')
    if canonical.get('log',{}).get('runtime_write_status')!='PASS':missing.append('complete diagnostic log write evidence')
    outcome='FAIL' if errors or failed else 'PASS' if not missing and terminal=='PASS' and canonical.get('game_outcome')=='PASS' and level==returned=='PASS' and busy in ('PASS','NOT_REQUESTED') else 'NOT_PROVEN'
    trusted=not errors and not failed and binding and terminal=='PASS' and canonical.get('game_outcome')=='PASS' and canonical.get('log',{}).get('runtime_write_status')=='PASS'
    ordered=stages==[s for s in stages_expected if s in stages]
    def complete_stage(stage):
        key='capacity_'+stage
        return stage in stages and all(key+s in result and checks and checks[-1].get(key+s)==result[key+s] for s in ('','_memory'))
    if not trusted or not ordered:level=returned=reception=busy='NOT_PROVEN'
    else:
        if not all(complete_stage(s) for s in ('level_before','level_loaded','level_ran','level_reloaded')):level='NOT_PROVEN'
        if not all(complete_stage(s) for s in ('continuity_before','expanded_returned','complete')):returned='NOT_PROVEN'
        if not all(complete_stage(s) for s in ('continuity_loaded','reception_before_save','reception_reloaded')) or result.get('capacity_continuity_roundtrip')!='PASS' or not (directory/'save/r73-continuity.sav').is_file():reception='NOT_PROVEN'
    return {'schema':'cth3ds-capacity-readback-v1','protocol':protocol,'outcome':outcome,'errors':errors,'missing':sorted(set(missing)),
        'terminal_outcome':terminal,'terminal_reason':result.get('reason'),'checkpoints':len(checks),'checkpoint_cap':checkpoint_cap,
        'stages':stages,'reception':reception,'level_load':level,'expanded_return':returned,
        'address_observation':{'scope':'auxiliary historical text; not object identity proof','values':addresses},
        'lua_release':result.get('capacity_lua_release_outcome','NOT_PROVEN') if outcome=='PASS' else 'NOT_PROVEN',
        'native_gpu_release':'NOT_PROVEN','largest_contiguous_allocation':'NOT_PROVEN','busy_hospital':busy,'busy_work':busy_work,
        'fps_acceptance_gate':False,'device_acceptance':'NOT_PROVEN unless bound actual device evidence supplied'}


def _uint(value, label='integer'):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,20}',value) or int(value)>2**64-1:
        raise ValueError('invalid '+label)
    return int(value)


def _fields(text):
    pairs=re.findall(r'(\w+)=([^\s]+)',text)
    if len(pairs)!=len({key for key,_ in pairs}):raise ValueError('duplicate log field')
    return dict(pairs)


def _identity(directory):
    errors=[];missing=[];records={};raw={}
    names=('manifest.kv','config.bin','result.kv','receipt.kv','device-before.kv','device-after.kv')
    for name in names:
        path=directory/name
        if not path.is_file():missing.append(name);records[name]={};continue
        try:raw[name]=path.read_bytes();records[name]=kv(raw[name])
        except (ValueError,UnicodeError,OSError) as exc:errors.append(name+': '+str(exc));records[name]={}
    mf=records['manifest.kv'];r=records['result.kv'];receipt=records['receipt.kv'];config=records['config.bin']
    if mf and (set(mf)!=set(IDENTITY) or mf.get('version')!='1' or
               not re.fullmatch('[a-z0-9-]{8,64}',mf.get('run_id','')) or
               not all(HASH.fullmatch(mf.get(k,'')) for k in IDENTITY[2:])):
        errors.append('invalid manifest identity')
    for name in ('result.kv','receipt.kv'):
        row=records[name]
        if row and (any(row.get(k)!=mf.get(k) for k in IDENTITY) or row.get('manifest_sha256')!=sha(raw.get('manifest.kv',b''))):
            errors.append(name+' identity mismatch')
    if raw.get('config.bin') and sha(raw['config.bin'])!=mf.get('config_sha256'):errors.append('config SHA mismatch')
    artifacts={}
    for name,key in (('program.3dsx','artifact_sha256'),('input.bin','input_sha256')):
        path=directory/name
        if not path.is_file():missing.append(name);artifacts[name]='NOT_PROVEN';continue
        artifacts[name]='PASS' if sha(path.read_bytes())==mf.get(key) else 'FAIL'
        if artifacts[name]=='FAIL':errors.append(name+' SHA mismatch')
    if r:
        if r.get('phase')!='complete' or r.get('outcome') not in ('PASS','FAIL','NOT_PROVEN'):errors.append('invalid result terminal')
        try:
            for key in ('simulation_ticks','frames','elapsed_us'):_uint(r.get(key),key)
        except ValueError as exc:errors.append(str(exc))
        if not r.get('workload'):errors.append('missing workload')
    if r and receipt:
        if receipt.get('result_sha256')!=sha(raw['result.kv']):errors.append('result SHA mismatch')
        if receipt.get('outcome')!=r.get('outcome'):errors.append('receipt outcome mismatch')
    before=records['device-before.kv'];after=records['device-after.kv']
    returned=False
    if before and after and receipt:
        if not HASH.fullmatch(before.get('launcher_sha256','')) or before.get('launcher_sha256')!=after.get('launcher_sha256'):
            errors.append('launcher identity changed')
        if before.get('boot')!=receipt.get('launch_boot') or after.get('boot')!=receipt.get('return_boot'):
            errors.append('receipt/device boot mismatch')
        returned=bool(receipt.get('status')=='COMPLETED' and before.get('boot') and after.get('boot') and before['boot']!=after['boot'])
        if not returned:missing.append('completed launch/return boot transition')
    if config.get('assets_receipt_sha256'):
        if r.get('assets_receipt_sha256')!=config['assets_receipt_sha256']:errors.append('asset receipt binding mismatch')
        # The runner deliberately reuses the bound asset receipt. A value of
        # zero records that it did not reread ~200 MB during this run; it does
        # not contradict the manifest-bound capacity evidence.
        if r.get('assets_full_reverified') not in ('0','1'):missing.append('asset verification mode')
    else:missing.append('assets receipt binding')
    logs=list((directory/'artifacts').rglob('boot.log'));lines=[]
    if len(logs)!=1:missing.append('one boot.log')
    else:
        try:
            if logs[0].stat().st_size>4*1024*1024:raise ValueError('boot log exceeds bound')
            lines=logs[0].read_text(errors='strict').splitlines()
        except (OSError,UnicodeError,ValueError) as exc:errors.append(str(exc))
    failed=False
    for line in lines:
        if re.search(r'\bFATAL\b|HANDLEACTION REJECTED|event=FAILED(?:\s|$)|event=ABORT\S*',line):failed=True
    if failed:errors.append('runtime failure/abort in bound log')
    log_status='PASS'
    for field in ('log_failed','log_truncated'):
        if field not in r:missing.append(field);log_status='NOT_PROVEN'
        elif r[field]!='0':errors.append('runtime '+field);log_status='FAIL'
    if not any(re.search(r'event=(?:WORKLOAD-END|COMPLETE|FAILED)(?:\s|$)',line) for line in lines):
        missing.append('runtime terminal log marker');log_status='NOT_PROVEN'
    identity='FAIL' if errors else 'NOT_PROVEN' if missing else 'PASS'
    canonical={'identity':identity,'launcher_roundtrip':'PASS' if returned and identity=='PASS' else 'NOT_PROVEN',
               'game_outcome':r.get('outcome','NOT_PROVEN') if identity=='PASS' else 'FAIL' if failed else 'NOT_PROVEN',
               'log':{'runtime_write_status':log_status},'errors':errors,'missing':missing,'local_artifact_hashes':artifacts}
    canonical['assets_full_reverified']=r.get('assets_full_reverified')=='1'
    return canonical,config,r,lines


def _save_io(directory,config,result,lines,canonical):
    errors=[];missing=[];samples=[];snapshots={};order=(16384,65536,65536,16384)
    file_hashes=[];timing={};ab={};active=None;finished=set()
    def fail(message):errors.append(message)
    try:
        mf=kv((directory/'manifest.kv').read_bytes())
        bound=config.get('save_io_input_sha256')
        if not bound or bound!=mf.get('input_sha256') or result.get('save_io_input_sha256')!=bound:
            raise ValueError('save IO input/manifest/result mismatch')
        for name in ('input.bin','input.sav'):
            if not (directory/name).is_file():missing.append(name)
            elif sha((directory/name).read_bytes())!=bound:raise ValueError('save IO '+name+' SHA mismatch')
        if result.get('save_io_order')!='16384,65536,65536,16384':raise ValueError('save IO ABBA order mismatch')
        if result.get('save_io_outcome')!='HOST_READBACK_REQUIRED':missing.append('complete save IO producer')
        if result.get('save_io_bytes_outcome')!='NOT_PROVEN':raise ValueError('producer may not assert byte equality')
        if result.get('save_io_roundtrip')!='PASS':missing.append('save IO roundtrip health')
        activity=packed(result['save_io_activity'])
        if activity.get('outcome')=='FAIL':raise ValueError('save IO observed entity failure')
        if activity.get('outcome') not in ('PASS','NOT_PROVEN') or activity.get('partial')!='false' or not positive(activity,'count','updated') or activity['count']!=activity['updated']:
            missing.append('save IO healthy staff work')
        work=packed(result['capacity_save_io_work_work'])
        if not positive(work,'world','hours','frames','entities') or _uint(work.get('elapsed_ms'))<30000:
            raise ValueError('save IO no normal simulation/work')
        if work.get('failed_steps')!='0':raise ValueError('save IO failed simulation step')
        for i,capacity in enumerate(order,1):
            row=packed(result['save_io_sample_'+str(i)])
            file='r75-io-'+str(i)+'.sav'
            if row.get('file')!=file or row.get('capacity')!=str(capacity) or row.get('committed')!='1' or row.get('ready')!='1':
                raise ValueError('save IO sample identity/commit mismatch')
            for key in ('elapsed_ms','heap_before','heap_after','heap_low','linear_before','linear_after','frame','world_completed'):_uint(row.get(key),key)
            if not positive(row,'elapsed_ms'):raise ValueError('zero save IO elapsed')
            samples.append(row)
            path=directory/'save'/file
            if not path.is_file():missing.append('save/'+file)
            elif not path.stat().st_size or path.stat().st_size>64*1024*1024:raise ValueError('invalid private save size')
            else:file_hashes.append({'file':file,'size':path.stat().st_size,'sha256':sha(path.read_bytes())})
        if len({(r['frame'],r['world_completed']) for r in samples})!=1:raise ValueError('save IO advanced frame/world between samples')
        if len(file_hashes)==4 and len({(r['size'],r['sha256']) for r in file_hashes})!=1:raise ValueError('save IO outputs differ')
        for path in sorted((directory/'artifacts').glob('progress-*.kv')):
            f=kv(path.read_bytes());stage=f.get('capacity_stage')
            if f.get('phase')=='capacity' and stage in IO_STAGES:
                if stage in snapshots:raise ValueError('duplicate save IO boundary')
                snapshots[stage]={suffix:packed(f['capacity_'+stage+suffix]) for suffix in ('','_memory')}
                if snapshots[stage][''].get('errors')!='0':raise ValueError('save IO boundary simulation error')
        if tuple(snapshots)!=IO_STAGES:missing.append('three ordered save IO checkpoints')
        if 'save_io_worked' in snapshots and samples:
            row=snapshots['save_io_worked']['']
            if any(row.get(k)!=samples[0].get(v) for k,v in (('frames','frame'),('world_completed','world_completed'))):
                raise ValueError('save IO paused samples do not match worked checkpoint')
        if 'save_io_worked' in snapshots and 'save_io_reloaded' in snapshots:
            a=snapshots['save_io_worked'][''];b=snapshots['save_io_reloaded']['']
            if any(a.get(k)!=b.get(k) for k in ('level','difficulty','rooms','staff','patients','date')):
                raise ValueError('save IO roundtrip scene differs')
        # Native timing has no filename. Bind it to the matching operation's
        # save-begin/complete filename, then the following numbered AB record.
        for line in lines:
            if 'checkpoint[save_load]' in line:
                fields=_fields(line);file=posix_basename(fields.get('identity',''))
                match=re.fullmatch(r'r75-io-([1-4])\.sav',file)
                if fields.get('phase')=='save-begin':
                    if active is not None:raise ValueError('nested save IO operation')
                    active=int(match[1]) if match else 0
                elif fields.get('phase') in ('save-complete','save-failed'):
                    if match and fields.get('phase')=='save-failed':raise ValueError('save IO atomic failure')
                    if match:
                        if active!=int(match[1]):raise ValueError('save IO operation boundary mismatch')
                        finished.add(active)
                    active=None
            if line.startswith(('save-io:','save-io-timing:')) and active:
                if active in timing:raise ValueError('duplicate native save IO timing')
                row=_fields(line)
                if row.get('known')!='1':missing.append('known native save IO timing '+str(active));continue
                for key in ('dump_us','write_us','write_max_us','flush_us','close_ms'):_uint(row.get(key),key)
                if not (_uint(row['write_max_us'])<=_uint(row['write_us'])<=_uint(row['dump_us'])):
                    raise ValueError('native save IO timing containment')
                timing[active]=row
            if 'save-io-ab: ' in line:
                row=_fields(line);i=_uint(row.get('sample'),'sample')
                if i not in range(1,5) or i in ab:raise ValueError('duplicate/invalid save IO AB row')
                if i not in finished:raise ValueError('AB row precedes completed operation')
                if any(row.get(k)!=samples[i-1].get(k) for k in ('capacity','file','elapsed_ms','committed','ready')):
                    raise ValueError('save IO AB log/result mismatch')
                ab[i]=row
        if len(ab)!=4:missing.append('four operation-bound AB log rows')
    except (ValueError,KeyError,TypeError,OSError,UnicodeError) as exc:
        if isinstance(exc,KeyError):missing.append('save IO field '+str(exc))
        else:fail(str(exc))
    trusted=canonical['identity']=='PASS' and canonical['game_outcome']=='PASS' and canonical['launcher_roundtrip']=='PASS'
    outcome='FAIL' if errors else 'PASS' if trusted and not missing and len(file_hashes)==4 else 'NOT_PROVEN'
    if len(timing)!=4:missing_timing='NOT_PROVEN'
    else:missing_timing='PASS' if outcome=='PASS' else 'NOT_PROVEN'
    groups={}
    for capacity in order[:2]:
        selected=[row for row in samples if row.get('capacity')==str(capacity)]
        if len(selected)==2:
            groups[str(capacity)]={'elapsed_ms':[int(r['elapsed_ms']) for r in selected],
                'mean_elapsed_ms':sum(int(r['elapsed_ms']) for r in selected)/2,
                'max_elapsed_ms':max(int(r['elapsed_ms']) for r in selected),
                'heap_before_after':[[int(r['heap_before']),int(r['heap_after'])] for r in selected],
                'heap_low':[int(r['heap_low']) for r in selected]}
    return {'outcome':outcome,'errors':errors,'missing':missing,'files':file_hashes,'samples':samples,
            'native_timing':{'outcome':missing_timing,'samples':timing,'scope':'contained stdio wall time, not physical SD time'},
            'groups':groups,'activity_observation':result.get('save_io_activity'),
            'roundtrip':result.get('save_io_roundtrip','NOT_PROVEN') if outcome=='PASS' else 'NOT_PROVEN',
            'comparison_scope':'one ABBA same-state batch; performance choice requires observed effect, not byte size alone'}


def posix_basename(path):
    return path.rsplit('/',1)[-1]


def consume(directory):
    directory=Path(directory)
    canonical,config,result,lines=_identity(directory)
    report=_capacity(directory,canonical)
    report['identity']=canonical
    report['errors']+=canonical['errors'];report['missing']+=canonical['missing']
    if report['reception']!='PASS':report['missing'].append('two natural reception service windows')
    if config.get('capacity')=='r75-v1':
        report['save_io']=_save_io(directory,config,result,lines,canonical)
        report['errors']+=report['save_io']['errors'];report['missing']+=report['save_io']['missing']
        if report['save_io']['outcome']!='PASS' and report['outcome']=='PASS':report['outcome']='NOT_PROVEN'
    if report['errors']:report['outcome']='FAIL'
    elif report['missing'] and report['outcome']=='PASS':report['outcome']='NOT_PROVEN'
    if report['outcome']!='PASS':
        for key in ('busy_hospital','reception','level_load','expanded_return','lua_release'):
            report[key]='NOT_PROVEN'
        if 'save_io' in report and report['save_io']['outcome']=='PASS':
            # A standalone IO observation remains inspectable, while a failed
            # later workload cannot be presented as an accepted product run.
            report['save_io']['whole_run_acceptance']='NOT_PROVEN'
    report['missing']=sorted(set(report['missing']))
    report['device_acceptance']='bound readback only; physical controls/display/audio remain separate'
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    report=consume(parser.parse_args().run)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if report['outcome']=='FAIL' else 0


if __name__=='__main__':raise SystemExit(main())
