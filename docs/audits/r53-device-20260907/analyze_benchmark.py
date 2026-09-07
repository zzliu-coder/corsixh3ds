"""Read R53 logs after the device run. Keep sample bounds and stage overlap visible.
Presentation statistics are API completion intervals, not physical LCD scanout.
"""
import argparse,json,re
from pathlib import Path

def fields(line):
 result={}
 for key,quoted,plain in re.findall(r'([\w-]+)=(?:"([^"]*)"|(\S+))',line):
  value=quoted or plain
  try:value=int(value)
  except ValueError:pass
  result[key]=value
 return result

def analyze(text):
 rows=[];windows=[];marks=[];workloads=[];clocks=[];cpu=[];compact=[]
 latest_clock=None;observation={};segment={};gpu={};backends=[]
 for number,line in enumerate(text.splitlines(),1):
  r=dict(line=number,**fields(line))
  if line.startswith('benchmark: at_us='):marks.append(r)
  elif line.startswith('gpu: selected='):backends.append(r)
  elif line.startswith('perf:'):
   r['begin_us']=r['at_us']-r['elapsed_us'];compact.append(r)
  elif line.startswith('workload:'):workloads.append(r)
  elif line.startswith('cpu-work:'):
   r['begin_us']=r['at_us']-latest_clock['elapsed_us'] if latest_clock is not None else None
   cpu.append(r)
  elif line.startswith('simulation-clock:'):latest_clock=r;clocks.append(r)
  elif line.startswith('simulation-budget:') and latest_clock is not None:latest_clock['budget']=r
  elif line.startswith('observation:'):observation=r
  elif line.startswith('segment:'):segment=r
  elif line.startswith('gpu-work:'):gpu=r
  elif line.startswith('frames:'):
   windows.append(dict(**r,spans={},observation=dict(observation),segment=dict(segment),gpu=dict(gpu)))
  elif line.startswith('span:') and windows:windows[-1]['spans'][r['stage']]=r
 pending=None;samples=[]
 for mark in marks:
  if mark['event']=='SAMPLE-BEGIN':pending=mark
  elif mark['event']=='SAMPLE-END' and pending:
   samples.append((pending,mark));pending=None
  elif mark['event'].startswith(('FAILED','ABORT')):pending=None
 for begin,end in samples:
  start,finish=begin['at_us'],end['at_us']
  observed=[w for w in workloads if start<=w['at_us']<=finish]
  # Full-window flush is deferred until outer spans close. SAMPLE-END can be
  # followed by a reload in that same tick. Prefer compact cumulative snapshots
  # whose *entire* interval lies inside the sample; never hide the load overhang.
  stable_compact=[dict(**r,present_hz_from_rounded_mean=1e6/r['mean_us'])
   for r in compact if r['begin_us']>=start and r['at_us']<=finish
   and r.get('intervals',0)>0 and r.get('mean_us',0)>0
   and r.get('failed')==0 and not r.get('terminal') and not r.get('truncated')]
  matching=[]
  for window in windows:
   overlap=max(0,min(finish,window['end'])-max(start,window['begin']))
   if not window.get('sum') or overlap<window['elapsed']*.9:continue
   # No prorating counts: expose the exact measured interval and overhang.
   matching.append(dict(line=window['line'],begin_us=window['begin'],end_us=window['end'],
    sample_overlap_us=overlap,outside_sample_us=window['elapsed']-overlap,
    stable_eligible=window['segment'].get('stable_eligible'),
    present_hz=window['count']*1e6/window['sum'],mean_interval_ms=window['sum']/window['count']/1000,
    p95_bounds_us=[window['p95_lo'],window['p95_hi']],p99_bounds_us=[window['p99_lo'],window['p99_hi']],
    max_interval_us=window['max'],failed_presents=window['failed'],invalid=window['invalid'],
    stage_ms_per_present={k:v['exclusive_us']/window['success']/1000 for k,v in window['spans'].items()} if window['success'] else {},
    gpu_cumulative=window['gpu']))
  span_clocks=[r for r in clocks if start<=r['at_us']<=finish and 'budget' in r]
  simulation=None
  if len(span_clocks)>=2:
   a,b=span_clocks[0],span_clocks[-1];elapsed=b['at_us']-a['at_us']
   simulation=dict(begin_us=a['at_us'],end_us=b['at_us'],
    nominal_work_fraction=(b['budget']['steps']-a['budget']['steps'])*18000/elapsed,
    dropped_us=b['budget']['dropped_us']-a['budget']['dropped_us'],
    rebases=b['budget']['rebases']-a['budget']['rebases'])
  inclusive={}
  for name in ('world','ui','temperature','pathfind','input_state','input_action'):
   pieces=[r for r in cpu if r['name']==name and start<=r['at_us']<=finish]
   within=[r for r in pieces if r['begin_us'] is not None and r['begin_us']>=start]
   inclusive[name]=dict(calls=sum(r['calls'] for r in within),inclusive_us=sum(r['total_us'] for r in within),
    intervals=within,excluded_cross_boundary=[r for r in pieces if r not in within])
  rows.append(dict(speed=begin['speed'],start=begin,end=end,elapsed_seconds=(finish-start)/1e6,
   actual_workload_speeds=sorted({r['speed'] for r in observed}),
   workload=observed,windows=matching,compact_snapshots_cumulative_do_not_sum=stable_compact,
   preferred_compact=stable_compact[-1] if stable_compact else None,
   simulation=simulation,cpu_inclusive_do_not_sum=inclusive))
 complete=any(r['event']=='COMPLETE' for r in marks)
 failed=any(r['event'].startswith(('FAILED','ABORT')) for r in marks)
 ordered=(len(samples)==2 and [a['speed'] for a,b in samples]==['Normal','And then some more']
  and all(a['speed']==b['speed'] and b['at_us']-a['at_us']>=60000000 for a,b in samples)
  and samples[0][1]['at_us']<samples[1][0]['at_us']
  and any(r['event']=='COMPLETE' and r['at_us']>=samples[-1][1]['at_us'] for r in marks))
 return dict(benchmark_protocol='PASS' if complete and ordered and not failed else 'NOT_PROVEN',
  samples=rows,marks=marks,backend_selections=backends,device_visual_save_audio='NOT_PROVEN',fps_30='NOT_PROVEN',
  boundary='Use exact window bounds. Compact snapshots are cumulative; do not sum them. Deferred full flush can include a following load; show overhang and prefer wholly contained compact intervals. GPU completion time is not utilization; normal simulation and device visuals/save reload also required.')

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('log',type=Path);parser.add_argument('--output',type=Path)
 args=parser.parse_args();result=analyze(args.log.read_text(errors='replace'))
 encoded=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
 if args.output:
  with args.output.open('x') as f:f.write(encoded)
 else:print(encoded,end='')
