"""WSL process-lifecycle checks; no databases, credentials or business services."""
import json
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

import aihub_stack as stack


class EnvBootstrapTests(unittest.TestCase):
    def test_missing_env_is_copied_and_existing_env_is_kept(self):
        with tempfile.TemporaryDirectory(prefix='aihub-env-test-') as directory:
            project = Path(directory)
            source = project / '.env.local'
            source.write_bytes(b'EXAMPLE=value\n')
            target = stack.ensure_env_file(project, 'example', True)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            source.write_bytes(b'EXAMPLE=changed\n')
            stack.ensure_env_file(project, 'example', True)
            self.assertEqual(target.read_bytes(), b'EXAMPLE=value\n')
            self.assertTrue(source.is_file())

    def test_doctor_does_not_create_env_and_missing_template_fails(self):
        with tempfile.TemporaryDirectory(prefix='aihub-env-test-') as directory:
            project = Path(directory)
            (project / '.env.local').write_text('EXAMPLE=value\n')
            with self.assertRaisesRegex(RuntimeError, 'Missing example configuration'):
                stack.ensure_env_file(project, 'example', False)
            self.assertFalse((project / '.env').exists())
            (project / '.env.local').unlink()
            with self.assertRaisesRegex(RuntimeError, 'Missing example configuration'):
                stack.ensure_env_file(project, 'example', True)

    def test_stack_uses_repository_root_for_backend_env(self):
        with tempfile.TemporaryDirectory(prefix='aihub-project-test-') as directory:
            root = Path(directory)
            projects = {'iam': root / 'iam', 'gateway': root / 'gateway',
                        'backend': root / 'aihub' / 'backend'}
            for project in projects.values():
                project.mkdir(parents=True)
                (project / 'requirements.txt').touch()
            aihub = projects['backend'].parent
            for project in (projects['iam'], projects['gateway'], aihub):
                (project / '.env.local').write_text('EXAMPLE=value\n')
            arguments = ['aihub_stack.py', 'install', '--gateway-root', str(projects['gateway']),
                         '--iam-root', str(projects['iam'])]
            with patch.object(stack, 'ROOT', aihub), patch.object(sys, 'argv', arguments), \
                    patch.object(stack, 'venv', side_effect=RuntimeError('stop before dependency installation')):
                with self.assertRaisesRegex(RuntimeError, 'stop before dependency installation'):
                    stack.main()
            self.assertTrue((aihub / '.env').is_file())
            self.assertTrue((projects['iam'] / '.env').is_file())
            self.assertTrue((projects['gateway'] / '.env').is_file())
            self.assertFalse((projects['backend'] / '.env').exists())


class ProcessLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aihub-stack-test-')
        self.state = Path(self.temp.name)
        self.patch = patch.object(stack, 'STATE', self.state)
        self.patch.start()
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        self.patch.stop()
        self.temp.cleanup()

    def service(self, name):
        started = []
        process = stack.start_service(name, sys.executable, self.state, ['-c', 'import time; time.sleep(60)'],
                                      dict(__import__('os').environ), 'test-settings', started)
        self.processes.append(process)
        return started

    def test_second_start_reuses_same_process_and_changed_config_requires_restart(self):
        self.service('service')
        original = stack.managed('service')
        started = []
        stack.start_service('service', sys.executable, self.state, [], {}, 'test-settings', started)
        self.assertEqual(started, [])
        self.assertEqual(stack.managed('service'), original)
        with self.assertRaisesRegex(RuntimeError, 'different launch settings'):
            stack.start_service('service', sys.executable, self.state, [], {}, 'different', [])

    def test_stale_identity_cannot_kill_a_live_process(self):
        self.service('service')
        path = stack.state_file('service')
        record = json.loads(path.read_text())
        pid = record['identity']['pid']
        record['identity']['start'] = 'invalid-start-time'
        path.write_text(json.dumps(record))
        stack.stop('service')
        self.assertIsNotNone(stack.identity(pid))

    def test_host_rollback_only_stops_new_processes_from_its_transaction(self):
        self.service('previous')
        self.service('new')
        transaction = uuid.uuid4()
        record = stack.managed('new')
        (self.state / f'transaction-{transaction.hex}.json').write_text(json.dumps([
            {'name': 'new', 'identity': record['identity']}
        ]))
        arguments = [
            'aihub_stack.py', 'rollback',
            '--gateway-root', str(self.state), '--iam-root', str(self.state),
            '--transaction', str(transaction),
        ]
        with patch.object(sys, 'argv', arguments):
            stack.main()
        self.assertIsNotNone(stack.managed('previous'))
        self.assertIsNone(stack.managed('new'))

    def restart_context(self):
        root = self.state / 'aihub'
        gateway = self.state / 'gateway'
        iam = self.state / 'iam'
        for project in (root / 'backend', gateway, iam):
            project.mkdir(parents=True, exist_ok=True)
            (project / 'requirements.txt').touch()
        for project in (root, gateway, iam):
            (project / '.env').write_text('EXAMPLE=value\n')
        context = ExitStack()
        context.enter_context(patch.object(stack, 'ROOT', root))
        context.enter_context(patch.object(sys, 'argv', ['aihub_stack.py', 'restart',
                              '--gateway-root', str(gateway), '--iam-root', str(iam)]))
        context.enter_context(patch.object(stack, 'venv', return_value=sys.executable))
        context.enter_context(patch.object(stack, 'backend_preflight', return_value={'channels': False}))
        context.enter_context(patch.object(stack, 'service_config', return_value={
            'assertion': 'matching-fingerprint',
            'overrides': {'/aihub': 'http://127.0.0.1:15174', '/iam': 'http://127.0.0.1:9001'}}))
        return context

    def test_restart_dependency_failure_keeps_all_existing_processes(self):
        for name in ('iam', 'backend', 'channel-worker', 'gateway'):
            self.service(name)
        original = {name: stack.managed(name) for name in ('iam', 'backend', 'channel-worker', 'gateway')}
        for failing_service in ('backend', 'iam', 'gateway'):
            with self.subTest(service=failing_service), self.restart_context(), \
                    patch.object(stack, 'dependency_preflight') as check:
                def dependency(name, *args):
                    if name == failing_service:
                        raise RuntimeError('dependency unavailable')
                check.side_effect = dependency
                with self.assertRaisesRegex(RuntimeError, 'dependency unavailable'):
                    stack.main()
            for name, record in original.items():
                self.assertEqual(stack.managed(name), record)

    def test_restart_unknown_port_failure_keeps_existing_process(self):
        import socket
        self.service('backend')
        original = stack.managed('backend')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.restart_context(), patch.object(stack, 'dependency_preflight'), \
                    patch.object(stack, 'check_service_port',
                                 side_effect=lambda *args, **kwargs: port_check('gateway', port)):
                with self.assertRaisesRegex(RuntimeError, 'unmanaged process'):
                    stack.main()
        self.assertEqual(stack.managed('backend'), original)


port_check = stack.check_service_port


class LocalTemplateTests(unittest.TestCase):
    def test_new_clone_does_not_join_a_shared_channel_worker_pool(self):
        values = dict(line.split('=', 1) for line in (stack.ROOT / '.env.local').read_text().splitlines()
                      if '=' in line and not line.lstrip().startswith('#'))
        self.assertEqual(values['WEIXIN_ILINK_ENABLED'].lower(), 'false')
        self.assertEqual(values['DINGTALK_ENABLED'].lower(), 'false')


@unittest.skipUnless(os.environ.get('AIHUB_TEST_GATEWAY_ROOT') and os.environ.get('AIHUB_TEST_GATEWAY_PYTHON'),
                     'Set AIHUB_TEST_GATEWAY_ROOT/PYTHON to test the real Gateway configuration loader')
class GatewayConfigTests(unittest.TestCase):
    def config(self, environment_overrides, personal):
        environment = dict(os.environ, ROUTE_TARGET_OVERRIDES=json.dumps(environment_overrides),
                           ROUTE_PREFIX_ALIASES=json.dumps({'/iam-service': '/iam', '/common-service': '/common'}))
        return stack.service_config(os.environ['AIHUB_TEST_GATEWAY_PYTHON'],
                                    Path(os.environ['AIHUB_TEST_GATEWAY_ROOT']), environment,
                                    [{'/iam': 'http://127.0.0.1:9001', '/aihub': 'http://127.0.0.1:15174'}, personal])

    def test_aliases_across_layers_follow_priority_and_keep_other_services(self):
        config = self.config({'/iam-service': 'http://localhost:19001', '/common-service': 'http://common:8000'},
                             {'/iam-service/': 'http://localhost:29001/'})
        self.assertEqual(config['overrides'], {'/iam': 'http://localhost:29001',
                                             '/aihub': 'http://127.0.0.1:15174', '/common': 'http://common:8000'})

    def test_conflicting_aliases_in_one_layer_fail_without_printing_targets(self):
        with self.assertRaisesRegex(RuntimeError, 'conflicting aliases') as error:
            self.config({}, {'/iam': 'http://one', '/iam-service': 'http://two'})
        self.assertNotIn('http://one', str(error.exception))

    def test_invalid_override_url_does_not_expose_credentials(self):
        with self.assertRaises(RuntimeError) as error:
            self.config({}, {'/common-service': 'http://user:SECRET-MUST-NOT-LEAK@localhost'})
        self.assertNotIn('SECRET-MUST-NOT-LEAK', str(error.exception))


if __name__ == '__main__':
    unittest.main()
