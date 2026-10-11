"""Protect live configuration across the complete multi-stage shell install."""
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlsplit

import desktop_session
from install_services import all_labels, router_sources, validate_definitions, wait_stopped
import install_config_rollback


LABELS = all_labels()


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
    route_state = (codex / "jev-desktop-thread-routes").resolve()
    for managed in (state, (codex / "jev-install-backups").resolve()):
        if route_state.is_relative_to(managed) or managed.is_relative_to(route_state):
            raise ValueError("Desktop route state must be separate from install state and backups")
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


def disabled_services() -> set[str]:
    if sys.platform != "darwin":
        return set()
    result = subprocess.run(["launchctl", "print-disabled", f"gui/{os.getuid()}"],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError("cannot snapshot launchd disabled state")
    return set(re.findall(r'"([^"\n]+)"\s*=>\s*true', result.stdout or ""))


def plan_config_cleanup(backup: Path) -> None:
    """Capture the real read-only cleaner, never arbitrary after-install edits."""
    snapshot = backup / "config.toml"
    if not snapshot.exists():
        snapshot = backup / "config-empty.toml"
        install_config_rollback.private_write(snapshot, b"")
    node = shutil.which("node")
    if node is None:
        raise ValueError("Node.js is required to plan configuration rollback")
    manager = Path(__file__).resolve().parents[1] / "router/src/config-manager.mjs"
    result = subprocess.run([node, str(manager), "cleanup-preview", str(snapshot)],
                            env={**os.environ, "CODEX_ROUTER_ISOLATED": "1"},
                            capture_output=True, text=True, timeout=20)
    try:
        planned = json.loads(result.stdout).get("cleaned") if result.returncode == 0 else None
    except (ValueError, TypeError, AttributeError):
        planned = None
    if not isinstance(planned, str):
        raise ValueError("configuration rollback planning failed; no installation changes made")
    install_config_rollback.private_write(backup / "config-expected.toml", planned.encode())


def begin() -> Path:
    home, codex, state = runtime_paths()
    sources = router_sources(state, Path(__file__).resolve().parents[1] / "router")
    validate_definitions(home, codex, state, sources)
    session = desktop_session.snapshot(home, state) if (
        sys.platform == "darwin" and os.environ.get("JEV_INSTALL_DESKTOP") == "1") else None
    folder = codex / "jev-install-backups"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or folder.resolve().is_relative_to(state):
        raise ValueError("backup location must be separate from router state")
    folder.chmod(0o700)
    backup = Path(tempfile.mkdtemp(prefix="install-", dir=folder))
    config = codex / "config.toml"
    manifest = {"version": 1, "codex_home": str(codex), "state": str(state),
                "config_present": config.exists(), "state_present": state.exists(),
                "profile_present": (codex / "jev.config.toml").exists(),
                "services": {}, "router_sources": [str(path) for path in sources]}
    if session is not None:
        manifest["desktop_session"] = session
        if session["service_present"]:
            private_copy(home / "Library/LaunchAgents" / f"{desktop_session.LABEL}.plist",
                         backup / f"{desktop_session.LABEL}.plist")
    if config.exists():
        private_copy(config, backup / "config.toml")
    plan_config_cleanup(backup)
    if manifest["profile_present"]:
        private_copy(codex / "jev.config.toml", backup / "jev.config.toml")
    if state.exists():
        shutil.copytree(state, backup / "state", symlinks=True)
        protect_tree(backup / "state")
    disabled = disabled_services()
    for label in all_labels():
        plist = home / "Library/LaunchAgents" / f"{label}.plist"
        running = False
        if sys.platform == "darwin":
            running = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                     capture_output=True, timeout=15).returncode == 0
        if running and not plist.exists():
            raise ValueError(f"loaded service has no recoverable definition: {label}")
        manifest["services"][label] = {"present": plist.exists(), "running": running,
                                       "disabled": label in disabled}
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
    # Validate every current definition before any rollback service mutation.
    # Never adopt a new source anchor from the failed install's current state.
    sources = tuple(Path(value) for value in manifest.get("router_sources", []))
    validate_definitions(home, codex, state, sources)
    # Revert only declared installer ownership; keep concurrent user settings.
    config_error = None
    try:
        install_config_rollback.restore(codex / "config.toml", backup, state)
    except ValueError as error:
        # A user config conflict does not prevent independent recovery of the
        # previous runtime and its stopped services. Preserve the partial verdict.
        config_error = error
    profile = codex / "jev.config.toml"
    if profile.is_symlink():
        raise ValueError("refusing to overwrite a linked profile")
    if manifest.get("profile_present"):
        private_copy(backup / "jev.config.toml", profile)
    else:
        profile.unlink(missing_ok=True)
    session = manifest.get("desktop_session")
    session_plist = backup / f"{desktop_session.LABEL}.plist"
    session_original = session_plist.read_bytes() if session and session["service_present"] else None
    if session is not None:
        desktop_session.prepare_restore(session, home, session_original)
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
                wait_stopped(label)
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
            if previous["present"] or previous["running"] or previous.get("disabled"):
                # launchd rejects bootstrap while disabled, even when the
                # snapshot was both loaded and disabled. Reapply it afterward.
                verb = "disable" if previous.get("disabled") and not previous["running"] else "enable"
                result = subprocess.run(["launchctl", verb, f"gui/{os.getuid()}/{label}"],
                                        capture_output=True, timeout=15)
                if result.returncode:
                    raise RuntimeError(f"service disabled-state restoration failed for {label}")
            if previous["running"]:
                started = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
                                         capture_output=True, timeout=15)
                if started.returncode:
                    raise RuntimeError(f"service restoration failed for {label}")
                if previous.get("disabled"):
                    disabled = subprocess.run(["launchctl", "disable", f"gui/{os.getuid()}/{label}"],
                                              capture_output=True, timeout=15)
                    if disabled.returncode:
                        raise RuntimeError(f"service disabled-state restoration failed for {label}")
    if session is not None:
        desktop_session.finish_restore(session, home, session_original)
    if config_error is not None:
        raise config_error
    install_config_rollback.private_write(backup / "result.json", b'{"status":"restored"}\n')


def validate_catalog() -> None:
    _, _, state = runtime_paths()
    document = json.loads((state / "merged-models.json").read_text())
    models = document.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("installation requires a non-empty model catalog")
    print(json.dumps({"catalog_valid": True, "models": len(models)}))


def router_endpoint(value: str | None) -> bool:
    if not value:
        return False
    url = urlsplit(value)
    ports = {4202, 4102, int(os.environ.get("CODEX_ROUTER_PORT", "4202"))}
    return url.hostname in {"127.0.0.1", "localhost", "::1"} and url.port in ports


def validate_isolation() -> None:
    _, codex, state = runtime_paths()
    config = codex / "config.toml"
    base = tomllib.loads(config.read_text()) if config.exists() else {}
    selected = base.get("model_provider", "openai")
    if selected in {"codex-router", "codex-router-signed", "jev-router", "jev-router-auto", "jev-router-manual",
                    "jev-router-sol", "jev-router-astra"}:
        raise ValueError("router cannot own the default Codex provider")
    if base.get("model", "").startswith("jev/"):
        raise ValueError("Jev cannot be the default Codex model")
    providers = base.get("model_providers", {})
    if any(router_endpoint(url) for url in [base.get("openai_base_url"),
           providers.get("openai", {}).get("base_url"), providers.get(selected, {}).get("base_url")]):
        raise ValueError("router cannot own the global OpenAI URL")
    if base.get("model_catalog_json") and Path(base["model_catalog_json"]).resolve() == state / "merged-models.json":
        raise ValueError("router catalog cannot be global")
    profile = tomllib.loads((codex / "jev.config.toml").read_text())
    validate_profile(profile, state)
    print(json.dumps({"isolation_valid": True}))


def validate_profile(profile: dict[str, object], state: Path) -> None:
    try:
        validate_profile_fields(profile, state)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError("Jev profile must use its own authenticated local provider") from error


def validate_profile_fields(profile: dict[str, object], state: Path) -> None:
    providers = profile.get("model_providers")
    if not isinstance(providers, dict):
        raise ValueError("profile providers must be a table")
    provider = providers.get("jev-router")
    if not isinstance(provider, dict):
        raise ValueError("Jev provider must be a table")
    auth = provider.get("auth", {})
    if not isinstance(auth, dict):
        raise ValueError("Jev authentication must be a table")
    command = auth.get("command")
    args = auth.get("args")
    catalog = profile.get("model_catalog_json")
    if (not isinstance(command, str) or not isinstance(catalog, str)
            or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args)):
        raise ValueError("Jev authentication and catalog must use string paths")
    port = int(os.environ.get("CODEX_ROUTER_PORT", "4202"))
    if (profile.get("model_provider") != "jev-router" or profile.get("model") != "jev/auto"
            or provider.get("requires_openai_auth") is not False
            or provider.get("base_url") != f"http://127.0.0.1:{port}/v1"
            or provider.get("wire_api") != "responses"
            or Path(catalog).resolve() != state / "merged-models.json"
            or not Path(command).is_absolute()
            or len(args) != 2
            or not args[0].endswith("/src/caller-key-auth-command.mjs")
            or Path(args[1]).resolve() != state / "caller-secret"
            or "openai_base_url" in profile):
        raise ValueError("Jev profile must use its own authenticated local provider")


def main() -> None:
    command = sys.argv[1]
    if command == "begin":
        print(begin())
    elif command == "restore":
        restore(Path(sys.argv[2]))
    elif command == "validate":
        validate_catalog()
    elif command == "validate-isolation":
        validate_isolation()
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
