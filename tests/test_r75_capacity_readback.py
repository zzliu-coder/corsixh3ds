"""Synthetic protocol fixtures only; no claim of real SD/device measurement."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import read_capacity_result as reader


def encode(fields):
    return ''.join(str(k)+'='+str(v)+'\n' for k,v in sorted(fields.items())).encode()


def pack(**fields):
    return ';'.join(str(k)+'='+str(v) for k,v in sorted(fields.items()))


def fixture(path,protocol='r75-v1'):
    path.mkdir(parents=True);(path/'artifacts').mkdir();(path/'save').mkdir()
    program=b'fixture-executable';input_data=b'fixture-input'
    config={'capacity':protocol,'continuity_sha256':reader.SHA,'assets_receipt_sha256':'e'*64}
    if protocol=='r75-v1':config['save_io_input_sha256']=reader.sha(input_data)
    mf={'version':'1','run_id':'20260910-fixture-run','artifact_sha256':reader.sha(program),
        'config_sha256':reader.sha(encode(config)),'input_sha256':reader.sha(input_data)}
    for name,data in [('program.3dsx',program),('input.bin',input_data),('input.sav',input_data),
                      ('manifest.kv',encode(mf)),('config.bin',encode(config))]:(path/name).write_bytes(data)
    for name in ('r73-continuity.sav','r74-busy.sav','r73-level12.sav'):(path/'save'/name).write_bytes(b'fixture-private-save')
    r=dict(mf,manifest_sha256=reader.sha(encode(mf)),phase='complete',outcome='PASS',reason='fixture',
           workload='capacity-fixture',simulation_ticks='100',frames='100',elapsed_us='1000000000',
           log_failed='0',log_truncated='0',assets_full_reverified='0',assets_receipt_sha256='e'*64,
           capacity_stage='complete',capacity_input_sha256=reader.SHA,capacity_continuity_roundtrip='PASS',
           capacity_level_outcome='PASS',capacity_return_outcome='PASS',capacity_reception_outcome='PASS',
           capacity_lua_release_outcome='PASS')
    work=pack(world=100,hours=100,entities=400,frames=1000,elapsed_ms=180000,elapsed_us=180000000,
              nominal_timer_us=18000,world_tick_rate=3,hours_per_tick=1,failed_steps=0,debt_before_us=0,
              debt_after_us=0,dropped_us=0,rebases=0,budget_exits=0,completed_steps=100)
    for phase in ('reception_1','reception_2','level_run','return_run'):r['capacity_'+phase+'_work']=work
    for i in (1,2):r['capacity_reception_'+str(i)]=pack(updated=17,count=17,identity='PASS',partial='false')
    r['capacity_patient_services']='15=1;20=1'
    lines=[]
    for w in (1,2):
        for source in list(range(9,25))+[45]:
            lines.append(f'capacity-activity: window={w} source={source} ticks=3 failures=0')
        for source in (15,20):
            lines.append(f'capacity-service: window={w} event=1 source={source} head=Patient same=true passed_after=true id=p owner=d action=service next=walk tail=idle after=2 before=1')
    if protocol!='r73-v1':
        r.update(capacity_protocol=protocol,capacity_busy_hospital='PASS',capacity_busy_roundtrip='PASS',
                 capacity_busy_save_entry='UISaveGame.confirmName/trySave/doSave',capacity_busy_save_ui='PASS')
        for phase in ('busy_recruit','busy_1','busy_2'):r['capacity_'+phase+'_work']=work
        for i in (1,2):
            r['capacity_busy_'+str(i)+'_activity']=pack(count=40,updated=40,identity='PASS',partial='false',outcome='PASS')
            for source in range(1,41):lines.append(f'capacity-busy: window={i} source={source} ticks=10 failures=0 partial_timer=0')
    stage_order=tuple(s for s in reader.STAGES if protocol!='r73-v1' or not s.startswith('busy_'))
    scenes={}
    for stage in stage_order:
        level=12 if stage in ('level_loaded','level_ran','level_reloaded') else 1
        scenes[stage]=pack(level=level,difficulty='full',world='table:1',map='table:2',rooms=14,
                           staff=40 if stage.startswith('busy_') else 17,patients=10,date='date',
                           world_completed=500,hours=500,entities=600,frames=500,at=50000,errors=0)
        r['capacity_'+stage]=scenes[stage]
        r['capacity_'+stage+'_memory']=pack(heap=16000000,linear=2199552,lua=7000000)
    if protocol=='r75-v1':
        stage_order=reader.IO_STAGES+stage_order
        r.update(save_io_input_sha256=reader.sha(input_data),save_io_order='16384,65536,65536,16384',
                 save_io_outcome='HOST_READBACK_REQUIRED',save_io_bytes_outcome='NOT_PROVEN',save_io_roundtrip='PASS',
                 save_io_activity=pack(outcome='PASS',count=41,updated=41,action_covered=40,partial='false'),
                 capacity_save_io_work_work=work)
        for stage in reader.IO_STAGES:scenes[stage]=scenes['continuity_loaded']
        for i,capacity in enumerate((16384,65536,65536,16384),1):
            file='r75-io-'+str(i)+'.sav';(path/'save'/file).write_bytes(b'identical-serialized-state')
            r['save_io_sample_'+str(i)]=pack(capacity=capacity,file=file,elapsed_ms=1000+i,heap_before=17000000,
                heap_after=17000000,heap_low=16900000,linear_before=2199552,linear_after=2199552,
                committed=1,ready=1,frame=500,world_completed=500)
            lines.extend([f'checkpoint[save_load] +1ms: stage=S100 phase=save-begin identity=sdmc:/run/save/{file} bytes=0',
                'save-io: known=1 dump_us=900000 write_us=800000 write_max_us=500000 flush_us=1 close_ms=5 io_in_dump=1 close_in_dump=0',
                f'checkpoint[save_load] +2ms: stage=S100 phase=save-complete identity=sdmc:/run/save/{file} bytes=0',
                f'save-io-ab: sample={i} capacity={capacity} elapsed_ms={1000+i} committed=1 ready=1 file={file}'])
    lines.append('benchmark: at_us=999999999 event=COMPLETE')
    (path/'artifacts/boot.log').write_text('\n'.join(lines)+'\n')
    for i,stage in enumerate(stage_order,1):
        f=dict(r,phase='capacity',outcome='NOT_PROVEN',capacity_stage=stage,
               checkpoint_sequence=str(i),snapshot_complete='1')
        if stage in reader.IO_STAGES:
            f['capacity_'+stage]=scenes[stage];f['capacity_'+stage+'_memory']=pack(heap=16000000,linear=2199552,lua=7000000)
        (path/'artifacts'/f'progress-{i:04d}.kv').write_bytes(encode(f))
    write_result(path,r)
    return r


def write_result(path,r):
    (path/'result.kv').write_bytes(encode(r))
    mf=reader.kv((path/'manifest.kv').read_bytes())
    receipt=dict(mf,manifest_sha256=reader.sha((path/'manifest.kv').read_bytes()),result_sha256=reader.sha(encode(r)),
                 status='COMPLETED',outcome=r['outcome'],launch_boot='boot-one',return_boot='boot-two')
    (path/'receipt.kv').write_bytes(encode(receipt))
    for name,boot in (('device-before.kv','boot-one'),('device-after.kv','boot-two')):
        (path/name).write_bytes(encode({'version':'1','boot':boot,'launcher_sha256':'a'*64,'model':'old3ds'}))


class CapacityReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cth3ds-readback-fixture-');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'run';self.result=fixture(self.path)

    def test_r75_complete_bound_bytes_stages_services_and_no_fps_gate(self):
        report=reader.consume(self.path)
        self.assertEqual(report['outcome'],'PASS',report)
        self.assertEqual(report['save_io']['outcome'],'PASS')
        self.assertEqual(report['save_io']['native_timing']['outcome'],'PASS')
        self.assertEqual(report['reception'],'PASS');self.assertEqual(report['busy_hospital'],'PASS')
        self.assertEqual(report['native_gpu_release'],'NOT_PROVEN');self.assertFalse(report['fps_acceptance_gate'])
        self.assertEqual(report['stages'],list(reader.IO_STAGES+reader.STAGES))

    def test_historical_r73_r74_capacity_stages_keep_original_scopes(self):
        for protocol in ('r73-v1','r74-v1'):
            path=Path(self.temp.name)/protocol;fixture(path,protocol)
            report=reader.consume(path)
            self.assertEqual(report['outcome'],'PASS',report)
            self.assertNotIn('save_io',report)
            self.assertEqual(len(report['stages']),10 if protocol=='r73-v1' else 14)

    def test_output_missing_or_nonidentical_cannot_pass(self):
        file=self.path/'save/r75-io-3.sav';file.unlink()
        self.assertEqual(reader.consume(self.path)['save_io']['outcome'],'NOT_PROVEN')
        file.write_bytes(b'different')
        self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')

    def test_checkpoint_partial_missing_and_sequence_corrupt_cannot_pass(self):
        file=self.path/'artifacts/progress-0002.kv';original=file.read_bytes();file.unlink()
        self.assertNotEqual(reader.consume(self.path)['outcome'],'PASS')
        file.write_bytes(original.replace(b'checkpoint_sequence=2\n',b'checkpoint_sequence=3\n'))
        self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')
        file.write_bytes(original);(self.path/'artifacts/progress-0018.kv.tmp').write_bytes(b'partial')
        self.assertNotEqual(reader.consume(self.path)['outcome'],'PASS')

    def test_config_input_receipt_and_boot_identity_mutation_rejected(self):
        for name in ('input.bin','input.sav','program.3dsx','config.bin','receipt.kv','device-after.kv'):
            file=self.path/name;original=file.read_bytes()
            with self.subTest(name=name):
                file.write_bytes(original+(b'wrong\n' if name.endswith(('.kv','.bin')) else b'wrong'))
                self.assertNotEqual(reader.consume(self.path)['outcome'],'PASS')
                file.write_bytes(original)
        after=reader.kv((self.path/'device-after.kv').read_bytes());after['boot']='other'
        (self.path/'device-after.kv').write_bytes(encode(after))
        self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')

    def test_native_timing_missing_is_not_proven_without_inventing_sd_cost(self):
        log=self.path/'artifacts/boot.log';log.write_text('\n'.join(x for x in log.read_text().splitlines() if not x.startswith('save-io:'))+'\n')
        report=reader.consume(self.path)
        self.assertEqual(report['save_io']['outcome'],'PASS',report)
        self.assertEqual(report['save_io']['native_timing']['outcome'],'NOT_PROVEN')

    def test_failed_game_or_runtime_error_never_upgrades_fps_to_pass(self):
        self.result['outcome']='FAIL';self.result['frames']='999999999';write_result(self.path,self.result)
        self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')
        self.result['outcome']='PASS';write_result(self.path,self.result)
        log=self.path/'artifacts/boot.log';log.write_text(log.read_text()+'FATAL: simulation failed\n')
        report=reader.consume(self.path)
        self.assertEqual(report['outcome'],'FAIL');self.assertEqual(report['busy_hospital'],'NOT_PROVEN')

    def test_paused_frame_world_work_or_roundtrip_divergence_rejected(self):
        for key,value in [('frame','501'),('world_completed','501'),('committed','0'),('capacity','65536')]:
            row=reader.packed(self.result['save_io_sample_1']);row[key]=value
            mutated=copy.deepcopy(self.result);mutated['save_io_sample_1']=pack(**row);write_result(self.path,mutated)
            self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')
        write_result(self.path,self.result)
        file=self.path/'artifacts/progress-0003.kv';f=reader.kv(file.read_bytes());scene=reader.packed(f['capacity_save_io_reloaded'])
        scene['staff']='16';f['capacity_save_io_reloaded']=pack(**scene);file.write_bytes(encode(f))
        self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')

    def test_kv_duplicate_bound_payload_and_orphan_timing_rejected(self):
        for value in (b'k=1\nk=2\n',b'x='+b'a'*1025+b'\n',b'x=1',b'x=1\x00\n'):
            with self.assertRaises(ValueError):reader.kv(value)
        with self.assertRaises(ValueError):reader.lua_bound({str(i):'x' for i in range(129)})
        with self.assertRaises(ValueError):reader.lua_bound({'a':'x'*12000})
        log=self.path/'artifacts/boot.log';text=log.read_text();log.write_text(text.replace('phase=save-complete','phase=load-complete',1))
        self.assertEqual(reader.consume(self.path)['outcome'],'FAIL')

    def test_missing_natural_reception_busy_employee_or_identity_rows_not_proven(self):
        log=self.path/'artifacts/boot.log';text=log.read_text()
        for absent in ('capacity-service:','capacity-busy: window=2 source=1 ','capacity-activity: window=2 source=45 '):
            log.write_text('\n'.join(line for line in text.splitlines() if not line.startswith(absent))+'\n')
            report=reader.consume(self.path)
            self.assertNotEqual(report['outcome'],'PASS',report)
        log.write_text(text)

    def test_cli_reads_only_and_prints_json(self):
        before={str(p.relative_to(self.path)):reader.sha(p.read_bytes()) for p in self.path.rglob('*') if p.is_file()}
        result=subprocess.run([sys.executable,str(Path(reader.__file__)),str(self.path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['outcome'],'PASS')
        after={str(p.relative_to(self.path)):reader.sha(p.read_bytes()) for p in self.path.rglob('*') if p.is_file()}
        self.assertEqual(before,after)


if __name__=='__main__':unittest.main()
