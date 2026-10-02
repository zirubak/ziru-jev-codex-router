"""Read-only checks before the macOS installation transaction."""
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import urllib.request


def check_runtime() -> None:
    if sys.platform != 'darwin':
        raise RuntimeError('Full installation requires macOS.')
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    result = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
    version = tuple(int(part) for part in result.stdout.strip().lstrip('v').split('.')[:2])
    if version < (22, 19):
        raise RuntimeError('Node.js 22.19 or newer is required.')


def check_key() -> None:
    path = Path(os.environ.get('JEV_ENV_FILE') or Path.home() / '.jev.env').expanduser()
    if not path.is_absolute():
        raise RuntimeError('JEV_ENV_FILE must be an absolute path.')
    if '~' in os.environ.get('JEV_ENV_FILE', ''):
        raise RuntimeError('Use an expanded absolute JEV_ENV_FILE path, such as $HOME/.jev.env.')
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise RuntimeError('TypeSafe key file must be owner-only, regular and owned by this user.')
        present = any(line.strip().startswith('TYPESAFE_API_KEY=') and
                      line.strip().split('=', 1)[1].strip().strip('"\'')
                      for line in path.read_text().splitlines())
    except (OSError, UnicodeError):
        raise RuntimeError('TypeSafe key file missing or unreadable; set JEV_ENV_FILE to its private path.') from None
    if not present:
        raise RuntimeError('TypeSafe key missing from private env file.')


def check_login() -> None:
    resolver = Path(__file__).resolve().parents[1] / 'router/src/codex-binary.mjs'
    code = "import {findCodexBinary} from " + json.dumps(resolver.as_uri()) + ";console.log(findCodexBinary() || '')"
    found = subprocess.run(['node', '--input-type=module', '-e', code],
                           capture_output=True, text=True, check=True, timeout=30)
    binary = found.stdout.strip()
    if not binary:
        raise RuntimeError('Codex executable not found. Install Codex Desktop first.')
    result = subprocess.run([binary, 'login', 'status'], capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Codex login is required. Sign in before installing.')


def managed_jev() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:4319/health', timeout=2) as response:
            data = json.load(response)
        return data.get('service') == 'jev-router' and data.get('ok') is True
    except (OSError, ValueError):
        return False


def check_jev_port() -> None:
    try:
        with socket.create_connection(('127.0.0.1', 4319), timeout=1):
            pass
    except ConnectionRefusedError:
        return
    if not managed_jev():
        raise RuntimeError('Port 4319 is occupied by an unknown service; no process was stopped.')


def managed_router() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:4202/health', timeout=2) as response:
            data = json.load(response)
        return data.get('service') == 'codex-router'
    except (OSError, ValueError):
        return False


def check_router_port() -> None:
    try:
        with socket.create_connection(('127.0.0.1', 4202), timeout=1):
            pass
    except ConnectionRefusedError:
        return
    if not managed_router():
        raise RuntimeError('Port 4202 is occupied by an unknown service; no process was stopped.')


def run(prepare: bool = False) -> None:
    check_runtime()
    if not prepare:
        check_key()
        check_login()
        check_jev_port()
        check_router_port()


if __name__ == '__main__':
    try:
        run('--prepare-only' in sys.argv)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Installation preflight failed; check runtimes and login.', file=sys.stderr)
        raise SystemExit(1)
