"""Protect live configuration across the complete multi-stage shell install."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


LABELS = ("io.github.codex-router", "com.thibaultsaintjean.jev-router")


def runtime_paths() -> tuple[Path, Path, Path]:
    home = Path.home()
    codex = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser().resolve()
    state = Path(os.environ.get("MODEL_ROUTER_STATE_DIR")
                 or os.environ.get("CODEX_ROUTER_STATE_DIR")
                 or os.environ.get("KIMI_CODEX_STATE_DIR")
                 or codex / "codex-router").expanduser()
    if state.is_symlink():
        raise ValueError("state directory must not be a symlink")
    state = state.resolve()
    if codex.is_relative_to(state):
        raise ValueError("state directory cannot contain CODEX_HOME")
    return home, codex, state


def private_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Kernel-level refusal closes the gap between a link check and opening it.
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise ValueError("managed source must be a regular file")
        target_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(target_fd, "wb") as target:
            os.fchmod(target.fileno(), 0o600)
            with os.fdopen(os.dup(source_fd), "rb") as origin:
                shutil.copyfileobj(origin, target)
    finally:
        os.close(source_fd)


def protect_tree(root: Path) -> None:
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        owner_execute = bool(path.stat().st_mode & stat.S_IXUSR)
        path.chmod(0o700 if path.is_dir() or owner_execute else 0o600)


def begin() -> Path:
    home, codex, state = runtime_paths()
    folder = codex / "jev-install-backups"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or folder.resolve().is_relative_to(state):
        raise ValueError("backup location must be separate from router state")
    folder.chmod(0o700)
    backup = Path(tempfile.mkdtemp(prefix="install-", dir=folder))
    config = codex / "config.toml"
    manifest = {"version": 1, "codex_home": str(codex), "state": str(state),
                "config_present": config.exists(), "state_present": state.exists(),
                "services": {}}
    if config.exists():
        private_copy(config, backup / "config.toml")
    if state.exists():
        shutil.copytree(state, backup / "state", symlinks=True)
        protect_tree(backup / "state")
    for label in LABELS:
        plist = home / "Library/LaunchAgents" / f"{label}.plist"
        running = False
        if plist.exists() and sys.platform == "darwin":
            running = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                     capture_output=True, timeout=15).returncode == 0
        manifest["services"][label] = {"present": plist.exists(), "running": running}
        if plist.exists():
            private_copy(plist, backup / f"{label}.plist")
    (backup / "manifest.json").write_text(json.dumps(manifest))
    (backup / "manifest.json").chmod(0o600)
    return backup


def restore(backup: Path) -> None:
    home, codex, state = runtime_paths()
    manifest = json.loads((backup / "manifest.json").read_text())
    if (manifest["codex_home"], manifest["state"]) != (str(codex), str(state)):
        raise ValueError("backup belongs to different runtime paths")
    config = codex / "config.toml"
    if config.exists() and config.is_symlink():
        raise ValueError("refusing to overwrite a linked configuration")
    # Restore the direct client path first, before changing the service state.
    if manifest["config_present"]:
        fd, name = tempfile.mkstemp(prefix=".jev-config-restore-", dir=codex)
        os.close(fd)
        replacement = Path(name)
        try:
            private_copy(backup / "config.toml", replacement)
            replacement.replace(config)
        finally:
            replacement.unlink(missing_ok=True)
    else:
        config.unlink(missing_ok=True)
    # Quiesce every writer before replacing the shared state, and restart only
    # after all state and service definitions have been restored.
    if sys.platform == "darwin":
        for label, previous in manifest["services"].items():
            plist = home / "Library/LaunchAgents" / f"{label}.plist"
            if not plist.exists() and not previous["present"]:
                continue
            loaded = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                    capture_output=True, timeout=15).returncode == 0
            if loaded:
                stopped = subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                                         capture_output=True, timeout=15)
                if stopped.returncode:
                    raise RuntimeError(f"service stop failed for {label}")
    if state.exists():
        # Retain failed state privately for diagnosis rather than deleting it.
        shutil.move(str(state), str(backup / "failed-state"))
        protect_tree(backup / "failed-state")
    if manifest["state_present"]:
        shutil.copytree(backup / "state", state, symlinks=True)
        protect_tree(state)
    if sys.platform == "darwin":
        for label, previous in manifest["services"].items():
            plist = home / "Library/LaunchAgents" / f"{label}.plist"
            if previous["present"]:
                private_copy(backup / f"{label}.plist", plist)
            else:
                plist.unlink(missing_ok=True)
        for label, previous in manifest["services"].items():
            plist = home / "Library/LaunchAgents" / f"{label}.plist"
            if previous["running"]:
                started = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
                                         capture_output=True, timeout=15)
                if started.returncode:
                    raise RuntimeError(f"service restoration failed for {label}")
    (backup / "result.json").write_text('{"status":"restored"}\n')


def validate_catalog() -> None:
    _, _, state = runtime_paths()
    document = json.loads((state / "merged-models.json").read_text())
    models = document.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("installation requires a non-empty model catalog")
    print(json.dumps({"catalog_valid": True, "models": len(models)}))


def main() -> None:
    command = sys.argv[1]
    if command == "begin":
        print(begin())
    elif command == "restore":
        restore(Path(sys.argv[2]))
    elif command == "validate":
        validate_catalog()
    elif command == "commit":
        backup = Path(sys.argv[2])
        (backup / "result.json").write_text('{"status":"committed"}\n')
    else:
        raise ValueError("unknown transaction command")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Paths in errors are useful; secret-bearing service output is never emitted.
        print(f"Install transaction: {error}", file=sys.stderr)
        raise SystemExit(1)
