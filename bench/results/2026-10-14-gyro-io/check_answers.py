import ast, builtins, json, re, resource, sys
from pathlib import Path
resource.setrlimit(resource.RLIMIT_CPU,(3,3))
resource.setrlimit(resource.RLIMIT_AS,(256*2**20,256*2**20))
source=Path(sys.argv[1]).read_text()
code=re.search(r"```(?:python)?\n(.*?)```",source,re.S).group(1)
tree=ast.parse(code)
assert all(isinstance(n,ast.FunctionDef) and not n.decorator_list for n in tree.body)
methods={'replace','split','join','append'}
names={'isinstance','int','float','ValueError','TypeError','min','max','str','list','tuple','len'}
for n in ast.walk(tree):
 assert not isinstance(n,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal,ast.ClassDef))
 assert not isinstance(n,ast.Name) or not n.id.startswith('__')
 assert not isinstance(n,ast.Attribute) or n.attr in methods
 if isinstance(n,ast.Call):assert isinstance(n.func,ast.Name) and n.func.id in names or isinstance(n.func,ast.Attribute) and n.func.attr in methods
ns={'__builtins__':{n:getattr(builtins,n) for n in names}}
exec(compile(tree,'answer','exec'),ns)
cases=json.loads(Path(__file__).with_name('cases.json').read_text())['cases'];out=[]
for c in cases:
 args=ast.literal_eval(c['args']);expect=c['expected'];exception=expect=="<class 'ValueError'>"
 try:
  value=ns[c['function']](*args);passed=not exception and value==ast.literal_eval(expect);actual=repr(value)
 except Exception as e:passed=exception and isinstance(e,ValueError);actual=type(e).__name__
 out.append(dict(function=c['function'],args=c['args'],expected=expect,actual=actual,passed=passed))
print(json.dumps({'passed':sum(c['passed'] for c in out),'total':len(out),'cases':out},indent=2))
