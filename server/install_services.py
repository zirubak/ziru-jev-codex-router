"""Exact launchd identities shared by installation and transaction recovery."""
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
from threading import Event
import time

JEV_LABEL = "com.thibaultsaintjean.jev-router"
LEGACY_JEV_LABEL = "io.0xnatoshi.jev-router"
ROUTER_LABELS = ("io.github.codex-router", "io.github.kimi-codex-router",
                 "com.ziwenxu.kimi-codex-proxy")


def wait_stopped(label: str, timeout: float = 15, executable: str = "launchctl") -> None:
    """bootout acknowledges termination before launchd removes the service."""
    deadline = time.monotonic() + timeout
    service = f"gui/{os.getuid()}/{label}"
    while (remaining := deadline - time.monotonic()) > 0:
        result = subprocess.run([executable, "print", service], capture_output=True,
                                timeout=min(5, remaining))
        if result.returncode == 113:  # launchd's absent-service status on macOS.
            return
        if result.returncode != 0:
            raise RuntimeError(f"cannot verify service removal: {label}")
        Event().wait(min(0.1, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"service shutdown deadline expired: {label}")


def jev_label() -> str:
    """Reject path components and control characters before touching launchd."""
    label = os.environ.get("JEV_ROUTER_LABEL", JEV_LABEL)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", label):
        raise ValueError("invalid Jev service label")
    if label in ROUTER_LABELS:
        raise ValueError("Jev service label conflicts with the embedded router")
    return label


def jev_labels() -> tuple[str, ...]:
    return tuple(dict.fromkeys((jev_label(), JEV_LABEL, LEGACY_JEV_LABEL)))


def all_labels() -> tuple[str, ...]:
    return (*ROUTER_LABELS, *jev_labels())


def read_regular(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("service ownership evidence must be a regular file")
        return source.read()


def router_sources(state: Path, source: Path) -> tuple[Path, ...]:
    """Accept the active source and the previous installer's recorded source."""
    current = Path(os.environ.get("CODEX_ROUTER_SOURCE_ROOT", str(source)))
    if not current.is_absolute():
        raise ValueError("CODEX_ROUTER_SOURCE_ROOT must be an absolute path")
    sources = {current.resolve()}
    manifest = state / "install-manifest.json"
    if manifest.exists() or manifest.is_symlink():
        data = json.loads(read_regular(manifest))
        record = data.get("current", {}) if isinstance(data, dict) else None
        if not isinstance(record, dict):
            raise ValueError("cannot verify the previous router service source")
        previous = record.get("sourceRoot")
        if previous is not None:
            if not isinstance(previous, str) or not Path(previous).is_absolute():
                raise ValueError("cannot verify the previous router service source")
            sources.add(Path(previous).resolve())
    return tuple(sorted(sources))


def router_owned(data: dict, codex: Path | None, state: Path | None,
                 sources: tuple[Path, ...]) -> bool:
    """Match the supported generator and the transaction's runtime anchors."""
    working = data.get("WorkingDirectory")
    environment = data.get("EnvironmentVariables")
    if (codex is None or state is None or not isinstance(working, str)
            or not Path(working).is_absolute() or not isinstance(environment, dict)):
        return False
    source = Path(working).resolve()
    if source not in sources or Path(data["ProgramArguments"][1]).resolve() != source / "src/start.mjs":
        return False
    anchors = {"CODEX_HOME": codex, **{key: state for key in (
        "MODEL_ROUTER_STATE_DIR", "CODEX_ROUTER_STATE_DIR", "KIMI_CODEX_STATE_DIR")}}
    for key, expected in anchors.items():
        value = environment.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute() or Path(value).resolve() != expected.resolve():
            return False
    configured = environment.get("CODEX_ROUTER_SOURCE_ROOT", working)
    return isinstance(configured, str) and Path(configured).is_absolute() and Path(configured).resolve() == source


def owned(path: Path, label: str, *, codex: Path | None = None,
          state: Path | None = None, sources: tuple[Path, ...] = ()) -> None:
    """A known label alone never authorizes stopping or replacing a program."""
    if label in ROUTER_LABELS[1:]:
        raise ValueError(f"unrecognized legacy service definition at {path}; preserve it and migrate it explicitly")
    data = plistlib.loads(read_regular(path))
    args = data.get("ProgramArguments", []) if isinstance(data, dict) else []
    if (not isinstance(data, dict) or data.get("Label") != label
            or not isinstance(args, list) or len(args) != 2
            or not all(isinstance(value, str) and Path(value).is_absolute() for value in args)):
        raise ValueError(f"foreign service definition at {path}")
    verified = (label in jev_labels() and args[1].endswith("/server/jev_server.py")) or (
        label == ROUTER_LABELS[0] and router_owned(data, codex, state, sources))
    if not verified:
        raise ValueError(f"foreign service definition at {path}")


def validate_definitions(home: Path, codex: Path, state: Path, sources: tuple[Path, ...]) -> None:
    for label in all_labels():
        path = home / "Library/LaunchAgents" / f"{label}.plist"
        if path.exists() or path.is_symlink():
            owned(path, label, codex=codex, state=state, sources=sources)
