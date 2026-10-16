from pathlib import Path
source=Path(__file__).with_name('run.py').read_text()
exec(compile(source.split('cases=[',1)[0],str(Path(__file__).with_name('run.py')),'exec'))
winners={}
for name in models:
 candidates=[r for r in summary if r['model']==name and 'timings' in r]
 if not candidates:raise RuntimeError('No completed tuning trials for '+name)
 quality=max(r.get('checks_passed',0) for r in candidates);candidates=[r for r in candidates if r.get('checks_passed')==quality]
 target=260096 if 'TIEL' in name else 130048
 winner=min(candidates,key=lambda r:target/r['timings']['prompt_per_second']+512/r['timings']['predicted_per_second'])
 base_candidates=[r for r in candidates if r['case']['spec']=='none' and r['case'].get('fit',2048)==2048 and 'threads' not in r['case'] and 'cpu_moe' not in r['case']]
 baseline=min(base_candidates,key=lambda r:target/r['timings']['prompt_per_second']+512/r['timings']['predicted_per_second']) if base_candidates else None
 if baseline:
  score=lambda r:target/r['timings']['prompt_per_second']+512/r['timings']['predicted_per_second']
  if score(winner)>score(baseline)*.95:winner=baseline
 if 'TIEL' in name:winner=next(r for r in candidates if r['case']['id']=='manual-cpu27-ub1024')
 winners[name]=winner
(out/'winners.json').write_text(json.dumps(winners,indent=2)+'\n')
for name,winner in winners.items():
 directory=out/(name.lower()+'-full-context');directory.mkdir(exist_ok=True)
 report=directory/'context/report.json'
 if report.exists() and len(json.loads(report.read_text()).get('runs',[]))==2:continue
 phase({'stage':'full-context-loading','model':name,'case':winner['case']});print('FULL START',name,winner['case'],flush=True)
 proc=None;log=None
 try:
  proc,scope,log=launch(name,winner['case'],directory)
  warm=request('/v1/chat/completions',{'model':name,'messages':[{'role':'user','content':'Reply READY.'}],'max_tokens':16,'reasoning_effort':'none','chat_template_kwargs':{'enable_thinking':False}})
  phase({'stage':'full-context','model':name,'case':winner['case']})
  cmd=[py,'tools/coding_context_bench.py','--model',name,'--tokens',str(260096 if 'TIEL' in name else 130048),'--long-context-probes','--base-url',base,'--output',str(directory/'context')]
  with (directory/'benchmark.log').open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
  subprocess.run([py,'tools/check_coding_context.py',str(directory/'context/fresh.md'),'--output',str(directory/'context/code-check.json')],check=False)
  print('FULL DONE',name,report.read_text(),flush=True)
 finally:
  if proc:stop(proc,scope)
  if log:log.close()
phase({'stage':'full-context-complete'})
