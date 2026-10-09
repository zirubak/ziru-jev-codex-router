"""Own the current user's persistent Desktop bridge selection without restarting apps."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import tempfile

from install_services import wait_stopped

LABEL = "io.github.jev-desktop-bridge"
ENVIRONMENT = "CODEX_CLI_PATH"


def private_read(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("refusing linked Desktop session file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Desktop session files must be owner-only regular files")
        with os.fdopen(os.dup(fd), "rb") as source:
            return source.read()
    finally:
        os.close(fd)


def private_write(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        private_read(path)
    fd, filename = tempfile.mkstemp(prefix=".jev-session-", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load(manifest: Path) -> dict[str, object]:
    if not manifest.is_absolute():
        raise ValueError("Desktop manifest must be absolute")
    data = json.loads(private_read(manifest))
    settings = data.get("session", {})
    if data.get("version") != 1 or settings.get("label") != LABEL:
        raise ValueError("invalid Desktop session manifest")
    for value in (data.get("bridgeLauncher"), settings.get("python"), settings.get("script")):
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("Desktop session executables must be absolute")
    wrapper = Path(data["bridgeLauncher"])
    if wrapper.parent != manifest.parent or wrapper.name != "jev-codex":
        raise ValueError("Desktop wrapper must belong to the manifest directory")
    private_read(wrapper)
    if wrapper.stat().st_mode & 0o100 == 0:
        raise ValueError("Desktop wrapper must be executable")
    return data


def run(arguments: list[str], gui: bool = False) -> subprocess.CompletedProcess:
    command = ["/bin/launchctl"]
    if gui:
        command += ["asuser", str(os.getuid()), "/bin/launchctl"]
    return subprocess.run(command + arguments, capture_output=True, text=True, timeout=15)


def environment() -> str:
    result = run(["getenv", ENVIRONMENT], gui=True)
    if result.returncode not in (0, 1):
        raise RuntimeError("cannot read the current GUI session environment")
    # launchctl adds one record newline; whitespace inside the value is owned
    # by its caller and must not be normalized into an apparently empty value.
    return (result.stdout or "").removesuffix("\n")


def replace_environment(expected: str, value: str) -> None:
    current = environment()
    if current == value:
        return
    if current != expected:
        raise ValueError("CODEX_CLI_PATH changed concurrently; foreign value was preserved")
    result = run(["setenv", ENVIRONMENT, value] if value else ["unsetenv", ENVIRONMENT], gui=True)
    if result.returncode:
        raise RuntimeError("cannot update the current GUI session environment")
    if environment() != value:
        raise RuntimeError("Desktop GUI environment readback failed")


def activate(manifest: Path) -> None:
    target = load(manifest)["bridgeLauncher"]
    current = environment()
    if current and current != target:
        raise ValueError("foreign CODEX_CLI_PATH conflicts with Desktop integration")
    if current != target:
        replace_environment(current, target)


def deactivate(manifest: Path, home: Path | None = None) -> None:
    target = load(manifest)["bridgeLauncher"]
    current = environment()
    if current and current != target:
        raise ValueError("foreign CODEX_CLI_PATH was preserved")
    # Use the rollback ownership checks to remove this user's registration only.
    previous = {"wrapper": target, "manifest": str(manifest), "environment": "",
                "service_present": False, "service_running": False}
    home = home or Path.home()
    prepare_restore(previous, home, None)
    finish_restore(previous, home, None)


def status(manifest: Path) -> dict[str, object]:
    target = load(manifest)["bridgeLauncher"]
    current = environment()
    return {"active": current == target, "conflict": bool(current and current != target)}


def owned_plist(content: bytes, wrapper: str, manifest: Path) -> bool:
    try:
        data = plistlib.loads(content)
    except plistlib.InvalidFileException:
        return False
    args = data.get("ProgramArguments", [])
    return (data.get("Label") == LABEL and data.get("JevDesktopOwner") == wrapper
            and isinstance(args, list) and len(args) == 4
            and all(isinstance(arg, str) for arg in args)
            and Path(args[0]).is_absolute() and Path(args[1]).is_absolute()
            and args[1].endswith("/server/desktop_session.py")
            and args[2:] == ["activate", str(manifest)] and data.get("RunAtLoad") is True)


def install(manifest: Path, home: Path | None = None) -> None:
    data = load(manifest)
    current = environment()
    if current and current != data["bridgeLauncher"]:
        raise ValueError("foreign CODEX_CLI_PATH conflicts with Desktop integration")
    directory = (home or Path.home()) / "Library/LaunchAgents"
    if directory.is_symlink():
        raise ValueError("refusing linked LaunchAgents directory")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("LaunchAgents directory has unsafe ownership or permissions")
    plist = directory / f"{LABEL}.plist"
    previous = private_read(plist) if plist.exists() or plist.is_symlink() else None
    if previous is not None and not owned_plist(previous, data["bridgeLauncher"], manifest):
        raise ValueError("foreign Desktop LaunchAgent was preserved")
    domain = f"gui/{os.getuid()}"
    loaded = run(["print", f"{domain}/{LABEL}"]).returncode == 0
    if loaded and previous is None:
        raise ValueError("foreign loaded Desktop LaunchAgent was preserved")
    settings = data["session"]
    content = plistlib.dumps({"Label": LABEL, "JevDesktopOwner": data["bridgeLauncher"],
        "ProgramArguments": [settings["python"], settings["script"], "activate", str(manifest)],
        "RunAtLoad": True, "ProcessType": "Background"})
    if previous != content:
        if loaded:
            if run(["bootout", f"{domain}/{LABEL}"]).returncode:
                raise RuntimeError("cannot stop previous Desktop session registration")
            wait_stopped(LABEL, executable="/bin/launchctl")
        loaded = False
        private_write(plist, content)
    if not loaded and run(["bootstrap", domain, str(plist)]).returncode:
        raise RuntimeError("cannot register Desktop session LaunchAgent")
    activate(manifest)


def snapshot(home: Path, state: Path) -> dict[str, object]:
    """Capture only integration-owned GUI state before any installation writes."""
    wrapper = str(state / "desktop/jev-codex")
    manifest = state / "desktop/manifest.json"
    current = environment()
    if current and current != wrapper:
        raise ValueError("foreign CODEX_CLI_PATH conflicts with Desktop integration")
    plist = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    present = plist.exists() or plist.is_symlink()
    if present and not owned_plist(private_read(plist), wrapper, manifest):
        raise ValueError("foreign Desktop LaunchAgent was preserved")
    loaded = run(["print", f"gui/{os.getuid()}/{LABEL}"]).returncode == 0
    if loaded and not present:
        raise ValueError("foreign loaded Desktop LaunchAgent was preserved")
    if loaded and current != wrapper:
        # Rebootstrapping RunAtLoad would re-enable an intentionally unset
        # environment, so this snapshot cannot be restored exactly.
        raise ValueError("Desktop registration is inactive; run Jev Codex.command before reinstalling")
    return {"wrapper": wrapper, "manifest": str(manifest), "environment": current,
            "service_present": present, "service_running": loaded}


def validate_restore(previous: dict[str, object], home: Path, original: bytes | None) -> Path:
    current = environment()
    if current not in (previous["environment"], previous["wrapper"]):
        raise ValueError("CODEX_CLI_PATH changed concurrently; foreign value was preserved")
    plist = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    if plist.exists() or plist.is_symlink():
        contents = private_read(plist)
        if contents != original and not owned_plist(contents, previous["wrapper"], Path(previous["manifest"])):
            raise ValueError("foreign Desktop LaunchAgent was preserved during rollback")
    elif run(["print", f"gui/{os.getuid()}/{LABEL}"]).returncode == 0:
        raise ValueError("foreign loaded Desktop LaunchAgent was preserved during rollback")
    return plist


def prepare_restore(previous: dict[str, object], home: Path, original: bytes | None) -> None:
    """Quiesce registration before the transaction replaces its referenced state."""
    validate_restore(previous, home, original)
    service = f"gui/{os.getuid()}/{LABEL}"
    if run(["print", service]).returncode == 0:
        if run(["bootout", service]).returncode:
            raise RuntimeError("cannot stop Desktop session registration for rollback")
        wait_stopped(LABEL, executable="/bin/launchctl")
    current = environment()
    if current != previous["environment"]:
        if current != previous["wrapper"]:
            raise ValueError("CODEX_CLI_PATH changed concurrently; foreign value was preserved")
        replace_environment(current, previous["environment"])


def finish_restore(previous: dict[str, object], home: Path, original: bytes | None) -> None:
    plist = validate_restore(previous, home, original)
    if original is None:
        plist.unlink(missing_ok=True)
    else:
        private_write(plist, original)
    if previous["service_running"]:
        if run(["bootstrap", f"gui/{os.getuid()}", str(plist)]).returncode:
            raise RuntimeError("cannot restore previous Desktop session registration")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("activate", "deactivate", "status"))
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(status(args.manifest)))
    else:
        {"activate": activate, "deactivate": deactivate}[args.command](args.manifest)


if __name__ == "__main__":
    main()
