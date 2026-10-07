"""App tool runtime ownership and signed executable validation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import install_desktop
import install_transaction


class AppToolRuntimeTests(unittest.TestCase):
    def test_runtime_signature_and_executable_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            app = Path(name) / "ChatGPT.app"
            node = app / "Contents/Resources/cua_node/bin/node"
            node.parent.mkdir(parents=True)
            node.write_text("fixture")
            node.chmod(0o700)
            with patch.object(install_desktop.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                    subprocess.CompletedProcess([], 0, stdout="v22.19.0\n", stderr="")]) as run:
                self.assertEqual(install_desktop.trusted_node(app), node)
                self.assertIn('certificate leaf[subject.OU] = "2DC432GLL2"', run.call_args_list[0].args[0][-2])
                self.assertEqual(run.call_args_list[1].args[0], [str(node), "--version"])
            with patch.object(install_desktop.subprocess, "run", return_value=
                              subprocess.CompletedProcess([], 1, stdout="", stderr="private output")):
                with self.assertRaisesRegex(ValueError, "signature"):
                    install_desktop.trusted_node(app)
            node.chmod(0o600)
            with self.assertRaises(ValueError):
                install_desktop.trusted_node(app)
            node.unlink()
            node.symlink_to("/bin/sh")
            with self.assertRaises(ValueError):
                install_desktop.trusted_node(app)

    def test_owned_override_preserves_unrelated_env_and_is_idempotent(self) -> None:
        original = ('# user comment\nmodel="gpt-6.1-sol"\n'
                    '[plugins."codex-app-tools@openai-bundled".mcp_servers.codex_app.env]\n'
                    'KEEP="user" # preserve\n[projects."/mine"]\ntrust_level="trusted"\n')
        updated = install_desktop.app_tools_config(original, Path("/signed/node"))
        self.assertEqual(updated, install_desktop.app_tools_config(updated, Path("/signed/node")))
        self.assertIn('KEEP="user" # preserve\n', updated)
        self.assertIn('[projects."/mine"]\ntrust_level="trusted"\n', updated)
        env = tomllib.loads(updated)["plugins"]["codex-app-tools@openai-bundled"]["mcp_servers"]["codex_app"]["env"]
        self.assertEqual(env, {"KEEP": "user", "CODEX_MCP_NODE_PATH": "/signed/node"})
        revised = install_desktop.app_tools_config(updated, Path("/updated/node"))
        self.assertIn(json.dumps("/updated/node"), revised)

    def test_foreign_or_tampered_override_is_rejected(self) -> None:
        header = '[plugins."codex-app-tools@openai-bundled".mcp_servers.codex_app.env]\n'
        for original in (header + 'CODEX_MCP_NODE_PATH="/user/node"\n',
                         header + 'CODEX_MCP_NODE_PATH="/signed/node"\n'):
            with self.assertRaisesRegex(ValueError, "ownership"):
                install_desktop.app_tools_config(original, Path("/signed/node"))
        updated = install_desktop.app_tools_config('', Path('/signed/node'))
        with self.assertRaises(ValueError):
            install_desktop.app_tools_config(updated.replace('CODEX_MCP_NODE_PATH =', 'USER_KEY ='), Path('/signed/node'))
        with self.assertRaises(ValueError):
            install_desktop.app_tools_config('text="""\n' + updated + '"""\n', Path('/signed/node'))

    def test_root_transaction_restores_runtime_override_and_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            codex = root / "codex"
            state = codex / "codex-router"
            desktop = state / "desktop"
            desktop.mkdir(parents=True)
            config = codex / "config.toml"
            original = b'model="gpt-6.1-sol"\n'
            config.write_bytes(original)
            config.chmod(0o600)
            wrapper = desktop / "jev-codex"
            wrapper.write_bytes(b'#!/bin/sh\nexec /old/node "$@"\n')
            wrapper.chmod(0o700)
            with patch.dict(os.environ, {"CODEX_HOME": str(codex), "MODEL_ROUTER_STATE_DIR": str(state)}), \
                    patch.object(install_transaction.sys, "platform", "linux"):
                backup = install_transaction.begin()
                config.write_text(install_desktop.app_tools_config(original.decode(), Path('/signed/node')))
                wrapper.write_bytes(b'#!/bin/sh\nexec /signed/node "$@"\n')
                install_transaction.restore(backup)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(wrapper.read_bytes(), b'#!/bin/sh\nexec /old/node "$@"\n')
