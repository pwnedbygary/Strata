from pathlib import Path
import re
s=Path(__file__).with_name('run.py').read_text()
s=re.sub(r'^cases=.*$',"cases=[{'id':'manual-cpu27-ub2048','ub':2048,'spec':'none','cpu_moe':27}]",s,flags=re.M)
s=s.replace('for name in models:',"for name in [m for m in models if 'TIEL' in m]:")
exec(compile(s,str(Path(__file__).with_name('run.py')),'exec'))
