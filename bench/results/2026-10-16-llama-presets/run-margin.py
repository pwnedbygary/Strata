from pathlib import Path
import re
s=Path(__file__).with_name('run.py').read_text()
s=re.sub(r'^cases=.*$',"cases=[{'id':'ub2048-none-fit1536','ub':2048,'spec':'none','fit':1536}]",s,flags=re.M)
exec(compile(s,str(Path(__file__).with_name('run.py')),'exec'))
