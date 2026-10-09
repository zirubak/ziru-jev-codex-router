"""Serialize the Jev LaunchAgent before changing its exact service registrations."""
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from threading import Event

from install_services import jev_label, jev_labels, owned, wait_stopped


def document(source: Path, python: str) -> dict[str, object]:
    if not Path(python).is_absolute() or not os.access(python, os.X_OK):
        raise ValueError("Jev Python executable must be an absolute executable path")
    home = Path.home()
    codex = os.environ.get("CODEX_HOME", str(home / ".codex"))
    state = (os.environ.get("MODEL_ROUTER_STATE_DIR") or os.environ.get("CODEX_ROUTER_STATE_DIR")
             or os.environ.get("KIMI_CODEX_STATE_DIR") or str(Path(codex) / "codex-router"))
    environment = {"CODEX_HOME": codex, "CODEX_ROUTER_STATE_DIR": state}
    if os.environ.get("JEV_ENV_FILE"):
        environment["JEV_ENV_FILE"] = os.environ["JEV_ENV_FILE"]
    return {"Label": jev_label(), "ProgramArguments": [python, str(source / "server/jev_server.py")],
            "RunAtLoad": True, "KeepAlive": True, "WorkingDirectory": str(source),
            "StandardOutPath": str(home / "Library/Logs/jev-router.out.log"),
            "StandardErrorPath": str(home / "Library/Logs/jev-router.err.log"),
            "EnvironmentVariables": environment}


def launchctl(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *arguments], capture_output=True, timeout=15)


def service_pid(label: str) -> int | None:
    result = launchctl("print", f"gui/{os.getuid()}/{label}")
    match = re.search(rb"(?m)^\s*pid = (\d+)\s*$", result.stdout or b"")
    return int(match.group(1)) if result.returncode == 0 and match else None


def listener_pids() -> set[int]:
    result = subprocess.run(["lsof", "-nP", "-iTCP:4319", "-sTCP:LISTEN", "-Fp"],
                            capture_output=True, timeout=5)
    if result.returncode not in (0, 1) or result.stderr:
        raise RuntimeError("cannot verify Jev listener ownership")
    return {int(line[1:]) for line in result.stdout.splitlines()
            if re.fullmatch(rb"p\d+", line)}


def pause(seconds: float) -> None:
    Event().wait(seconds)


def wait_ready(label: str, python: str, source: Path, timeout: float = 15) -> None:
    """launchd bootstrap is asynchronous; wait for this PID to own a healthy port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = service_pid(label)
        listeners = listener_pids()
        if listeners and listeners != {pid}:
            raise RuntimeError("Jev port is owned by another process; it was not stopped")
        if pid and listeners == {pid}:
            result = subprocess.run([python, str(source / "server/healthcheck.py")],
                                    capture_output=True, timeout=6)
            if (result.returncode == 0 and service_pid(label) == pid
                    and listener_pids() == {pid}):
                return
        pause(min(0.1, max(0, deadline - time.monotonic())))
    raise RuntimeError("Jev service readiness deadline expired")


def install(source: Path, python: str) -> None:
    values = document(source, python)
    encoded = plistlib.dumps(values, fmt=plistlib.FMT_XML)
    if plistlib.loads(encoded) != values:
        raise ValueError("Jev service serialization did not round-trip")
    directory = Path.home() / "Library/LaunchAgents"
    if directory.is_symlink():
        raise ValueError("refusing linked LaunchAgents directory")
    directory.mkdir(parents=True, exist_ok=True)
    (Path.home() / "Library/Logs").mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    previous = []
    for label in jev_labels():
        path = directory / f"{label}.plist"
        loaded = launchctl("print", f"{domain}/{label}").returncode == 0
        if path.exists() or path.is_symlink():
            owned(path, label)
        elif loaded:
            raise ValueError(f"loaded Jev service has no recoverable definition: {label}")
        previous.append((label, path, loaded))
    owned_pids = {pid for label, _, loaded in previous if loaded
                  for pid in [service_pid(label)] if pid is not None}
    if listener_pids() - owned_pids:
        raise RuntimeError("Jev port is owned by another process; it was not stopped")
    descriptor, filename = tempfile.mkstemp(prefix=".jev-service-", dir=directory)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(encoded)
        for label, _, loaded in previous:
            if loaded:
                if launchctl("bootout", f"{domain}/{label}").returncode:
                    raise RuntimeError(f"Jev service stop failed: {label}")
                wait_stopped(label)
        destination = directory / f"{jev_label()}.plist"
        temporary.replace(destination)
        for label, path, _ in previous:
            if label != jev_label():
                path.unlink(missing_ok=True)
        if launchctl("bootstrap", domain, str(destination)).returncode:
            raise RuntimeError("Jev service bootstrap failed")
    finally:
        temporary.unlink(missing_ok=True)
    wait_ready(jev_label(), python, source)
    print(f"Jev Router service OK ({jev_label()})")


if __name__ == "__main__":
    try:
        install(Path(__file__).resolve().parents[1], os.environ["JEV_PYTHON"])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Jev service installation: {error}", file=sys.stderr)
        raise SystemExit(1)
