from pathlib import Path
import re
s=Path(__file__).with_name('run.py').read_text()
s=re.sub(r'^cases=.*$',"cases=[{'id':'manual-cpu28-ub128','ub':128,'spec':'none','cpu_moe':28},{'id':'manual-cpu28-ub512','ub':512,'spec':'none','cpu_moe':28},{'id':'manual-cpu28-ub2048','ub':2048,'spec':'none','cpu_moe':28},{'id':'manual-cpu26-ub128','ub':128,'spec':'none','cpu_moe':26},{'id':'manual-cpu26-ub512','ub':512,'spec':'none','cpu_moe':26},{'id':'manual-cpu26-ub2048','ub':2048,'spec':'none','cpu_moe':26}]",s,flags=re.M)
s=s.replace('for name in models:',"for name in [m for m in models if 'TIEL' in m]:")
s=s.replace('trials=cases',"trials=[c for c in cases if not(name.startswith('CYBER') and c['id']=='manual-cpu28-ub2048')]")
exec(compile(s,str(Path(__file__).with_name('run.py')),'exec'))
