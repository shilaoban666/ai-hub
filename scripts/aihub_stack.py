"""WSL-only stack supervisor. Uses separate virtualenvs and process identities."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local-launch'
STATE.mkdir(exist_ok=True)
DATA = Path.home() / '.local/share/aihub/stack'
PROBE = '''
import hashlib,json,sys
from app.config import settings
def fingerprint(s): return hashlib.sha256(s.encode()).hexdigest()
overrides = getattr(settings, "route_target_overrides", {})
layers = json.load(sys.stdin)
if layers is not None:
    from app.route_overrides import canonical_overrides
    merged = {}
    for layer in (layers[0], overrides, layers[1]):
        merged.update(canonical_overrides(layer, settings.route_prefix_aliases))
    overrides = merged
print(json.dumps({"cors":settings.cors_origins,"assertion":fingerprint(settings.gateway_assertion_secret),"overrides":overrides,"session_https_only":getattr(settings,"session_https_only",False)}))
'''


def fail(message):
    raise RuntimeError(message)


def run(command, *, cwd=None, env=None, timeout=120):
    # Logs belong to their service; never echo loaded settings or credentials.
    completed = subprocess.run(command, cwd=cwd, env=env, timeout=timeout, check=False)
    if completed.returncode:
        fail(f'Command failed ({completed.returncode}): {Path(str(command[0])).name}; see output above.')


def identity(pid):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            return None
        return {'pid': pid, 'start': stat[19], 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'cwd': os.readlink(f'/proc/{pid}/cwd'), 'exe': os.readlink(f'/proc/{pid}/exe')}
    except (OSError, IndexError):
        return None


def state_file(name):
    return STATE / f'{name}.json'


def managed(name):
    try:
        record = json.loads(state_file(name).read_text())
        return record if record['identity'] == identity(record['identity']['pid']) else None
    except (OSError, KeyError, ValueError):
        return None


def stop(name):
    record = managed(name)
    if record:
        pid = record['identity']['pid']
        os.killpg(pid, signal.SIGTERM)
        for _ in range(100):
            if identity(pid) != record['identity']:
                break
            time.sleep(.1)
        if identity(pid) == record['identity']:
            os.killpg(pid, signal.SIGKILL)
        print(f'[OK] Stopped {name} PID={pid}', flush=True)
    state_file(name).unlink(missing_ok=True)


def http(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=3) as response:
        return json.load(response)


def wait_http(url, name, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not managed(name):
            fail(f'{name} exited; inspect {STATE / (name + ".log")}')
        try:
            return http(url)
        except (OSError, ValueError):
            time.sleep(.5)
    fail(f'{name} readiness timed out: {url}; inspect {STATE / (name + ".log")}')


def venv(name, project, install):
    directory = DATA / name
    python = directory / 'bin/python'
    requirements = project / 'requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = directory / '.requirements.sha256'
    if install:
        if not python.exists():
            run([sys.executable, '-m', 'venv', str(directory)])
        if not stamp.exists() or stamp.read_text() != digest:
            print(f'[INSTALL] {name} Python dependencies', flush=True)
            run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', str(requirements)], timeout=600)
            stamp.write_text(digest)
        check = subprocess.run([str(python), '-m', 'pip', 'check'], capture_output=True)
        required = subprocess.run([str(python), '-c', '''
from importlib.metadata import version
from pathlib import Path
from pip._vendor.packaging.requirements import Requirement
import sys
try:
    for line in Path(sys.argv[1]).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        requirement=Requirement(line)
        if requirement.marker and not requirement.marker.evaluate(): continue
        if version(requirement.name) not in requirement.specifier: sys.exit(1)
except Exception: sys.exit(1)
''', str(requirements)], capture_output=True)
        if check.returncode or required.returncode:
            run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], timeout=600)
            run([str(python), '-m', 'pip', 'check'])
    if not python.exists():
        fail(f'Missing {name} virtualenv. Run aihub.bat install/start to install dependencies.')
    return str(python)


def service_config(python, cwd, environment, override_layers=None):
    result = subprocess.run([python, '-c', PROBE], cwd=cwd, env=environment,
                            input=json.dumps(override_layers), capture_output=True, text=True, timeout=30)
    if result.returncode:
        fail(f'Cannot load configuration for {cwd.name}; check .env, route aliases and overrides. '
             'Each layer must be a JSON object with valid HTTP(S) targets and no conflicting aliases (no credentials printed).')
    return json.loads(result.stdout.splitlines()[-1])


def dependency_preflight(name, python, cwd, environment):
    try:
        result = subprocess.run([python, str(ROOT / 'scripts/aihub_dependency_probe.py'), name],
                                cwd=cwd, env=environment, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        fail(f'{name} database/Redis/key preflight timed out; check its .env and network access.')
    if result.returncode:
        # The probe emits only fixed labels, never raw connection exceptions.
        details = [line for line in result.stdout.splitlines() if line.startswith('[FAIL]')]
        fail(details[-1] if details else f'{name} dependency preflight failed; check its .env.')
    print(f'[OK] {name} database/Redis/key preflight', flush=True)


def check_service_port(name, port, allow_managed=False):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('0.0.0.0', int(port)))
            return
        except OSError:
            record = managed(name) if allow_managed else None
            if record:
                try:
                    command = Path(f'/proc/{record["identity"]["pid"]}/cmdline').read_bytes().split(b'\0')
                    if command[command.index(b'--port') + 1] == str(port).encode():
                        return
                except (OSError, ValueError, IndexError):
                    pass
            fail(f'{name}: port {port} is occupied by an unmanaged process. Stop it explicitly before retrying.')


def ensure_env_file(project, label, install):
    envfile = project / '.env'
    if envfile.is_file():
        return envfile
    local = project / '.env.local'
    if install and local.is_file():
        # Exclusive creation also protects against concurrent first launches.
        try:
            with envfile.open('xb') as stream:
                stream.write(local.read_bytes())
        except FileExistsError:
            return envfile
        print(f'[INIT] Created {envfile} from .env.local', flush=True)
        return envfile
    fail(f'Missing {label} configuration: add {envfile} or {local}.')


def linux_executable(path):
    if not path:
        return False
    try:
        candidate = Path(path)
        return candidate.is_file() and bool(candidate.stat().st_mode & 0o111)
    except OSError:
        return False


def native_cli(configured, install):
    target = configured or '/usr/local/bin/claude'
    if not Path(target).is_absolute() or str(Path(target).resolve()).startswith('/mnt/'):
        fail('CLAUDE_CODE_NATIVE_CLAUDE_BIN must be an absolute Linux executable path outside /mnt.')
    if linux_executable(target):
        check = subprocess.run(['sudo', '-n', '-u', 'nobody', 'env', 'HOME=/tmp', target, '--version'], capture_output=True, timeout=30)
        if check.returncode == 0:
            return target
    if not install:
        fail(f'Linux native Claude CLI is missing or inaccessible at {target}. Run aihub.bat install/start.')
    source = next((candidate for candidate in (Path(path).resolve() for path in (target, shutil.which('claude'), Path.home() / '.local/bin/claude') if path)
                   if not str(candidate).startswith('/mnt/') and linux_executable(candidate)), None)
    if source is None:
        DATA.mkdir(parents=True, exist_ok=True)
        installer = DATA / 'install-claude.sh'
        run(['curl', '-q', '-fL', '--retry', '2', '--connect-timeout', '15', '--max-time', '120',
             'https://claude.ai/install.sh', '-o', str(installer)], timeout=180)
        try:
            run(['bash', str(installer)], timeout=300)
        finally:
            installer.unlink(missing_ok=True)
        source = (Path.home() / '.local/bin/claude').resolve()
        if not linux_executable(source):
            fail('Official Linux Claude CLI installation failed. Check access to claude.ai and install the Linux native CLI manually.')
    if source != Path(target).resolve():
        run(['sudo', '-n', 'install', '-D', '-o', 'root', '-g', 'root', '-m', '0755', str(source), target])
    check = subprocess.run(['sudo', '-n', '-u', 'nobody', 'env', 'HOME=/tmp', target, '--version'], capture_output=True, timeout=30)
    if check.returncode:
        fail(f'Native users cannot execute {target}. Use a shared Linux path such as /usr/local/bin/claude.')
    return target


def backend_preflight(python, environment, install):
    cwd = ROOT / 'backend'
    probe = '''
import json
from database import settings
from sandbox import get_configured_sandbox_type
print(json.dumps({"sandbox":get_configured_sandbox_type(),"workspace":settings.user_workspace_root,"legacy":settings.claude_code_native_workspace_root,"claude":settings.claude_code_native_claude_bin,"channels":settings.weixin_ilink_enabled or settings.dingtalk_enabled}))
'''
    result = subprocess.run([python, '-c', probe], cwd=cwd, env=environment, capture_output=True, text=True)
    if result.returncode:
        fail('AI Hub settings could not load; configure root .env. No secrets printed.')
    config = json.loads(result.stdout.splitlines()[-1])
    if config['sandbox'] != 'native':
        fail('This launcher requires CLAUDE_CODE_SANDBOX_TYPE=native in root .env.')
    for path in (config['workspace'], config['legacy']):
        if path and (not Path(path).is_absolute() or str(Path(path).resolve()).startswith('/mnt/')):
            fail('Native workspaces must be absolute Linux filesystem paths, outside /mnt.')
    if subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode:
        fail('native sudo check failed. Run aihub.bat install to initialize a dedicated WSL service user.')
    environment['CLAUDE_CODE_NATIVE_CLAUDE_BIN'] = native_cli(config['claude'], install)
    if install:
        for path in (config['workspace'], config['legacy']):
            if path and not Path(path).exists():
                run(['sudo', '-n', 'install', '-d', '-o', 'root', '-g', 'root', '-m', '0755', path])
    result = subprocess.run([python, '_verify_channel_tables.py', '--required-if-enabled'], cwd=cwd, env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    if result.returncode:
        fail('Channel schema/database preflight failed. Check database connectivity and run the documented migration preview; migrations are not auto-applied.')
    print('[OK] native CLI, Linux workspace paths and channel schema', flush=True)
    return config


def start_service(name, python, cwd, arguments, environment, fingerprint, started):
    existing = managed(name)
    if existing:
        if existing.get('config') != fingerprint:
            fail(f'{name} is running with different launch settings; use restart.')
        print(f'[OK] Reusing {name} PID={existing["identity"]["pid"]}', flush=True)
        return
    port = arguments[-1] if '--port' in arguments else None
    if port:
        check_service_port(name, port)
    log = STATE / (name + '.log')
    with log.open('ab') as stream:
        proc = subprocess.Popen([python, *arguments], cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=stream, start_new_session=True)
    record = {'identity': identity(proc.pid), 'config': fingerprint, 'project': str(cwd)}
    if record['identity'] is None:
        fail(f'{name} exited immediately. Inspect {log}')
    state_file(name).write_text(json.dumps(record))
    started.append(name)
    print(f'[OK] Launched {name} PID={proc.pid} log={log}', flush=True)
    return proc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'restart', 'stop', 'status', 'doctor', 'install', 'rollback'])
    parser.add_argument('--gateway-root', default='')
    parser.add_argument('--iam-root', default='')
    parser.add_argument('--ports', default='{"frontend":15173,"backend":15174,"gateway":8080,"iam":9001}')
    parser.add_argument('--public-host', default='localhost')
    parser.add_argument('--overrides', default='{}')
    parser.add_argument('--transaction', default='')
    args = parser.parse_args()
    ports = json.loads(args.ports)
    if set(ports) != {'frontend', 'backend', 'gateway', 'iam'} or any(type(p) != int or not 1 <= p <= 65535 for p in ports.values()) or len(set(ports.values())) != 4:
        fail('Four distinct TCP ports (1..65535) are required.')
    gateway_project = Path(args.gateway_root).resolve() if args.gateway_root else None
    iam_project = Path(args.iam_root).resolve() if args.iam_root else None
    transaction = STATE / f'transaction-{uuid.UUID(args.transaction).hex}.json' if args.transaction else None
    if args.action == 'rollback':
        if transaction and transaction.is_file():
            for record in reversed(json.loads(transaction.read_text())):
                current = managed(record['name'])
                if current and current['identity'] == record['identity']:
                    stop(record['name'])
            transaction.unlink()
        return
    if args.action in {'start', 'restart', 'doctor', 'install'} and (not gateway_project or not iam_project):
        fail('Set both --gateway-root and --iam-root.')
    if args.action == 'stop':
        for name in ('gateway', 'channel-worker', 'backend', 'iam'):
            stop(name)
        return
    if args.action == 'status':
        for name in ('iam', 'backend', 'channel-worker', 'gateway'):
            record = managed(name)
            print(f'{name}: ' + (f'running PID={record["identity"]["pid"]}' if record else 'stopped'))
        return
    projects = {'iam': iam_project, 'gateway': gateway_project, 'backend': ROOT / 'backend'}
    install = args.action in {'start', 'restart', 'install'}
    for name, project in projects.items():
        if not (project / 'requirements.txt').is_file():
            fail(f'Missing project {project}. Install/clone it or set the corresponding service root explicitly.')
        ensure_env_file(ROOT if name == 'backend' else project,
                        'AI Hub' if name == 'backend' else name, install)
    pythons = {name: venv(name, project, install) for name, project in projects.items()}
    base = dict(os.environ, PYTHONUNBUFFERED='1')
    backend_env = dict(base, MODEL_GATEWAY_BASE_URL=f'http://127.0.0.1:{ports["backend"]}/api/model-gateway')
    config = backend_preflight(pythons['backend'], backend_env, install)
    cors = ','.join(dict.fromkeys(f'http://{host}:{ports["frontend"]}' for host in (args.public_host, 'localhost', '127.0.0.1')))
    iam_base = dict(base, CORS_ORIGINS=cors, SESSION_HTTPS_ONLY='false')
    gateway_base = dict(base, IAM_SERVICE_URL=f'http://127.0.0.1:{ports["iam"]}',
                        JWT_JWKS_URL=f'http://127.0.0.1:{ports["iam"]}/.well-known/jwks.json', CORS_ORIGINS=cors)
    iam_config = service_config(pythons['iam'], projects['iam'], iam_base)
    defaults = {'/aihub': f'http://127.0.0.1:{ports["backend"]}', '/iam': f'http://127.0.0.1:{ports["iam"]}'}
    gateway_config = service_config(pythons['gateway'], projects['gateway'], gateway_base,
                                    [defaults, json.loads(args.overrides)])
    if iam_config['assertion'] != gateway_config['assertion']:
        fail('IAM and Gateway GATEWAY_ASSERTION_SECRET differ. Set matching values in their own .env files.')
    overrides = gateway_config['overrides']
    if not {'/aihub', '/iam'} <= overrides.keys():
        fail('Route aliases must preserve the /aihub and /iam service prefixes.')
    gateway_base['ROUTE_TARGET_OVERRIDES'] = json.dumps(overrides)
    service_config(pythons['gateway'], projects['gateway'], gateway_base)  # validate before launching anything
    for name, environment in (('backend', backend_env), ('iam', iam_base), ('gateway', gateway_base)):
        dependency_preflight(name, pythons[name], projects[name], environment)
    if args.action in {'doctor', 'install'}:
        print('[OK] Stack prerequisites ready. Run start to launch services.')
        return
    files = [ROOT / '.env'] + [project / name for project in projects.values() for name in ('.env', '.env.' + base.get('APP_ENV', 'dev'), 'requirements.txt') if (project / name).is_file()]
    fingerprints = [hashlib.sha256(file.read_bytes()).hexdigest() for file in files]
    fingerprint = hashlib.sha256(json.dumps([ports, args.public_host, overrides, str(gateway_project), str(iam_project), fingerprints], sort_keys=True).encode()).hexdigest()
    for name in ('iam', 'backend', 'gateway'):
        check_service_port(name, ports[name], allow_managed=True)
    # Keep the existing stack alive until every dependency/configuration check
    # has passed. A failure above must never call stop().
    if args.action == 'restart':
        for name in ('gateway', 'channel-worker', 'backend', 'iam'):
            stop(name)
    started = []
    try:
        start_service('iam', pythons['iam'], projects['iam'], ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', str(ports['iam'])], iam_base, fingerprint, started)
        wait_http(f'http://127.0.0.1:{ports["iam"]}/health', 'iam')
        http(f'http://127.0.0.1:{ports["iam"]}/.well-known/jwks.json')
        start_service('backend', pythons['backend'], projects['backend'], ['-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', str(ports['backend'])], backend_env, fingerprint, started)
        wait_http(f'http://127.0.0.1:{ports["backend"]}/', 'backend')
        if config['channels']:
            start_service('channel-worker', pythons['backend'], projects['backend'], ['channel_worker.py'], backend_env, fingerprint, started)
            time.sleep(2)
            if not managed('channel-worker'):
                fail(f'Channel worker exited; inspect {STATE / "channel-worker.log"}')
        start_service('gateway', pythons['gateway'], projects['gateway'], ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', str(ports['gateway'])], gateway_base, fingerprint, started)
        health = wait_http(f'http://127.0.0.1:{ports["gateway"]}/gateway/health', 'gateway')
        table = health.get('data', health)['route_table']
        if table['error_count'] or not table['route_count']:
            fail('Gateway is listening but failed to load IAM database routes. Check IAM database connectivity.')
        for prefix in ('/aihub', '/iam'):
            active = table.get('target_overrides', {}).get(prefix, {})
            if not active.get('matched') or active.get('effective_target') != overrides[prefix]:
                fail(f'Gateway override for {prefix} is missing or unmatched; update api-gateway and check registered service prefixes.')
        print('[OK] WSL stack ready; IAM database routes loaded and local target overrides applied.', flush=True)
        if transaction:
            transaction.write_text(json.dumps([{'name': name, 'identity': managed(name)['identity']} for name in started]))
    except BaseException:
        for name in reversed(started):
            stop(name)
        raise


if __name__ == '__main__':
    try:
        with (STATE / 'wsl.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('Another WSL stack operation is running. Wait for it to finish.')
            main()
    except Exception as error:
        # Do not print connection strings or raw database exceptions.
        print(f'[FAIL] {error}', file=sys.stderr, flush=True)
        sys.exit(1)
