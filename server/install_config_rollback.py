"""Undo declared configuration ownership without reverting concurrent user edits."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib


ROUTER_BLOCKS = (
    "codex-router-managed", "codex-router-provider-managed",
    "codex-router-signed-provider-managed", "codex-router-agent-concurrency-managed",
    "codex-router-multi-agent-v2-managed", "codex-router-standalone-web-search-managed",
    "kimi-codex-router-managed", "kimi-codex-proxy-managed",
)
DESKTOP_BLOCKS = ("jev-desktop-recovery-providers v1", "jev-desktop-app-tools-runtime v1")
ENV_HEADER = '[plugins."codex-app-tools@openai-bundled".mcp_servers.codex_app.env]'
BLOCKS = (*ROUTER_BLOCKS, *DESKTOP_BLOCKS)
ROOT_KEYS = {"model", "model_provider", "model_reasoning_effort", "openai_base_url",
             "model_catalog_json", "max_concurrent_threads_per_session", "multi_agent_v2",
             "supports_standalone_web_search", "web_search"}
PROVIDER_KEYS = {"name", "base_url", "wire_api", "requires_openai_auth",
                 "supports_standalone_web_search", "env_key", "http_headers", "auth"}


@dataclass(frozen=True)
class Block:
    name: str
    text: str
    start: int
    end: int


def read(path: Path) -> bytes | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("configuration conflict: not a regular file")
        return source.read()


def comment_offsets(text: str, *, code: bool = False) -> set[int]:
    """Identify top-level TOML lines without adopting string or array content."""
    offsets: set[int] = set()
    index, line_start = 0, 0
    quote = ""
    depth = 0
    while index < len(text):
        if code and index == line_start and not quote and not depth:
            offsets.add(index)
        if text[index] == "\n":
            line_start = index + 1
        if quote:
            if quote.startswith('"') and text[index] == "\\":
                if index + 1 < len(text) and text[index + 1] == "\n":
                    line_start = index + 2
                index += 2
                continue
            if text.startswith(quote, index):
                # TOML permits one or two literal quote characters immediately
                # before a multiline closing delimiter (four/five-quote runs).
                stop = index + len(quote)
                if len(quote) == 3:
                    while stop < len(text) and text[stop] == quote[0]:
                        stop += 1
                index = stop
                quote = ""
                continue
        elif text[index] in ('"', "'"):
            character = text[index]
            quote = character * (3 if text.startswith(character * 3, index) else 1)
            index += len(quote)
            continue
        elif text[index] == "#":
            if not code and not depth and not text[line_start:index].strip():
                offsets.add(index)
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        elif text[index] in "[{":
            depth += 1
        elif text[index] in "]}":
            depth -= 1
        index += 1
    return offsets


def blocks(text: str) -> dict[str, Block]:
    found = {}
    comments = comment_offsets(text)
    for name in BLOCKS:
        begin, end = f"# BEGIN {name}", f"# END {name}"
        starts = [match for match in re.finditer(r"(?m)^" + re.escape(begin) + r"\r?$", text)
                  if match.start() in comments]
        ends = [match for match in re.finditer(r"(?m)^" + re.escape(end) + r"\r?(?:\n|$)", text)
                if match.start() in comments]
        if not starts and not ends:
            continue
        if len(starts) != 1 or len(ends) != 1 or starts[0].start() >= ends[0].start():
            raise ValueError("configuration conflict: ambiguous ownership markers")
        start, stop = starts[0].start(), ends[0].end()
        found[name] = Block(name, text[start:stop], start, stop)
    spans = sorted((block.start, block.end) for block in found.values())
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("configuration conflict: overlapping ownership markers")
    return found


def validate_router_block(block: Block) -> None:
    """Foreign tables or keys inside a marker are never implicitly installer-owned."""
    data = tomllib.loads(block.text)
    providers = data.pop("model_providers", {})
    if set(data) - ROOT_KEYS or not isinstance(providers, dict):
        raise ValueError("configuration conflict: foreign content inside managed block")
    for name, provider in providers.items():
        if (name not in {"codex-router", "codex-router-signed", "kimi-codex-router", "kimi-codex-proxy"}
                or not isinstance(provider, dict) or set(provider) - PROVIDER_KEYS):
            raise ValueError("configuration conflict: foreign provider content inside managed block")


def desktop_expected(state: Path) -> dict[str, str]:
    manifest = state / "desktop/manifest.json"
    if not manifest.exists():
        return {}
    data = json.loads(read(manifest) or b"{}")
    if not isinstance(data, dict) or "provider" not in data:
        return {}
    # Expected bytes come from the installer's manifest, never an after-the-fact
    # snapshot of arbitrary live config edits.
    from desktop_provider_registry import render, validate_provider
    validate_provider(data["provider"])
    app = Path(data["appExecutable"])
    if not app.is_absolute() or app.parent.name != "MacOS":
        raise ValueError("configuration conflict: invalid Desktop manifest")
    node = app.parent.parent / "Resources/cua_node/bin/node"
    name = DESKTOP_BLOCKS[1]
    runtime = (f"# BEGIN {name}\nCODEX_MCP_NODE_PATH = {json.dumps(str(node))}\n"
               f"# END {name}\n")
    return {DESKTOP_BLOCKS[0]: render(data["provider"]), name: runtime}


def table_identity(header: str) -> str:
    return json.dumps(tomllib.loads(header + "\n__jev_boundary__ = true\n"), sort_keys=True)


def table_headers(text: str) -> list[tuple[int, int, str]]:
    """Find actual table headers and compare their parsed TOML identities."""
    tomllib.loads(text)
    headers: list[tuple[int, int, str]] = []
    for start in sorted(comment_offsets(text, code=True)):
        end = text.find("\n", start)
        end = len(text) if end < 0 else end + 1
        header = text[start:end].strip()
        if not header.startswith("["):
            continue
        # Parsing a header alone canonicalizes quoted/dotted names and comments
        # without guessing which bracket-looking lines belong to user values.
        identity = table_identity(header)
        headers.append((start, end, identity))
    return headers


def insertion_point(original: str, block: Block, current: str) -> int:
    """Restore a removed block within its original TOML table, never across one."""
    headers = [header for header in table_headers(original) if header[0] < block.start]
    context = headers[-1][2] if headers else None
    live = table_headers(current)
    if context is None:
        return live[0][0] if live else len(current)
    matches = [index for index, header in enumerate(live) if header[2] == context]
    if len(matches) != 1:
        raise ValueError("configuration conflict: original table boundary changed")
    following = matches[0] + 1
    return live[following][0] if following < len(live) else len(current)


def runtime_context(text: str, block: Block) -> tuple[int, int, str]:
    """The runtime marker owns one leaf only within the real app-tools env table."""
    value = tomllib.loads(block.text)
    node = value.get("CODEX_MCP_NODE_PATH")
    if set(value) != {"CODEX_MCP_NODE_PATH"} or not isinstance(node, str) or not Path(node).is_absolute():
        raise ValueError("configuration conflict: foreign content inside Desktop runtime block")
    headers = [header for header in table_headers(text) if header[0] < block.start]
    if not headers or headers[-1][2] != table_identity(ENV_HEADER):
        raise ValueError("configuration conflict: Desktop runtime block is outside its owned env table")
    return headers[-1]


def removed_root_slots(before: str, live: str, planned: bytes | None,
                       baseline: dict[str, Block]) -> list[Block]:
    """Only the real cleaner's predeclared root changes are rollback-owned."""
    if planned is None:
        return []
    original, expected, current = tomllib.loads(before), tomllib.loads(planned.decode()), tomllib.loads(live)
    syntax = comment_offsets(before, code=True)
    table = next((offset for offset in sorted(syntax) if before[offset:].lstrip().startswith("[")), len(before))
    removed = []
    for key in ("model", "model_provider", "model_catalog_json", "openai_base_url"):
        if original.get(key) == expected.get(key) or current.get(key) == original.get(key):
            continue
        if current.get(key) != expected.get(key):
            raise ValueError("configuration conflict: an installer-owned root setting changed concurrently")
        pattern = r"(?m)^[ \t]*(?:" + re.escape(key) + r"|[\"']" + re.escape(key) + r"[\"'])[ \t]*=[^\n]*(?:\n|$)"
        rows = [match for match in re.finditer(pattern, before)
                if match.start() in syntax and match.start() < table]
        if len(rows) != 1:
            raise ValueError("configuration conflict: ambiguous root setting boundary")
        match = rows[0]
        if any(block.start <= match.start() < block.end for block in baseline.values()):
            continue
        if tomllib.loads(match.group(0)) != {key: original.get(key)} or key in expected:
            raise ValueError("configuration conflict: unsupported root setting transform")
        removed.append(Block("root:" + key, match.group(0), match.start(), match.end()))
    return removed


def merge(original: bytes | None, current: bytes | None, state: Path,
          planned: bytes | None = None) -> bytes | None:
    if original == current:
        return current
    if planned is not None and (current or b"") == planned:
        return original
    before, live = (original or b"").decode(), (current or b"").decode()
    baseline, present = blocks(before), blocks(live)
    expected = desktop_expected(state) if any(name in present for name in DESKTOP_BLOCKS) else {}
    # Validate every change before constructing any replacement.
    for name in baseline.keys() | present.keys():
        old, new = baseline.get(name), present.get(name)
        if old and new and old.text == new.text:
            continue
        if name in ROUTER_BLOCKS:
            if old:
                validate_router_block(old)
            if new:
                raise ValueError("configuration conflict: managed router block changed concurrently")
        else:
            if new and new.text != expected.get(name):
                raise ValueError("configuration conflict: Desktop block differs from installer output")
            if name == DESKTOP_BLOCKS[1]:
                if old:
                    runtime_context(before, old)
                if new:
                    runtime_context(live, new)
            elif old:
                from desktop_provider_registry import split_owned
                split_owned(before)
    roots = removed_root_slots(before, live, planned, baseline)
    deleted = [block for name, block in baseline.items() if name not in present] + roots
    expected_without_deleted = before
    for block in sorted(deleted, key=lambda item: item.start, reverse=True):
        expected_without_deleted = expected_without_deleted[:block.start] + expected_without_deleted[block.end:]
    if deleted and live == expected_without_deleted:
        return original
    merged = live
    for name, new in sorted(present.items(), key=lambda pair: pair[1].start, reverse=True):
        old = baseline.get(name)
        if name in DESKTOP_BLOCKS and (old is None or old.text != new.text):
            merged = merged[:new.start] + (old.text if old else "") + merged[new.end:]
    for old in sorted(deleted, key=lambda block: block.start):
        at = insertion_point(before, old, merged)
        merged = merged[:at] + old.text + merged[at:]
    # The manifest proves runtime-leaf ownership, not creation of its table.
    # A harmless empty header may have been added by the user after begin.
    tomllib.loads(merged)
    if not merged and original is None:
        return None
    return merged.encode()


def private_write(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(content)


def conflict_record(config: Path, backup: Path) -> tuple[bool, bool]:
    """Preserve only safely readable bytes; recording failure must not block recovery."""
    captured = False
    try:
        latest = read(config)
        if latest is not None:
            private_write(backup / "config-current.toml", latest)
            captured = True
    except (ValueError, OSError):
        # This is an explicit partial-recovery result, not a successful rollback.
        # Never follow links or publish file contents to explain a refusal.
        captured = False
    recorded = False
    try:
        result = {"status": "configuration_conflict", "current_snapshot": "saved" if captured else "unavailable"}
        private_write(backup / "result.json", (json.dumps(result) + "\n").encode())
        recorded = True
    except OSError:
        recorded = False
    return captured, recorded


def restore(config: Path, backup: Path, state: Path) -> None:
    try:
        original = read(backup / "config.toml")
        current = read(config)
        restored = merge(original, current, state, read(backup / "config-expected.toml"))
        if restored == current:
            return
        descriptor, filename = tempfile.mkstemp(prefix=".jev-config-restore-", dir=config.parent)
        replacement = Path(filename)
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(restored or b"")
            if read(config) != current:
                raise ValueError("configuration conflict: file changed during rollback")
            if restored is None:
                config.unlink(missing_ok=True)
            else:
                replacement.replace(config)
        finally:
            replacement.unlink(missing_ok=True)
    except (ValueError, OSError) as error:
        captured, recorded = conflict_record(config, backup)
        detail = (f"compare {backup}/config-current.toml with the original config.toml snapshot"
                  if captured else f"current configuration could not be copied safely; compare it locally with {backup}/config.toml")
        if not recorded:
            detail += "; the private conflict record could not be written"
        raise ValueError(f"configuration rollback conflict; current configuration was not overwritten; {detail} before retrying") from error
