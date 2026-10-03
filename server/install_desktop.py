"""Install an opt-in launcher inside the root transaction's private state tree."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import tomllib


SUPPORTED_HASHES = {
    "expectedAppSha256": "c662897ab25e819cd97a7981cf34d10eefcb9243095d527d27adff71bc18af0a",
    "expectedNativeSha256": "1180e2d56ea06ec583092acd933345685da3441cb1769a436d76dbf320613e75",
}


def verify_app(app: Path) -> dict[str, str]:
    """Pin the actual protocol and picker build, not a marketing version."""
    artifacts = {
        "expectedAppSha256": app / "Contents/Resources/app.asar",
        "expectedNativeSha256": app / "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    }
    hashes = {}
    for key, file in artifacts.items():
        with file.open("rb") as artifact:
            hashes[key] = hashlib.file_digest(artifact, "sha256").hexdigest()
    if hashes != SUPPORTED_HASHES:
        raise ValueError(
            "Unverified Desktop build; keep ordinary Codex until compatibility is tested. "
            "Verified adapter: Desktop 12776 / bundled CLI 0.159.0-alpha.12.1. "
            "For CLI routing, run ./install.sh without --desktop, then codex -p jev. "
            "Do not replace compatibility hashes without native validation.")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                   check=True, capture_output=True, timeout=60)
    return hashes


def private_write(destination: Path, content: bytes, mode: int) -> None:
    if destination.is_symlink():
        raise ValueError("refusing linked Desktop destination")
    if destination.exists():
        info = destination.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Desktop destination must be an owned regular file")
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
    destination = state / "desktop"
    if destination.is_symlink() or state.is_symlink():
        raise ValueError("refusing linked Desktop state")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.stat().st_uid != os.getuid():
        raise ValueError("Desktop state must belong to the current user")
    destination.chmod(0o700)
    manifest_path = destination / "manifest.json"
    manifest = {
        "version": 1, "provider": provider,
        "routeStateDirectory": str(route_state),
        "nativeBinary": str(app / "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
        "appExecutable": str(app / "Contents/MacOS/ChatGPT"),
        "appAsar": str(app / "Contents/Resources/app.asar"),
        "bridgeBinary": str(source / "router/bin/jev-desktop-codex"),
        **hashes,
    }
    private_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode(), 0o600)
    command = "#!/bin/sh\nexec " + " ".join(shlex.quote(str(value)) for value in (
        node, source / "router/src/desktop-launch.mjs", manifest_path)) + "\n"
    launcher = destination / "Jev Codex.command"
    private_write(launcher, command.encode(), 0o700)
    return launcher


def main() -> None:
    import argparse
    import shutil
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
    print(f"Desktop launcher prepared, not started: {launcher}")


if __name__ == "__main__":
    main()
