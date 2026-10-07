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


APP_TOOLS_HEADER = '[plugins."codex-app-tools@openai-bundled".mcp_servers.codex_app.env]'
APP_TOOLS_BEGIN = "# BEGIN jev-desktop-app-tools-runtime v1\n"
APP_TOOLS_END = "# END jev-desktop-app-tools-runtime v1\n"


def trusted_node(app: Path) -> Path:
    """Require the OpenAI-signed bundle runtime rather than a cache or PATH copy."""
    node = app.absolute() / "Contents/Resources/cua_node/bin/node"
    if node.is_symlink() or not node.is_file() or not os.access(node, os.X_OK):
        raise ValueError("Desktop signed Node runtime is missing or not executable")
    requirement = 'anchor apple generic and identifier "node" and certificate leaf[subject.OU] = "2DC432GLL2"'
    try:
        result = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "-R",
                                 "=" + requirement, str(node)],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ValueError("Desktop Node signature validation failed")
        result = subprocess.run([str(node), "--version"], capture_output=True, text=True, timeout=10)
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
        if result.returncode or not match or tuple(map(int, match.groups())) < (22, 19, 0):
            raise ValueError("Desktop signed Node runtime requires Node.js 22.19 or newer")
    except subprocess.SubprocessError as error:
        raise ValueError("Desktop signed Node validation did not complete") from error
    return node


def app_tools_env(text: str) -> dict[str, object]:
    value = tomllib.loads(text)
    return value.get("plugins", {}).get("codex-app-tools@openai-bundled", {}).get(
        "mcp_servers", {}).get("codex_app", {}).get("env", {})


def app_tools_config(text: str, node: Path) -> str:
    """Own only the runtime leaf and preserve every unrelated byte."""
    env = app_tools_env(text)
    row = "CODEX_MCP_NODE_PATH = " + json.dumps(str(node)) + "\n"
    block = APP_TOOLS_BEGIN + row + APP_TOOLS_END
    if APP_TOOLS_BEGIN in text or APP_TOOLS_END in text:
        if text.count(APP_TOOLS_BEGIN) != 1 or text.count(APP_TOOLS_END) != 1:
            raise ValueError("ambiguous Desktop app tool runtime ownership")
        prefix, rest = text.split(APP_TOOLS_BEGIN)
        owned, suffix = rest.split(APP_TOOLS_END)
        parsed = tomllib.loads(owned)
        previous = parsed.get("CODEX_MCP_NODE_PATH")
        if (set(parsed) != {"CODEX_MCP_NODE_PATH"} or not isinstance(previous, str)
                or not Path(previous).is_absolute() or env.get("CODEX_MCP_NODE_PATH") != previous
                or "CODEX_MCP_NODE_PATH" in app_tools_env(prefix + suffix)):
            raise ValueError("foreign content inside Desktop app tool runtime ownership block")
        updated = prefix + block + suffix
    else:
        if "CODEX_MCP_NODE_PATH" in env:
            raise ValueError("Desktop app tool runtime ownership conflicts with user configuration")
        # Only splice into a proven standalone table; dotted or inline ownership
        # is ambiguous and must be resolved by the owner before any write.
        headers = list(re.finditer(r"(?m)^" + re.escape(APP_TOOLS_HEADER) + r"[ \t]*(?:#[^\n]*)?\n", text))
        if headers:
            if len(headers) != 1:
                raise ValueError("ambiguous Desktop app tool environment table")
            start = headers[0].end()
            following = re.search(r"(?m)^\s*\[", text[start:])
            end = start + following.start() if following else len(text)
            prefix, suffix = text[:end], text[end:]
            updated = prefix + ("\n" if prefix and not prefix.endswith("\n") else "") + block + suffix
        elif env:
            raise ValueError("Desktop app tool environment ownership requires a standalone table")
        else:
            updated = text + ("\n" if text and not text.endswith("\n") else "") + APP_TOOLS_HEADER + "\n" + block
    if app_tools_env(updated).get("CODEX_MCP_NODE_PATH") != str(node):
        raise ValueError("Desktop app tool runtime ownership is not structural")
    return updated


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
    node = trusted_node(app)
    config = codex / "config.toml"
    original = desktop_provider_registry.private_read(config) if config.exists() else b""
    app_tools_config(original.decode("utf-8"), node)
    desktop_provider_registry.split_owned(original.decode("utf-8"))
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
    wrapper += "\nCODEX_MCP_NODE_PATH=" + shlex.quote(str(node))
    wrapper += "\nexport JEV_DESKTOP_CONFIG CODEX_MCP_NODE_PATH\nexec " + " ".join(shlex.quote(str(value)) for value in (
        node, source / "router/bin/jev-desktop-codex")) + ' "$@"\n'
    private_write(destination / "jev-codex", wrapper.encode(), 0o700)
    desktop_provider_registry.install(config, provider)
    registered = desktop_provider_registry.private_read(config)
    updated = app_tools_config(registered.decode("utf-8"), node).encode("utf-8")
    if desktop_provider_registry.private_read(config) != registered:
        raise ValueError("configuration changed during Desktop app tool registration")
    private_write(config, updated, 0o600)
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
        trusted_node(Path("/Applications/ChatGPT.app"))
        codex = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        config = codex / "config.toml"
        original = desktop_provider_registry.private_read(config) if config.exists() else b""
        app_tools_config(original.decode("utf-8"), Path("/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node"))
        desktop_provider_registry.split_owned(original.decode("utf-8"))
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
