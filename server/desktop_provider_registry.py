"""Register recovery-only provider names without changing native routing defaults."""
import json
import os
from pathlib import Path
import stat
import tempfile
import tomllib


BEGIN = "# BEGIN jev-desktop-recovery-providers v1\n"
END = "# END jev-desktop-recovery-providers v1\n"
LEGACY_NAMES = ("jev-router-auto", "jev-router-manual")
NAMES = (*LEGACY_NAMES, "jev-router-sol", "jev-router-astra")
HEADER = {"x-jev-desktop-recovery": "required"}


def private_read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Desktop registry requires an owner-only regular configuration")
        with os.fdopen(os.dup(fd), "rb") as source:
            return source.read()
    finally:
        os.close(fd)


def validate_provider(provider: dict[str, object], recovery: bool = False) -> None:
    allowed = {"name", "base_url", "wire_api", "requires_openai_auth", "auth"}
    if recovery:
        allowed.add("http_headers")
    if not allowed <= set(provider) or set(provider) - allowed - {"supports_standalone_web_search"}:
        raise ValueError("Recovery provider must use command authentication without inline credentials")
    auth = provider.get("auth")
    if (not isinstance(auth, dict) or not {"command", "args"} <= set(auth)
            or set(auth) - {"command", "args", "timeout_ms", "refresh_interval_ms"}):
        raise ValueError("Recovery provider requires command authentication")
    for key in ("timeout_ms", "refresh_interval_ms"):
        if key in auth and (type(auth[key]) is not int or auth[key] < 0):
            raise ValueError("Recovery authentication timing must be a nonnegative integer")
    if "supports_standalone_web_search" in provider and type(provider["supports_standalone_web_search"]) is not bool:
        raise ValueError("Recovery capability must be boolean")
    command, args = auth["command"], auth["args"]
    if (not isinstance(command, str) or not Path(command).is_absolute()
            or not isinstance(args, list) or len(args) != 2
            or not all(isinstance(arg, str) and Path(arg).is_absolute() for arg in args)
            or not args[0].endswith("/src/caller-key-auth-command.mjs")
            or Path(args[1]).name != "caller-secret"):
        raise ValueError("Recovery provider authentication must reference protected credential files")
    if (not isinstance(provider["name"], str)
            or provider["base_url"] != "http://127.0.0.1:4202/v1"
            or provider["wire_api"] != "responses"
            or provider["requires_openai_auth"] is not False
            or recovery and provider["http_headers"] != HEADER):
        raise ValueError("Recovery provider transport does not match the isolated loopback contract")


def split_owned(text: str) -> tuple[str, str]:
    """Prove block ownership structurally before replacing its original bytes."""
    parsed = tomllib.loads(text)
    names = set(parsed.get("model_providers", {})) & set(NAMES)
    if BEGIN not in text and END not in text:
        if names:
            raise ValueError("foreign Desktop provider definition conflicts with recovery registration")
        return text, ""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("ambiguous Desktop recovery ownership markers")
    prefix, remainder = text.split(BEGIN)
    owned, suffix = remainder.split(END)
    if (prefix and not prefix.endswith("\n")) or BEGIN in suffix:
        raise ValueError("invalid Desktop recovery ownership boundary")
    document = tomllib.loads(owned)
    if (set(document) != {"model_providers"}
            or set(document["model_providers"]) not in (set(LEGACY_NAMES), set(NAMES))):
        raise ValueError("foreign content inside Desktop recovery block")
    owned_names = set(document["model_providers"])
    if names != owned_names or any(
            parsed["model_providers"][name] != document["model_providers"][name] for name in owned_names):
        raise ValueError("Desktop recovery markers do not own the parsed provider definitions")
    for provider in document["model_providers"].values():
        validate_provider(provider, recovery=True)
    # Parsing the outside independently catches quoted and dotted conflicting keys.
    outside = tomllib.loads(prefix + suffix)
    if set(outside.get("model_providers", {})) & set(NAMES):
        raise ValueError("foreign Desktop provider exists outside its managed block")
    return prefix, suffix


def render(provider: dict[str, object], *, legacy: bool = False) -> str:
    rows = [BEGIN.rstrip("\n")]
    for name in LEGACY_NAMES if legacy else NAMES:
        rows.append(f"[model_providers.{name}]")
        for key in ("name", "base_url", "wire_api", "requires_openai_auth", "supports_standalone_web_search"):
            if key in provider:
                rows.append(f"{key} = {json.dumps(provider[key], ensure_ascii=False)}")
        rows.append(f"[model_providers.{name}.auth]")
        for key, value in provider["auth"].items():
            rows.append(f"{key} = {json.dumps(value)}")
        rows.extend([f"[model_providers.{name}.http_headers]",
                     'x-jev-desktop-recovery = "required"'])
    return "\n".join(rows) + "\n" + END


def install(config: Path, provider: dict[str, object]) -> None:
    validate_provider(provider)
    if config.is_symlink():
        raise ValueError("refusing linked Desktop registry configuration")
    original = private_read(config) if config.exists() else b""
    prefix, suffix = split_owned(original.decode("utf-8"))
    separator = "\n" if prefix and not prefix.endswith("\n") else ""
    updated = (prefix + separator + render(provider) + suffix).encode("utf-8")
    tomllib.loads(updated.decode("utf-8"))
    if original == updated:
        return
    descriptor, filename = tempfile.mkstemp(prefix=".jev-registry-", dir=config.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(updated)
        if (private_read(config) if config.exists() else b"") != original:
            raise ValueError("configuration changed concurrently during Desktop registration")
        temporary.replace(config)
    finally:
        temporary.unlink(missing_ok=True)
