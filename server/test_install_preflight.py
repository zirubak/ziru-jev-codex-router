"""Installation preflight fails before configuration or services change."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class InstallPreflightTests(unittest.TestCase):
    def test_missing_key_stops_shell_before_dependency_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'router/bin').mkdir(parents=True)
            (root / 'server').mkdir()
            (root / 'install.sh').write_bytes((ROOT / 'install.sh').read_bytes())
            (root / 'install.sh').chmod(0o755)
            cli = root / 'router/bin/codex-router'
            cli.write_text('#!/bin/sh\nexit 0\n')
            cli.chmod(0o755)
            (root / 'router/bin/install').write_text('#!/bin/sh\necho MUTATED\n')
            (root / 'router/bin/install').chmod(0o755)
            (root / 'server/install_preflight.py').write_text(
                'import sys\nprint("TypeSafe key missing", file=sys.stderr)\nsys.exit(1)\n')
            result = subprocess.run(['sh', str(root / 'install.sh')],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('TypeSafe key missing', result.stderr)
            self.assertNotIn('MUTATED', result.stdout)

    def test_service_uses_the_checked_python(self) -> None:
        source = (ROOT / 'server/install-service.sh').read_text()
        self.assertIn('JEV_PYTHON', source)
        self.assertNotIn('command -v /usr/local/bin/python3', source)

    def test_key_missing_permissions_and_symlink_fail_closed(self) -> None:
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.jev.env'
            with mock.patch.dict(module.os.environ, {'JEV_ENV_FILE': str(path)}):
                with self.assertRaises(RuntimeError):
                    module.check_key()
                path.write_text('TYPESAFE_API_KEY=synthetic-test-value\n')
                path.chmod(0o644)
                with self.assertRaises(RuntimeError):
                    module.check_key()
                path.chmod(0o600)
                module.check_key()
                link = path.with_name('link')
                link.symlink_to(path)
                with mock.patch.dict(module.os.environ, {'JEV_ENV_FILE': str(link)}):
                    with self.assertRaises(RuntimeError):
                        module.check_key()

    def test_runtime_and_login_failures(self) -> None:
        module = self.module()
        with mock.patch.object(module.sys, 'platform', 'linux'):
            with self.assertRaises(RuntimeError):
                module.check_runtime()
        with mock.patch.object(module.sys, 'platform', 'darwin'), \
                mock.patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v22.18.0')):
            with self.assertRaises(RuntimeError):
                module.check_runtime()
        with mock.patch.object(module.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, '/fixture/codex'), subprocess.CompletedProcess([], 1)]):
            with self.assertRaises(RuntimeError):
                module.check_login()

    def test_parent_router_foreign_port_is_refused(self) -> None:
        module = self.module()
        with mock.patch.object(module.socket, 'create_connection'), \
                mock.patch.object(module, 'managed_router', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '4202'):
                module.check_router_port()

    def test_login_uses_embedded_binary_resolver(self) -> None:
        module = self.module()
        binary = '/Applications/Codex.app/Contents/Resources/codex'
        with mock.patch.object(module.subprocess, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, binary + '\n'),
                subprocess.CompletedProcess([], 0)]) as run:
            module.check_login()
            self.assertEqual(run.call_args_list[1].args[0][0], binary)

    def module(self):
        spec = importlib.util.spec_from_file_location('install_preflight', ROOT / 'server/install_preflight.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_foreign_port_listener_is_refused(self) -> None:
        module = self.module()
        with mock.patch.object(module.socket, 'create_connection'), \
                mock.patch.object(module, 'managed_jev', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '4319'):
                module.check_jev_port()

    def test_managed_listener_allows_repeat_install(self) -> None:
        module = self.module()
        with mock.patch.object(module.socket, 'create_connection'), \
                mock.patch.object(module, 'managed_jev', return_value=True):
            module.check_jev_port()

    def test_prepare_only_skips_key_login_and_service_checks(self) -> None:
        module = self.module()
        with mock.patch.object(module, 'check_runtime'), \
                mock.patch.object(module, 'check_key') as key, \
                mock.patch.object(module, 'check_login') as login, \
                mock.patch.object(module, 'check_jev_port') as port:
            module.run(prepare=True)
            key.assert_not_called()
            login.assert_not_called()
            port.assert_not_called()

    def test_empty_key_file_is_refused_without_echoing_contents(self) -> None:
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.jev.env'
            path.write_text('TYPESAFE_API_KEY=\n')
            path.chmod(0o600)
            with mock.patch.dict(module.os.environ, {'JEV_ENV_FILE': str(path)}):
                with self.assertRaisesRegex(RuntimeError, 'missing'):
                    module.check_key()


if __name__ == '__main__':
    unittest.main()
