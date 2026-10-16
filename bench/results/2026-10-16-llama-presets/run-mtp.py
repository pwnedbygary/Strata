from pathlib import Path
import re
s=Path(__file__).with_name('run.py').read_text()
s=re.sub(r'^cases=.*$',"cases=[{'id':'ub2048-mtp1','ub':2048,'spec':'draft-mtp','draft':1}]",s,flags=re.M)
s=s.replace('for name in models:',"for name in [m for m in models if 'TIEL' in m]:")
exec(compile(s,str(Path(__file__).with_name('run.py')),'exec'))
