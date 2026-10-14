"""Opt-in single-resident-model router. Existing single-model serving is untouched."""
from __future__ import annotations

import argparse
import contextlib
import hmac
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 32 * 1024 * 1024
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'}
GENERATE = {'/v1/chat/completions', '/v1/completions', '/v1/messages', '/v1/responses',
            '/v1/images/generations'}


def read_registry(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict):
        raise ValueError('Registry must be a JSON object')
    profiles = raw.get('profiles')
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError('registry needs a nonempty profiles object: model name -> config file')
    result = {}
    for name, source in profiles.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(source, str):
            raise ValueError('profile names and configuration paths must be strings')
        config = Path(source).expanduser()
        if not config.is_absolute():
            config = Path(path).resolve().parent / config
        cfg = json.loads(config.read_text(encoding='utf-8-sig'))
        if not isinstance(cfg, dict):
            raise ValueError(f'{name}: config must be a JSON object')
        if not isinstance(cfg.get('router', {}), dict):
            raise ValueError(f'{name}: router settings must be a JSON object')
        if not isinstance(cfg.get('exe'), str) or not cfg['exe'] or not isinstance(cfg.get('args'), list) or not all(isinstance(arg, str) for arg in cfg['args']) or not isinstance(cfg.get('tokenizer'), str) or not cfg['tokenizer']:
            raise ValueError(f'{name}: expected a prepared Strata config with exe, args and tokenizer')
        if cfg.get('replicas') or cfg.get('parallel', 1) != 1:
            raise ValueError(f'{name}: this router supports one request and one engine at a time')
        model_metadata(name, cfg, {'active': None, 'loading': None})
        result[name] = (config.resolve(), cfg)
    default = raw.get('default', next(iter(result)))
    if not isinstance(default, str) or default not in result:
        raise ValueError('default model is not registered')
    if result[default][1].get('router', {}).get('enabled') is False:
        raise ValueError('Default model cannot be disabled')
    return result, default


def model_metadata(name, cfg, state):
    args = cfg.get('args', [])
    context = None
    if '--max-context' in args:
        at = args.index('--max-context') + 1
        if at < len(args):
            with contextlib.suppress(ValueError, TypeError):
                context = int(args[at])
    settings = cfg.get('router', {})
    cap = settings.get('max_output_tokens')
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0):
        raise ValueError(f'{name}: router.max_output_tokens must be a positive integer')
    maximum = min(cap, context) if cap and context else cap or context
    vision = bool(cfg.get('vision'))
    draft_tokens = 0
    flag = '--spec' if cfg.get('arch', 'qwen4exp') == 'qwen4exp' else '--mtp'
    if flag in args and args.index(flag) + 1 < len(args):
        with contextlib.suppress(ValueError, TypeError):
            draft_tokens = max(0, int(args[args.index(flag)+1]))
    return {'id': name, 'object': 'model', 'owned_by': 'strata',
            'name': settings.get('display_name', name),
            'description': settings.get('description', ''),
            'context_length': context, 'max_output_tokens': maximum,
            'available': settings.get('enabled', True) is not False,
            'unavailable_reason': settings.get('disabled_reason') if settings.get('enabled') is False else None,
            'meta': {'n_ctx': context, 'max_output_tokens': maximum},
            'model_architecture': cfg.get('arch', 'qwen4exp'),
            'architecture': {'input_modalities': ['text', 'image'] if vision else ['text'],
                             'output_modalities': ['text']},
            'capabilities': {'streaming': True, 'tools': True, 'vision': vision,
                             'image_generation': bool(cfg.get('images'))},
            'sampling_defaults': cfg.get('sampling', {}),
            'drafting': {'enabled': draft_tokens > 0, 'draft_tokens': draft_tokens,
                         'greedy_only': cfg.get('arch', 'qwen4exp') != 'qwen4exp'},
            'output_limit_policy': 'min(configured_cap, context_length - tokenized_input)',
            'fit_max_tokens': bool(cfg.get('fit_max_tokens')),
            'status': {'value': 'unavailable' if settings.get('enabled') is False else
                      'loading' if state['loading'] == name else
                      'loaded' if state['active'] == name else 'unloaded'}}


def profile_web_script(source, name, cfg):
    """Apply this router profile's defaults and keep browser edits per model."""
    defaults = {key: value for key, value in cfg.get('sampling', {}).items()
                if key in ('temperature', 'top_p', 'top_k')}
    if cfg.get('reasoning_effort'):
        defaults['thinking'] = cfg['reasoning_effort']
    original = 'let settings = {...DEFAULTS, ...store.get("sampling", {})};'
    if original not in source:
        return source
    replacement = ('Object.assign(DEFAULTS, ' + json.dumps(defaults) + ');\n'
                   'const PROFILE_SAMPLING_KEY = ' + json.dumps('sampling:' + name) + ';\n'
                   'let settings = {...DEFAULTS, ...store.get(PROFILE_SAMPLING_KEY, {})};')
    return source.replace(original, replacement).replace(
        'store.set("sampling", settings);', 'store.set(PROFILE_SAMPLING_KEY, settings);')


def worker_command(config, port):
    args = ['--engine', 'strata', '--config', str(config), '--host', '127.0.0.1', '--port', str(port)]
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--worker', *args]
    return [sys.executable, str(ROOT / 'serve/server.py'), *args]


class Router:
    def __init__(self, profiles, default, *, contained=True, startup_timeout=600, memory_floor=1.5):
        self.profiles, self.default = profiles, default
        self.contained, self.startup_timeout, self.memory_floor = contained, startup_timeout, memory_floor
        self.requests = threading.BoundedSemaphore(8)
        self.turn = threading.RLock()
        self.lifecycle = threading.RLock()
        self.state_lock = threading.Lock()
        self.active = None
        self.loading = None
        self.error = None
        self.process = None
        self.port = None
        self.secret = secrets.token_urlsafe(32)
        self.browser_token = secrets.token_urlsafe(32)
        self.directory = tempfile.TemporaryDirectory(prefix='strata-router-')
        self.closed = threading.Event()
        self.unit = f'strata-router-model-{os.getpid()}'
        self.guard = threading.Thread(target=self._guard, daemon=True)
        self.guard.start()

    def status(self):
        with self.state_lock:
            live = self.process is not None and self.process.poll() is None
            return {'active': self.active if live else None, 'loading': self.loading,
                    'error': self.error, 'default': self.default,
                    'profiles': list(self.profiles), 'loaded': bool(live and self.active)}

    def _guard(self):
        while not self.closed.wait(.5):
            try:
                available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                                 if line.startswith('MemAvailable:')) * 1024
                if available < self.memory_floor * 2**30 and self.process is not None:
                    with self.state_lock:
                        self.error = 'Model stopped: available system RAM fell below the guard threshold'
                    self._stop()
            except (OSError, StopIteration):
                pass

    def _stop(self):
        with self.lifecycle:
            self._stop_worker()

    def _stop_worker(self):
        process, self.process = self.process, None
        self.active = None
        if process is None:
            return
        if self.contained:
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                subprocess.run(['systemctl', '--user', 'stop', self.unit + '.scope'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

    def switch(self, name):
        if name not in self.profiles:
            raise ValueError(f'Unknown model: {name}')
        settings = self.profiles[name][1].get('router', {})
        if settings.get('enabled') is False:
            raise ValueError(settings.get('disabled_reason') or 'This model profile is unavailable')
        with self.turn:
            if self.closed.is_set():
                raise RuntimeError('Router is shutting down')
            if self.active == name and self.process is not None and self.process.poll() is None:
                return
            with self.state_lock:
                self.loading, self.error = name, None
            try:
                self._stop()
                source, saved = self.profiles[name]
                cfg = dict(saved)
                cwd = Path(cfg.get('cwd') or source.parent).expanduser().resolve()
                cfg['cwd'] = str(cwd)
                for key in ('exe', 'tokenizer', 'log'):
                    if cfg.get(key) and not str(cfg[key]).startswith('@bundle/'):
                        value = Path(cfg[key]).expanduser()
                        cfg[key] = str(value if value.is_absolute() else cwd / value)
                if str(cfg['exe']).startswith('@bundle/'):
                    cfg['exe'] = str(ROOT / 'engines' / str(cfg['exe']).removeprefix('@bundle/'))
                if isinstance(cfg.get('vision'), dict):
                    cfg['vision'] = dict(cfg['vision'])
                    for key in ('exe', 'model', 'mmproj'):
                        value = cfg['vision'].get(key)
                        if value and str(value).startswith('@bundle/'):
                            cfg['vision'][key] = str(ROOT / 'engines' / str(value).removeprefix('@bundle/'))
                        elif value:
                            path = Path(value).expanduser()
                            cfg['vision'][key] = str(path if path.is_absolute() else cwd / path)
                cfg['args'] = [str(ROOT / arg.removeprefix('@bundle/'))
                               if isinstance(arg, str) and arg.startswith('@bundle/') else arg
                               for arg in cfg['args']]
                cfg['env'] = {key: str(ROOT / value.removeprefix('@bundle/'))
                              if isinstance(value, str) and value.startswith('@bundle/') else value
                              for key, value in cfg.get('env', {}).items()}
                cfg.update(model_name=name, aliases=[], host='127.0.0.1', api_key=self.secret,
                           allowed_hosts=[], trusted_origins=[], cors_origins=[], lazy_load=False,
                           open_browser=False)
                config = Path(self.directory.name) / 'active.json'
                config.write_text(json.dumps(cfg), encoding='utf-8')
                config.chmod(0o600)
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    self.port = sock.getsockname()[1]
                command = worker_command(config, self.port)
                if self.contained:
                    subprocess.run(['systemctl', '--user', 'reset-failed', self.unit + '.scope'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    command = ['systemd-run', '--user', '--scope', '--quiet', '--unit=' + self.unit,
                               '-p', 'MemoryMax=20G', '-p', 'MemorySwapMax=0', *command]
                env = dict(os.environ)
                env['STRATA_API_KEY'] = self.secret
                # Frozen Python's library path must not override the external HIP engine's runtime.
                if getattr(sys, 'frozen', False):
                    env['LD_LIBRARY_PATH'] = env.get('LD_LIBRARY_PATH_ORIG', '')
                with self.lifecycle:
                    self.process = subprocess.Popen(command, env=env, start_new_session=True)
                deadline = time.monotonic() + self.startup_timeout
                while time.monotonic() < deadline:
                    if self.process is None or self.process.poll() is not None:
                        raise RuntimeError(self.error or 'Model worker exited while loading; see terminal log')
                    connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=1)
                    try:
                        connection.request('GET', '/health', headers={'Authorization': 'Bearer ' + self.secret})
                        response = connection.getresponse()
                        response.read()
                        if response.status == 200:
                            self.active = name
                            return
                    except (OSError, http.client.HTTPException):
                        pass
                    finally:
                        connection.close()
                    self.closed.wait(.2)
                    if self.closed.is_set():
                        raise RuntimeError('Router stopped during model load')
                raise RuntimeError('Model load timed out')
            except Exception as exc:
                with self.state_lock:
                    self.error = str(exc)
                self._stop()
                raise
            finally:
                with self.state_lock:
                    self.loading = None

    def close(self):
        self.closed.set()
        self._stop()
        self.guard.join(timeout=2)
        self.directory.cleanup()


PAGE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Strata model router</title><style>
body{margin:0;background:#f8f9fb;color:#242429;font:14px system-ui}header{padding:12px 24px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #dedee6}
select,button,input{font:inherit;background:white;color:inherit;border:1px solid #dcdde5;border-radius:10px;padding:9px 12px}button{cursor:pointer}#load{background:#09b882;color:white;border-color:#09b882}button:disabled{opacity:.5;cursor:wait}
iframe{display:block;border:0;width:100%;height:calc(100vh - 64px)}#status{font-size:13px;color:#62656e}a{color:#2469b3}
@media(prefers-color-scheme:dark){body{background:#101522;color:#e5eaf5}header{border-color:#30394c}select,button,input{background:#202b40;border-color:#425477}#status{color:#c2cada}}
</style></head><body><header><b>Model</b><select id="models" aria-label="Model profile"></select>
<button id="load">Load model</button><button id="unload">Release memory</button>
<input id="key" type="password" placeholder="API key, if configured" aria-label="API key"><span id="status">Ready</span></header>
<iframe id="chat" title="Strata chat"></iframe><script>
const $=id=>document.getElementById(id);let initialized=false;
const headers=()=>({'Content-Type':'application/json',...($('key').value?{'Authorization':'Bearer '+$('key').value}:{})});
async function state(){try{let r=await fetch('/router/status',{headers:headers()});let s=await r.json();if(!r.ok)throw Error(s.error?.message||r.status);
if(!initialized){let catalog=await(await fetch('/v1/models',{headers:headers()})).json();for(let m of catalog.data){let o=document.createElement('option');o.value=m.id;o.textContent=m.name+(m.available===false?' (unavailable)':'');o.disabled=m.available===false;o.title=m.unavailable_reason||'';$('models').append(o)}$('models').value=s.active||s.default;if(s.active)$('chat').src='/chat/';initialized=true}
$('status').textContent=s.loading?'Loading '+s.loading+'…':s.error||(s.active?'Loaded: '+s.active:'No model loaded');}catch(e){$('status').textContent=e.message}}
async function action(path,body){$('load').disabled=$('unload').disabled=true;$('status').textContent='Waiting for active request, then switching…';try{
let r=await fetch(path,{method:'POST',headers:headers(),body:JSON.stringify(body)});let s=await r.json();if(!r.ok)throw Error(s.error?.message||r.status);
$('chat').src=path.endsWith('load')&&!path.endsWith('unload')?'/chat/':'';
}catch(e){$('status').textContent=e.message}finally{$('load').disabled=$('unload').disabled=false;await state()}}
$('load').onclick=()=>action('/router/load',{model:$('models').value});$('unload').onclick=()=>action('/router/unload',{});
$('key').onchange=async()=>{await fetch('/router/session',{method:'POST',headers:headers(),body:'{}'});initialized=false;$('models').replaceChildren();state()};state();setInterval(state,2000);
</script></body></html>'''


def handler(router, api_key=''):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass

        def reply(self, status, body, kind='application/json'):
            data = json.dumps(body).encode() if kind == 'application/json' else body.encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def error(self, status, message):
            self.close_connection = True
            self.reply(status, {'error': {'message': message, 'type': 'router_error'}})

        def dispatch(self):
            admitted = self.command != 'POST' or router.requests.acquire(blocking=False)
            if not admitted:
                self.error(429, 'Router queue is full; retry after the active requests finish')
                return
            try:
                self.route()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except ValueError as exc:
                self.error(400, str(exc))
            except (OSError, RuntimeError, http.client.HTTPException) as exc:
                self.error(503, str(exc))
            finally:
                if self.command == 'POST':
                    router.requests.release()

        def route(self):
            host = self.headers.get('Host', '')
            hostname = urlsplit('//' + host).hostname
            if hostname not in self.server.allowed_hosts:
                self.error(403, 'Unrecognized Host header')
                return
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                self.error(403, 'Cross-origin requests are not permitted')
                return
            forward_path = '/' + self.path[len('/chat/'):] if self.path.startswith('/chat/') else self.path
            path = urlsplit(forward_path).path
            if self.path == '/' and self.command == 'GET':
                self.reply(200, PAGE, 'text/html; charset=utf-8')
                return
            asked = self.headers.get('Authorization', '').removeprefix('Bearer ') or self.headers.get('x-api-key', '')
            from http.cookies import SimpleCookie
            cookie = SimpleCookie()
            with contextlib.suppress(Exception):
                cookie.load(self.headers.get('Cookie', ''))
            session = cookie.get('strata_router_session')
            browser_ok = session is not None and hmac.compare_digest(session.value, router.browser_token)
            if api_key and not hmac.compare_digest(asked.encode(), api_key.encode()) and not browser_ok:
                self.error(401, 'API key required')
                return
            body = b''
            if self.command == 'POST':
                if self.headers.get('Transfer-Encoding'):
                    self.error(400, 'Use Content-Length, not chunked request encoding')
                    self.close_connection = True
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= MAX_BODY:
                    self.error(413, 'Request body exceeds 32 MiB')
                    self.close_connection = True
                    return
                self.connection.settimeout(30)
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError('Incomplete request body')
            if path == '/router/session' and self.command == 'POST':
                data = b'{}'
                self.send_response(200)
                self.send_header('Set-Cookie', 'strata_router_session=' + router.browser_token + '; HttpOnly; SameSite=Strict; Path=/')
                self.send_header('Content-Length', '2')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(data)
                return
            if path == '/router/status' and self.command == 'GET':
                self.reply(200, router.status())
                return
            if path in ('/v1/models', '/models') and self.command == 'GET':
                status = router.status()
                self.reply(200, {'object': 'list', 'data': [
                    model_metadata(name, cfg, status) for name, (_, cfg) in router.profiles.items()]})
                return
            if path == '/health' and not router.active:
                self.reply(200, {'status': 'ok', 'model': router.default, 'images': False,
                                 'max_context': 0, **router.status()})
                return
            if path == '/router/load' and self.command == 'POST':
                req = json.loads(body)
                if not isinstance(req, dict) or not isinstance(req.get('model'), str):
                    raise ValueError('Provide a registered model name')
                router.switch(req['model'])
                self.reply(200, router.status())
                return
            if path == '/router/unload' and self.command == 'POST':
                with router.turn:
                    router._stop()
                self.reply(200, router.status())
                return
            if path.startswith('/router/'):
                self.error(404, 'Unknown router endpoint')
                return
            model = None
            if path in GENERATE | {'/v1/messages/count_tokens'} and self.command == 'POST':
                req = json.loads(body)
                if not isinstance(req, dict):
                    raise ValueError('Request must be a JSON object')
                model = req.get('model') or router.active or router.default
                if not isinstance(model, str) or model not in router.profiles:
                    self.error(404, 'Model is not registered')
                    return
            if model and path in GENERATE:
                cap = router.profiles[model][1].get('router', {}).get('max_output_tokens')
                if cap:
                    keys = ('max_output_tokens',) if path == '/v1/responses' else (
                        'max_completion_tokens', 'max_tokens') if path == '/v1/chat/completions' else ('max_tokens',)
                    for key in keys:
                        if key in req and req[key] is not None:
                            if isinstance(req[key], bool) or not isinstance(req[key], int):
                                raise ValueError(key + ' must be an integer')
                            req[key] = min(req[key], cap) if req[key] > 0 else cap
                    if not any(key in req and req[key] is not None for key in keys):
                        req[keys[-1]] = cap
                    body = json.dumps(req).encode()
            # Hold the lease until the last streamed byte: no worker can be replaced mid-response.
            with router.turn if self.command == 'POST' else contextlib.nullcontext():
                if model:
                    router.switch(model)
                elif not router.active:
                    self.error(503, 'No model loaded; select a model or send a generation request')
                    return
                target = forward_path
                profile_name = router.active
                headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in HOP | {'origin', 'authorization', 'x-api-key'}}
                headers.pop('Cookie', None)
                headers['Authorization'] = 'Bearer ' + router.secret
                headers['Content-Length'] = str(len(body))
                connection = http.client.HTTPConnection('127.0.0.1', router.port, timeout=600)
                started = False
                try:
                    connection.request(self.command, target, body=body or None, headers=headers)
                    response = connection.getresponse()
                    if path == '/web/app.js' and response.status == 200:
                        source = response.read().decode('utf-8')
                        source = profile_web_script(source, profile_name, router.profiles[profile_name][1])
                        self.reply(200, source, 'application/javascript; charset=utf-8')
                        return
                    if path == '/health' and response.status == 200:
                        health = json.loads(response.read())
                        health['api_key'] = bool(api_key)
                        self.reply(200, health)
                        return
                    self.send_response(response.status)
                    for key, value in response.getheaders():
                        if key.lower() not in HOP | {'access-control-allow-origin', 'access-control-allow-credentials'}:
                            self.send_header(key, value)
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    started = True
                    self.close_connection = True
                    while data := response.read1(65536):
                        self.wfile.write(data)
                        self.wfile.flush()
                except Exception:
                    if started:
                        self.close_connection = True
                        return
                    raise
                finally:
                    connection.close()

        do_GET = dispatch
        do_POST = dispatch
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'strata/router.json')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8096)
    parser.add_argument('--api-key', default=os.environ.get('STRATA_API_KEY', ''))
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--allowed-host', action='append', default=[], help='additional Host name or LAN IP for access')
    parser.add_argument('--no-containment', action='store_true', help='development only: disable systemd memory scope')
    args = parser.parse_args(argv)
    if args.host not in ('127.0.0.1', 'localhost') and not args.api_key:
        parser.error('A non-loopback bind requires --api-key')
    try:
        profiles, default = read_registry(args.registry)
        if not args.no_containment:
            if not Path('/sys/fs/cgroup/cgroup.controllers').is_file():
                raise ValueError('Requires Linux cgroup v2 and a systemd user manager')
            subprocess.run(['systemctl', '--user', 'show-environment'], check=True, stdout=subprocess.DEVNULL)
            if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'strata-local.scope']).returncode == 0:
                raise ValueError('Stop strata-local.scope before starting the router')
        router = Router(profiles, default, contained=not args.no_containment)
        server = ThreadingHTTPServer((args.host, args.port), handler(router, args.api_key))
        server.daemon_threads = True
        if not args.no_containment:
            import fcntl
            lockpath = Path(os.environ.get('XDG_RUNTIME_DIR', tempfile.gettempdir())) / ('strata-router-' + str(os.getuid()) + '.lock')
            instance_lock = open(lockpath, 'a')
            try:
                fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another Strata router is already running')
        server.allowed_hosts = {'127.0.0.1', 'localhost', args.host, *args.allowed_host}
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    def stop(*_):
        router.closed.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f'Strata router: http://{args.host}:{args.port}/ — {len(profiles)} profiles; models load on demand', flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://{args.host}:{args.port}/')
    try:
        server.serve_forever()
    finally:
        server.server_close()
        router.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
