import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import agent_routes
from auth import CurrentUser
from sandbox.base import MAX_WORKSPACE_DOWNLOAD_BYTES, WorkspaceDownloadTooLarge
from sandbox.native import NativeSandbox, READ_FILE_LIMITED_SCRIPT
from test_workspace_file_safety import _TempSandbox


class WorkspaceDownloadLimitTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sandbox = _TempSandbox(str(self.root))

    def test_normal_file_and_preview_keep_working(self):
        (self.root / 'report.txt').write_bytes(b'hello')
        self.assertEqual(self.sandbox.read_file_for_download(1, 'report.txt'), (b'hello', 'report.txt'))
        self.assertEqual(self.sandbox.read_file_limited(1, 'report.txt', 3), (b'hell', 'report.txt'))

    def test_oversized_file_rejected_before_read_and_handle_closed(self):
        with (self.root / 'large.bin').open('wb') as handle:
            handle.truncate(MAX_WORKSPACE_DOWNLOAD_BYTES + 1)
        real_fdopen = os.fdopen
        opened = []
        class CheckedFile:
            def __init__(self, handle):
                self.handle = handle
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                self.handle.close()
            def fileno(self):
                return self.handle.fileno()
            def read(self, *_args):
                raise AssertionError('Oversized files must be rejected before reading')
        def record(*args):
            handle = real_fdopen(*args)
            opened.append(handle)
            return CheckedFile(handle)
        with patch('sandbox.base.os.fdopen', side_effect=record), self.assertRaises(WorkspaceDownloadTooLarge):
            self.sandbox.read_file_for_download(1, 'large.bin')
        self.assertTrue(opened[0].closed)
        self.assertEqual((self.root / 'large.bin').stat().st_size, MAX_WORKSPACE_DOWNLOAD_BYTES + 1)

    def test_size_growth_after_stat_is_still_bounded(self):
        (self.root / 'growing.txt').write_bytes(b'12345')
        metadata = SimpleNamespace(st_mode=(self.root / 'growing.txt').stat().st_mode, st_size=1)
        with patch('sandbox.base.os.fstat', return_value=metadata), self.assertRaises(WorkspaceDownloadTooLarge):
            self.sandbox.read_file_limited(1, 'growing.txt', 4, reject_oversized=True)
        self.assertEqual(self.sandbox.read_file_limited(1, 'growing.txt', 5, reject_oversized=True)[0], b'12345')

    def test_parent_paths_and_symbolic_links_remain_forbidden(self):
        with self.assertRaises(ValueError):
            self.sandbox.read_file_for_download(1, '../outside.txt')
        (self.root / 'target.txt').write_bytes(b'content')
        try:
            (self.root / 'link.txt').symlink_to(self.root / 'target.txt')
        except OSError:
            self.skipTest('symlink creation not permitted')
        with self.assertRaises(ValueError):
            self.sandbox.read_file_for_download(1, 'link.txt')

    def test_native_helper_checks_size_before_emitting_bytes(self):
        path = self.root / 'native.bin'
        path.write_bytes(b'12345')
        def run(limit, reject, target=path):
            return subprocess.run([sys.executable, '-c', READ_FILE_LIMITED_SCRIPT,
                                   str(target), str(self.root), str(limit), reject],
                                  capture_output=True, timeout=10)
        denied = run(4, '1')
        self.assertEqual(denied.returncode, 43)
        self.assertEqual(denied.stdout, b'')
        accepted = run(5, '1')
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout, b'12345')
        self.assertEqual(run(2, '0').stdout, b'123')
        self.assertEqual(run(4, '1', self.root.parent / 'outside.txt').returncode, 41)
        native = NativeSandbox.__new__(NativeSandbox)
        with patch.object(native, '_resolve_workspace_path', return_value=str(path)), \
             patch.object(native, '_workspace', return_value=str(self.root)), \
             patch.object(native, '_run_root_bytes', return_value=denied):
            with self.assertRaises(WorkspaceDownloadTooLarge):
                native.read_file_for_download(1, 'native.bin')

    def test_download_route_returns_413_and_uses_bounded_provider(self):
        (self.root / 'small.txt').write_bytes(b'hello')
        agent = SimpleNamespace(id=1)
        with patch.object(agent_routes, 'get_usable_agent', return_value=agent), \
             patch.object(agent_routes, 'bind_agent_workspace', return_value=(1, None)), \
             patch.object(agent_routes, 'get_workspace_provider', return_value=self.sandbox), \
             patch.object(self.sandbox, 'read_file', side_effect=AssertionError('unbounded download')):
            response = agent_routes.download_workspace_file(1, 'small.txt', None, CurrentUser(7))
            self.assertEqual(response.body, b'hello')
            with patch.object(self.sandbox, 'read_file_for_download', side_effect=WorkspaceDownloadTooLarge('too large')):
                with self.assertRaises(HTTPException) as error:
                    agent_routes.download_workspace_file(1, 'large.bin', None, CurrentUser(7))
            self.assertEqual(error.exception.status_code, 413)


if __name__ == '__main__':
    unittest.main()
