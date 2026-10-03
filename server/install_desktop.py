"""Install an opt-in launcher inside the root transaction's private state tree."""
import json
import os
from pathlib import Path
import shlex
import shutil
import re
import sys
import stat
import subprocess
import tempfile
import tomllib

import desktop_provider_registry
import desktop_session


def verify_app(app: Path) -> dict[str, object]:
    """Qualify each signed build against the isolated native bridge contract."""
    node = shutil.which("node")
    if not node or not Path(node).is_absolute():
        raise ValueError("An absolute Node.js runtime is required for Desktop compatibility")
    probe = Path(__file__).resolve().parent.parent / "router/src/desktop-compatibility.mjs"
    try:
        result = subprocess.run([node, str(probe), "--app", str(app.resolve())],
                                capture_output=True, text=True, timeout=90)
    except subprocess.SubprocessError as error:
        raise ValueError("Desktop compatibility probe did not complete") from error
    if result.returncode:
        raise ValueError("Desktop compatibility validation failed; installation state was preserved")
    try:
        qualified = json.loads(result.stdout)
        keys = ("expectedAppSha256", "expectedNativeSha256", "contractDigest")
        if not isinstance(qualified, dict) or any(
                not isinstance(qualified.get(key), str)
                or not re.fullmatch(r"[a-f0-9]{64}", qualified[key]) for key in keys):
            raise ValueError("invalid compatibility fingerprints")
        if (type(qualified.get("contractVersion")) is not int or qualified["contractVersion"] != 1
                or not isinstance(qualified.get("nativeVersion"), str)
                or not qualified["nativeVersion"].strip()
                or len(qualified["nativeVersion"]) > 256):
            raise ValueError("invalid compatibility contract")
    except (ValueError, TypeError) as error:
        raise ValueError("Desktop compatibility probe returned an invalid result") from error
    return {key: qualified[key] for key in (*keys, "contractVersion", "nativeVersion")}


def private_write(destination: Path, content: bytes, mode: int) -> None:
    if destination.is_symlink():
        raise ValueError("refusing linked Desktop destination")
    if destination.exists():
        info = destination.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Desktop destination must be an owner-only regular file")
    fd, name = tempfile.mkstemp(prefix=".desktop-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            os.fchmod(output.fileno(), mode)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def install(codex: Path, state: Path, app: Path, source: Path, node: Path) -> Path:
    hashes = verify_app(app)
    codex, state, app, source, node = (path.absolute() for path in (codex, state, app, source, node))
    # Native threads and their route records must advance together. Keep route
    # records outside the install transaction's snapshotted/restored state.
    route_state = codex.resolve() / "jev-desktop-thread-routes"
    if route_state.is_symlink():
        raise ValueError("refusing linked Desktop route state")
    for managed in (state.resolve(), (codex / "jev-install-backups").resolve()):
        if route_state.is_relative_to(managed) or managed.is_relative_to(route_state):
            raise ValueError("Desktop route state must be separate from install state and backups")
    profile = tomllib.loads((codex / "jev.config.toml").read_text())
    provider = profile.get("model_providers", {}).get("jev-router")
    if not isinstance(provider, dict) or provider.get("base_url") != "http://127.0.0.1:4202/v1":
        raise ValueError("An isolated loopback Jev provider is required")
    if provider.get("requires_openai_auth") is not False:
        raise ValueError("Jev must not use the built-in OpenAI authentication path")
    desktop_provider_registry.validate_provider(provider)
    destination = state / "desktop"
    if destination.is_symlink() or state.is_symlink():
        raise ValueError("refusing linked Desktop state")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.stat().st_uid != os.getuid():
        raise ValueError("Desktop state must belong to the current user")
    destination.chmod(0o700)
    manifest_path = destination / "manifest.json"
    manifest = {
        "version": 1, "provider": provider, "codexHome": str(codex.resolve()),
        "bridgeLauncher": str(destination / "jev-codex"),
        "session": {"label": desktop_session.LABEL, "python": str(Path(sys.executable).resolve()),
                    "script": str(source / "server/desktop_session.py")},
        "routeStateDirectory": str(route_state),
        "nativeBinary": str(app / "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
        "appExecutable": str(app / "Contents/MacOS/ChatGPT"),
        "appAsar": str(app / "Contents/Resources/app.asar"),
        "bridgeBinary": str(source / "router/bin/jev-desktop-codex"),
        **hashes,
    }
    private_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode(), 0o600)
    wrapper = "#!/bin/sh\nJEV_DESKTOP_CONFIG=" + shlex.quote(str(manifest_path))
    wrapper += "\nexport JEV_DESKTOP_CONFIG\nexec " + " ".join(shlex.quote(str(value)) for value in (
        node, source / "router/bin/jev-desktop-codex")) + ' "$@"\n'
    private_write(destination / "jev-codex", wrapper.encode(), 0o700)
    desktop_provider_registry.install(codex / "config.toml", provider)
    command = "#!/bin/sh\nexec " + " ".join(shlex.quote(str(value)) for value in (
        node, source / "router/src/desktop-launch.mjs", manifest_path)) + "\n"
    launcher = destination / "Jev Codex.command"
    private_write(launcher, command.encode(), 0o700)
    desktop_session.install(manifest_path)
    return launcher


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify Desktop compatibility without changing installation state")
    args = parser.parse_args()
    if args.check:
        verify_app(Path("/Applications/ChatGPT.app"))
        print("Desktop compatibility verified; no installation state changed.")
        return
    from install_transaction import runtime_paths
    _, codex, state = runtime_paths()
    source = Path(__file__).resolve().parent.parent
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required")
    launcher = install(codex, state, Path("/Applications/ChatGPT.app"), source, Path(node))
    print(f"Desktop integration registered; quit and reopen the app to activate: {launcher}")


if __name__ == "__main__":
    main()
