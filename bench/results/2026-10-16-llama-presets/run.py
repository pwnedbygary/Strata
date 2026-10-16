from pathlib import Path
import json,subprocess,urllib.request,time,os,signal,configparser,shutil
root=Path.cwd();out=Path(__file__).parent.resolve();py=str(root/'.venv/bin/python');exe=Path.home()/'.local/bin/llama';base='http://127.0.0.1:8098'
original=Path('/home/garyb/Mounts/NVME/Strata/models/presets.ini');backup=out/'presets-before-tuning.ini'
if not backup.exists():shutil.copy2(original,backup)
ini=configparser.ConfigParser(interpolation=None);ini.read_string("[metadata]\n"+backup.read_text())
models=[s for s in ini.sections() if s not in ['*','metadata']];summary=json.loads((out/'summary.json').read_text()) if (out/'summary.json').exists() else []
prompt=(root/'bench/results/2026-10-16-unified-runner/coding-8k-prompt.txt').read_text()
def phase(x):(out/'phase.json').write_text(json.dumps(dict(x,time=time.time()),indent=2)+'\n')
def request(path,b=None,timeout=900):
 r=urllib.request.Request(base+path,data=None if b is None else json.dumps(b).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=timeout) as f:return json.load(f)
def stop(proc,scope):
 subprocess.run(['systemctl','--user','stop',scope],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:proc.wait(timeout=10)
 except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=10)
def launch(name,case,directory):
 c=configparser.ConfigParser(interpolation=None);c['*']=dict(ini['*']);c[name]=dict(ini[name])
 c['*'].update({'device':'Vulkan0','fit':'on','fit-target':str(case.get('fit',2048)),'cache-ram':'0','load-mode':'none','parallel':'1','threads':str(case.get('threads',8)),'threads-batch':str(case.get('threads',8)),'batch-size':'2048','cache-type-k':'q8_0','cache-type-v':'q8_0'})
 c[name].update({'fit':'on','fit-target':str(case.get('fit',2048)),'ctx-size':str(262144 if 'TIEL' in name else 131072),'ubatch-size':str(case['ub']),'spec-type':case['spec']})
 c[name].pop('n-gpu-layers',None)
 c[name]['spec-draft-n-max']=str(case.get('draft',2))
 if case.get('cpu_moe'):
  c[name]['n-cpu-moe']=str(case['cpu_moe']);c[name]['fit']='off';c[name]['n-gpu-layers']='all'
 candidate=directory/'presets.ini'
 with candidate.open('w') as f:f.write('version = 1\n\n');c.write(f)
 scope='strata-preset-test-'+str(time.time_ns())+'.scope';lock='/run/user/'+str(os.getuid())+'/strata-native-model-'+str(os.getuid())+'.lock'
 cmd=[str(exe),'serve','--models-preset',str(candidate),'--models-max','1','--models-autoload','--host','127.0.0.1','--port','8098','--offline','--no-ui','--slots','--metrics']
 wrapped=[py,'tools/benchmark_guarded.py','--scope',scope,'--memory-floor-gib','4','--vram-floor-mib','640','--gtt-floor-mib','768','--output',str(directory/'guard.json'),'--','systemd-run','--user','--scope','--quiet','--unit',scope.removesuffix('.scope'),'--collect','-p','MemoryMax=20G','-p','MemoryHigh=18G','-p','MemorySwapMax=0','flock','--nonblock',lock,*cmd]
 (directory/'command.json').write_text(json.dumps({'command':cmd,'guarded_command':wrapped},indent=2)+'\n')
 env={k:v for k,v in os.environ.items() if not k.startswith(('STRATA_','LLAMA_ARG_','LLAMA_API_KEY'))};env['LD_LIBRARY_PATH']='/opt/rocm/lib'
 log=(directory/'server.log').open('w');proc=subprocess.Popen(wrapped,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
 for _ in range(1200):
  if proc.poll() is not None:log.close();raise RuntimeError('Startup failed: '+str(directory))
  try:
   if request('/health',timeout=1).get('status')=='ok':return proc,scope,log
  except Exception:pass
  time.sleep(.25)
 stop(proc,scope);log.close();raise RuntimeError('Startup timeout')
cases=[{'id':'ub512-none','ub':512,'spec':'none'},{'id':'ub2048-none','ub':2048,'spec':'none'},{'id':'ub2048-ngram','ub':2048,'spec':'ngram-mod'},{'id':'ub512-ngram','ub':512,'spec':'ngram-mod'}]
for name in models:
 trials=cases
 for case in trials:
  if any(r['model']==name and r['case']==case and 'error' not in r for r in summary):continue
  directory=out/(name.lower()+'-'+case['id']);directory.mkdir(exist_ok=True);phase({'model':name,'case':case,'stage':'loading'});print('START',name,case,flush=True)
  proc=None;log=None
  try:
   proc,scope,log=launch(name,case,directory)
   warm=request('/v1/chat/completions',{'model':name,'messages':[{'role':'user','content':'Reply with READY only.'}],'max_tokens':16,'temperature':0,'reasoning_effort':'none','chat_template_kwargs':{'enable_thinking':False}})
   (directory/'warmup.json').write_text(json.dumps(warm,indent=2)+'\n');phase({'model':name,'case':case,'stage':'coding-8k'})
   start=time.monotonic();answer=request('/v1/chat/completions',{'model':name,'messages':[{'role':'user','content':prompt}],'max_tokens':768,'temperature':0,'reasoning_effort':'none','chat_template_kwargs':{'enable_thinking':False},'cache_prompt':False})
   (directory/'response.json').write_text(json.dumps(answer,indent=2)+'\n');(directory/'fresh.md').write_text(answer['choices'][0]['message'].get('content',''))
   subprocess.run([py,'tools/check_coding_context.py',str(directory/'fresh.md'),'--output',str(directory/'code-check.json')],stdout=subprocess.DEVNULL,check=False)
   check=json.loads((directory/'code-check.json').read_text());timings=answer.get('timings',{})
   result={'model':name,'case':case,'timings':timings,'usage':answer.get('usage',{}),'wall_seconds':time.monotonic()-start,'checks_passed':check['passed'],'directory':str(directory)}
  except Exception as e:
   result={'model':name,'case':case,'error':str(e),'directory':str(directory)};print('ERROR',result,flush=True)
  finally:
   if proc:stop(proc,scope)
   if log:log.close()
  summary.append(result);(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print('RESULT',result,flush=True)
  if 'error' in result:phase({'stage':'failed','result':result});raise RuntimeError('Trial failed; inspect the preserved server log before resuming')
phase({'stage':'short-trials-complete'})
